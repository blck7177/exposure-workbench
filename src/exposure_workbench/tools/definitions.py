"""The functions behind the desk's reads (V23), and the pause.

Until V1 this module registered the desk's tools by DATA DOMAIN × VERB — describe,
read_fundamentals, read_filings, read_prices, read_book, compute — and, from V30,
`run`, which took a program in a language of its own. V1 retired that surface:
the tools an agent holds are the twelve primitive verbs of tools/primitives, and
each of them is a thin wrapper over a function that lives HERE, where it has
always been — `_read_fundamentals`, `_read_filings`, `_read_prices`, and the
identity check they share. `think`, the research run's free pause, is the one
tool still registered from this module.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import FinancialFact
from exposure_workbench.services import fundamentals_service
from exposure_workbench.services import company_service
from exposure_workbench.services import filing_retrieval_service as frs
from exposure_workbench.services import price_analytics_service as pas
from exposure_workbench.services import security_master_service
from exposure_workbench.tools.registry import REFLECTION, Tool, ToolRegistry, current_session_id


# ── shared ──────────────────────────────────────────────────────────────────────

async def _resolve_company(db: AsyncSession, ticker: str) -> dict:
    """Identity, or a typed refusal that says what to do about it."""
    tk = ticker.upper()
    try:
        c = await company_service.get_by_ticker(db, tk)
    except company_service.CompanyNotFound:
        if await security_master_service.is_in_universe(db, tk):
            return {"error": "not_prepared", "ticker": tk,
                    "detail": f"{tk} is a listed security this desk has not prepared yet, so "
                              f"it holds no filings or facts for it. start(kind='readiness') "
                              f"puts it on the desk; the work runs in the background."}
        return {"error": "company_not_found", "ticker": tk}
    return {"id": c.id, "ticker": c.ticker, "name": c.name, "cik": c.cik,
            "exchange": c.exchange, "sector": c.sector, "industry": c.industry,
            "is_investigable": c.is_investigable}


# ── read_fundamentals ───────────────────────────────────────────────────────────

async def _metric_is_instant(db: AsyncSession, company_id: str, metric: str) -> bool | None:
    """Whether a metric is filed as balances (instants) — decided from the facts,
    not from a list: a row with no period_start is an instant."""
    row = (await db.execute(
        select(FinancialFact.period_start).where(
            FinancialFact.company_id == company_id, FinancialFact.normalized_metric == metric)
        .limit(1))).first()
    if row is None:
        return None
    return row[0] is None


async def _read_fundamentals(db: AsyncSession, ticker: str, metric: str | None = None,
                             months: int | None = None, start: str | None = None,
                             end: str | None = None, last_n: int | None = None,
                             at: str | None = None) -> dict:
    """One issuer's filed figures. No metric: every balance at one instant.
    A metric: a flow over a window (months, or start..end), a series of the
    last N windows or readings (last_n), or a balance at an instant (at)."""
    company = await _resolve_company(db, ticker)
    if company.get("error"):
        return company
    tk = company["ticker"]
    invoked_by = current_session_id()
    if metric is None:
        return await fundamentals_service.get_balance_sheet(db, tk, at=at, invoked_by=invoked_by)
    instant = await _metric_is_instant(db, company["id"], metric)
    if instant is None:
        from exposure_workbench.services import calc_service as cs
        from exposure_workbench.services.concept_mapping import SUPPORTED_METRICS
        have = sorted(m["metric"] for m in (await cs.list_available_metrics(db, tk))["metrics"])
        return {"error": "metric_not_filed", "ticker": tk, "metric": metric,
                # The refusal is about THIS argument's value: a batch of reads
                # for other metrics is not held behind it (agents/batch.py).
                "held_on": {"metric": metric},
                "available": have,
                "detail": (f"{tk} has no filed facts under {metric!r}"
                           + ("" if metric in SUPPORTED_METRICS else
                              f"; {metric!r} is not a metric this desk maps")
                           + "; the names it does hold are in `available`")}
    if instant:
        if last_n is not None:
            return await fundamentals_service.get_balance_series(db, tk, metric, last_n=int(last_n),
                                                                 invoked_by=invoked_by)
        sheet = await fundamentals_service.get_balance_sheet(db, tk, at=at, invoked_by=invoked_by)
        if sheet.get("error"):
            return sheet
        balances = sheet.get("balances") or {}
        if metric in balances:
            # ONE LINE WAS ASKED, so one line is answered: the sheet's note of which
            # OTHER lines are not reported at this date is about lines nobody named.
            # Left in, the smoke read of MSFT inventory came back with a second row,
            # commercial paper at $0.00, dated to a sheet it was never on.
            one = {k: v for k, v in sheet.items() if k != "not_reported_at_this_date"}
            return {**one, "balances": {metric: balances[metric]},
                    "detail": f"{metric} is a balance (an instant); the whole sheet at this date "
                              f"is read with the line omitted"}
        return {"error": "not_reported_at_this_date", "ticker": tk, "metric": metric,
                "as_of": sheet.get("as_of"),
                "last_reported": (sheet.get("not_reported_at_this_date") or {}).get(metric),
                "detail": "ask with `at` set to the date it was last reported, or last_n for its history"}
    return await fundamentals_service.get_flow(
        db, tk, metric, months=(int(months) if months is not None else None), start=start, end=end,
        last_n=(int(last_n) if last_n is not None else None), invoked_by=invoked_by)


# ── read_filings ────────────────────────────────────────────────────────────────

async def _read_filings(db: AsyncSession, ticker: str, query: str | None = None, item: str | None = None,
                        k: int = 5, form_type: str | None = None) -> dict:
    company = await _resolve_company(db, ticker)
    if company.get("error"):
        return company
    tk = company["ticker"]
    if (query is None) == (item is None):
        return {"error": "query_or_item", "detail": "give exactly one of `query` (search the "
                                                    "passages) or `item` (one Item verbatim, e.g. '1A', '7')"}
    if item is not None:
        code = item if item.lower().startswith("item") else f"Item {item}"
        section = await frs.get_section(db, company["id"], code, form_type=form_type)
        if section is None:
            return {"error": "section_not_found", "ticker": tk, "item": code}
        return {"ticker": tk, "item_code": section.item_code, "title": section.title, "text": section.text,
                "citation": {"type": "chunk", "accession": section.accession_number,
                             "form_type": section.form_type, "item": section.item_code,
                             "source_url": section.source_url}}
    try:
        passages = await frs.search_passages(db, company["id"], query, k=int(k), form_type=form_type)
    except frs.NotIndexed:
        return {"error": "not_indexed", "ticker": tk,
                "hint": "start(kind='readiness') indexes this company's filings first"}
    return {"ticker": tk, "query": query,
            "passages": [{"chunk_id": p.chunk_id, "text": p.text, "score": round(p.score, 4),
                          "item": p.item_code, "section_title": p.section_title,
                          "citation": p.citation()} for p in passages]}


# ── read_prices ─────────────────────────────────────────────────────────────────

async def _read_prices(db: AsyncSession, ticker: str, window: str | None = None,
                       as_of: str | None = None) -> dict:
    """A series over a named window, or — with no window — one session's price."""
    invoked_by = current_session_id()
    if window is not None:
        return await pas.get_price_series(db, ticker.upper(), window=window, invoked_by=invoked_by)
    return await pas.get_price(db, ticker.upper(), as_of=as_of, invoked_by=invoked_by)


# ── reflection ──────────────────────────────────────────────────────────────────

async def _think(db: AsyncSession, thought: str) -> dict:
    """Low-friction pause: no side effect, no budget, only a trace line."""
    return {"noted": True, "thought": thought[:400]}


# ── registration ────────────────────────────────────────────────────────────────

_TICKER = {"type": "string", "description": "ticker, e.g. NVDA"}
_FORM_TYPE = {"type": ["string", "null"], "enum": ["10-K", "10-Q", "10-K/A", "10-Q/A", None],
              "description": "narrow to one form; omit for any"}


def register_think(reg: ToolRegistry) -> ToolRegistry:
    reg.register(Tool(
        name="think",
        display="Thinking",
        description="Pause and note a thought. Free; no evidence; never an answer.",
        json_schema={"type": "object", "properties": {"thought": {"type": "string"}},
                     "required": ["thought"], "additionalProperties": False},
        fn=_think, tool_class=REFLECTION,
    ))
    return reg
