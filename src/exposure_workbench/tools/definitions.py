"""Tool definitions — the desk's data domains, one tool each (V23).

The agent's tools are organised by DATA DOMAIN × VERB, not by question
(IMPLEMENTATION_PLAN_V23 §2). Every tool sits in exactly one cell:

    describe(subject)        what the desk holds about a subject, across every domain,
                             what it means, what is missing, which methods apply
    read_fundamentals        an issuer's filed figures (a window, an instant, a series)
    read_filings             an issuer's filing text (a search, or one Item verbatim)
    read_prices              a name's daily closes (a series, or one session's price)
    read_book                a run's or scenario's figures by name; a portfolio's
                             positions, limits, alerts; a brief; a task's state
    compute                  the ONE place a figure is computed: an op over operands,
                             or a registry method over a subject   (compute_service)
    think                    a pause, free
    + start, respond (tools/meta_tools), search_web, submit_brief (tools/research_tools)

Every fn is a THIN wrapper over a service; what a result puts on the table is
made Facts by its adapter (services/fact_adapters, by tool name). Descriptions are one or two lines:
WHEN to use a tool is the agent's judgement, informed by describe and by the
skill registry, not a sentence in a description — that is the whole point of
the collapse from 44 tools to ten.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import skill
from exposure_workbench.analytics import withheld as _wh
from exposure_workbench.db.models import CalcLedger, Company, FinancialFact, RiskAlert
from exposure_workbench.services import brief_service, catalogue_service, compute_service
from exposure_workbench.services import fundamentals_service
from exposure_workbench.services import name_table as nt
from exposure_workbench.services import company_service
from exposure_workbench.services import filing_retrieval_service as frs
from exposure_workbench.services import job_status_service
from exposure_workbench.services import portfolio_service
from exposure_workbench.services import price_analytics_service as pas
from exposure_workbench.services import run_reads_service
from exposure_workbench.services import security_master_service
from exposure_workbench.services import quantities as qn
from exposure_workbench.services.typed_calculator import SCENARIO_OP
from exposure_workbench.tools.registry import (
    READ, REFLECTION, Shapes, Tool, ToolRegistry, current_session_id,
)


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


# ── describe ────────────────────────────────────────────────────────────────────

async def _describe(db: AsyncSession, subject: str | None = None, expand: str | None = None) -> dict:
    out = await catalogue_service.describe(db, subject, expand)
    if out.get("error"):
        return out
    # What this call puts on the table, by exact name (Evidence names_from):
    # a run's or scenario's every name; an issuer's place in each book it is
    # held in. Nothing else — a catalogue is a map, not the territory.
    kind = out.get("kind")
    if kind in ("run", "scenario"):
        resolved = await qn.of_ref(db, subject)
        out["table_names"] = {subject: [q.label for q in resolved.quantities if q.not_alone is None]}
    elif kind == "issuer":
        out["table_names"] = {h["run_id"]: h["names"] for h in (out.get("book") or {}).get("held_in", [])}
    return out


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
                **({"route": _routes([metric], ticker=tk)} if nt.get(metric) else {}),
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
            return {**sheet, "balances": {metric: balances[metric]},
                    "detail": f"{metric} is a balance (an instant); the whole sheet at this date "
                              f"is read with metric omitted"}
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


# ── read_book ───────────────────────────────────────────────────────────────────

_PORTFOLIO_SECTIONS = nt.PORTFOLIO_SECTIONS
_RUN_SECTIONS = nt.RUN_SECTIONS


def _routes(names: list[str], *, ref: str | None = None, ticker: str | None = None) -> dict:
    """For each name the name table knows: what it is and the call that uses it
    (V27). The subject is the caller's own ref when the name's kind takes one of
    that kind, a placeholder otherwise — the refusal teaches the address, it
    does not perform the call."""
    out = {}
    for n in names:
        e = nt.get(n)
        if e is None:
            continue
        subj = None
        if e.subject_kind in ("issuer", "price"):
            subj = ticker
        elif e.subject_kind == "run" and ref and ref.startswith(("run_", "calc_")):
            subj = ref
        elif e.subject_kind == "portfolio" and ref and ref.startswith("port_"):
            subj = ref
        elif e.kind in ("filed line", "filing item"):
            subj = ticker
        out[n] = nt.route(n, subject=subj, ref=ref)
    return out


async def _read_book(db: AsyncSession, ref: str, names: list[str]) -> dict:
    """Figures by name from a run or a scenario row; a portfolio's sections; a
    brief; a task's state. One tool for everything the desk holds about its
    own work, so the model learns one spelling: read_book(ref, names)."""
    wanted = [str(n) for n in names]
    if ref.startswith(("task_", "rrun_")):
        return await _task_status(db, ref)
    if ref.startswith("port_"):
        return await _portfolio_sections(db, ref, wanted)
    if ref.startswith("run_"):
        run = await run_reads_service.completed_run(db, ref)        # V28 C1: the one door
        if isinstance(run, dict):
            return run
        sections = [n for n in wanted if n in _RUN_SECTIONS]
        if sections:
            out: dict = {"run_id": ref, "section": {}}
            for s in sections:
                fn = {"alerts": run_reads_service.list_run_alerts,
                      "attribution": run_reads_service.get_attribution,
                      "risk_state": run_reads_service.get_risk_state}[s]
                out["section"][s] = await fn(db, ref)
            rest = [n for n in wanted if n not in _RUN_SECTIONS]
            if rest:
                out["by_name"] = await _quantities_by_name(db, ref, run.as_of_date.isoformat(), rest)
            return out
        return await _quantities_by_name(db, ref, run.as_of_date.isoformat(), wanted)
    if ref.startswith("calc_"):
        row = (await db.execute(select(CalcLedger).where(CalcLedger.id == ref))).scalar_one_or_none()
        if row is None:
            return {"error": "unknown_row", "ref": ref}
        if row.operation != SCENARIO_OP:
            return {"error": "not_a_book", "ref": ref,
                    "detail": "read_book reads a run or a scenario row; a calculator row's figures "
                              "are on its own table under their names"}
        return await _quantities_by_name(db, ref, (row.params or {}).get("as_of"), wanted)
    # a ticker: the desk's products about an issuer
    company = await _resolve_company(db, ref)
    if company.get("error"):
        return company
    out = {"ticker": company["ticker"], "section": {}}
    for n in wanted:
        if n == "brief":
            brief = await brief_service.latest_visible(db, company["id"])
            out["section"]["brief"] = brief or {"error": "no_brief",
                                                 "hint": "start(kind='research') produces one"}
        elif n == "alerts":
            rows = (await db.execute(
                select(RiskAlert).where(RiskAlert.entity_id == company["ticker"])
                .order_by(RiskAlert.created_at.desc()).limit(20))).scalars().all()
            out["section"]["alerts"] = [
                {"id": a.id, "type": a.alert_type, "severity": a.severity, "message": a.message,
                 "as_of": a.created_at.date().isoformat() if a.created_at else None,
                 "utilization": float(a.utilization) if a.utilization is not None else None}
                for a in _wh.published_alerts(rows)]
        else:
            out.setdefault("unknown", []).append(n)
    if out.get("unknown"):
        out["detail"] = "for an issuer, names are 'brief' and 'alerts'; its figures are read_fundamentals"
        routes = _routes(out["unknown"], ticker=company["ticker"])
        if routes:
            out["route"] = routes
    return out


async def _quantities_by_name(db: AsyncSession, ref: str, as_of: str | None, wanted: list[str]) -> dict:
    resolved = await qn.of_ref(db, ref)
    held = {q.label: q for q in resolved.quantities if q.not_alone is None}
    found = [n for n in wanted if n in held]
    unknown = [n for n in wanted if n not in held]
    # V24: the values travel in the payload, under their names — the adapter
    # (services/fact_adapters.read_book) makes each a Fact. `names`/`units`
    # stay for the V23 declaration path until phase C removes it.
    # A name the row does not hold comes back with the five nearest it does
    # (live round 3: `limit_checks.issuer_concentration:MSFT.limit_level` was
    # refused bare, and the model read the breach level as the warning).
    import difflib
    nearest = {n: difflib.get_close_matches(n, list(held), n=5, cutoff=0.5) for n in unknown}
    # V27: a name the table knows — a method, a domain, a filed line — is told
    # what it is and the call that uses it, instead of the nearest ROW names.
    routes = _routes(unknown, ref=ref)
    return {"run_id": ref, "as_of": as_of, "names": found,
            "units": {n: held[n].unit_class for n in found},
            "figures": {n: {"value": held[n].value, "unit_class": held[n].unit_class} for n in found},
            **({"unknown": unknown, "nearest": nearest,
                **({"route": routes} if routes else {}),
                "detail": (f"not names {ref} holds; `route` says what each is and how it is used"
                           if routes else
                           f"not names {ref} holds; `nearest` lists the closest it does; describe('{ref}') lists all")}
               if unknown else {})}


async def _portfolio_sections(db: AsyncSession, pid: str, wanted: list[str]) -> dict:
    p = await portfolio_service.get_portfolio(db, pid)
    if p is None:
        snaps = await portfolio_service.snapshot_all(db)
        return {"error": "unknown_portfolio", "portfolio_id": pid,
                "portfolios": [{"portfolio_id": s["portfolio_id"], "name": s["name"]} for s in snaps],
                "detail": "not a portfolio this desk holds; the ones it does are listed"}
    out: dict = {"portfolio_id": pid, "section": {}}
    for n in wanted:
        if n == "positions":
            out["section"]["positions"] = await portfolio_service.positions_with_weights(db, pid)
        elif n == "limits":
            out["section"]["limits"] = await run_reads_service.list_risk_limits(db, pid)
        elif n == "freshness":
            out["section"]["freshness"] = await run_reads_service.get_run_freshness(db, pid)
        elif n == "runs":
            out["section"]["runs"] = (await catalogue_service.describe(db, pid)).get("runs")
        elif n == "alerts":
            fresh = await run_reads_service.get_run_freshness(db, pid)
            rid = fresh.get("latest_completed_run")
            out["section"]["alerts"] = (await run_reads_service.list_run_alerts(db, rid) if rid
                                        else {"error": "no_completed_run"})
        else:
            out.setdefault("unknown", []).append(n)
    if out.get("unknown"):
        out["detail"] = f"a portfolio's sections are {', '.join(_PORTFOLIO_SECTIONS)}"
        routes = _routes(out["unknown"], ref=pid)
        if routes:
            out["route"] = routes
    return out


async def _task_status(db: AsyncSession, job_id: str) -> dict:
    try:
        row = await job_status_service.status_of(db, job_id)
    except job_status_service.NoOwner:
        return {"error": "sign_in_required", "detail": "task status is per-account"}
    if row is None:
        return {"error": "unknown_job", "job_id": job_id}
    return row


# ── compute ─────────────────────────────────────────────────────────────────────

# Which subject kinds a face's compute may run a method over. The research
# face is issuer-scoped by construction (faces.py): its compute runs issuer
# and price methods and refuses book methods by name, so a brief-writing agent
# cannot reach the holder's book through the one shared tool.
ISSUER_KINDS = ("issuer", "price", "series")
ALL_KINDS = tuple(skill.SUBJECT_KINDS)


def _compute_for(kinds: tuple[str, ...]):
    async def _compute(db: AsyncSession, op: str | None = None, method=None,
                       operands: list[str] | None = None, subject=None, params: dict | None = None,
                       as_quantity: str | None = None, direction: str | None = None) -> dict:
        names = [method] if isinstance(method, str) else list(method or [])
        outside = [m for m in names if m in skill.METHODS and skill.METHODS[m].subject_kind not in kinds]
        if outside:
            return {"error": "not_on_this_face", "methods": outside,
                    "detail": "this face is issuer-scoped; book methods are the meta face's"}
        return await compute_service.compute(db, op=op, method=method, operands=operands, subject=subject,
                                             params=params, as_quantity=as_quantity, direction=direction)
    return _compute


_compute = _compute_for(ALL_KINDS)


# ── reflection ──────────────────────────────────────────────────────────────────

async def _think(db: AsyncSession, thought: str) -> dict:
    """Low-friction pause: no side effect, no budget, only a trace line."""
    return {"noted": True, "thought": thought[:400]}


# ── registration ────────────────────────────────────────────────────────────────

_TICKER = {"type": "string", "description": "ticker, e.g. NVDA"}
_FORM_TYPE = {"type": ["string", "null"], "enum": ["10-K", "10-Q", "10-K/A", "10-Q/A", None],
              "description": "narrow to one form; omit for any"}
_RUN_TABLES = tuple(qn.RUN_TABLES)


def build_read_registry(kinds: tuple[str, ...] = ALL_KINDS) -> ToolRegistry:
    """The read core. `kinds` bounds what this registry's compute may run a
    method over: the research face passes ISSUER_KINDS."""
    reg = ToolRegistry()

    reg.register(Tool(
        name="describe",
        display="Looking at what the desk holds",
        description=(
            "What this desk holds about a subject — a ticker, a portfolio (port_…), a run (run_…), "
            "a scenario row (calc_…); or, with subject omitted, the desk itself: its portfolios with "
            "their ids and latest runs, where a book question starts — across every domain: filed "
            "figures, filing text, prices, its place in the book, briefs; what is NOT held and why; "
            "the methods compute can produce for it and the procedures an analyst follows. Start "
            "here. expand opens one domain's detail."
        ),
        json_schema={"type": "object", "properties": {
            "subject": {"type": ["string", "null"], "description": "ticker | port_… | run_… | calc_… | null for the desk"},
            "expand": {"type": ["string", "null"], "enum": [*catalogue_service.EXPANDS, None]},
        }, "additionalProperties": False},
        fn=_describe, tool_class=READ,
    ))
    reg.register(Tool(
        name="read_fundamentals",
        display="Reading {ticker}'s filed figures",
        description=(
            "An issuer's filed figures. No metric: every balance at one instant (at). A metric: a "
            "flow over a window (months, or start..end), its last N windows or readings (last_n), "
            "or a balance at an instant (at). Every figure arrives with its period and a citable id; "
            "a figure not filed is an absence row, never a substitute."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "metric": {"type": ["string", "null"], "enum": [*nt.TABLE_FILED_LINES, None],
                       "description": "one of the filed lines describe(ticker) lists; null for the whole balance sheet"},
            "months": {"type": ["integer", "null"], "enum": [3, 6, 9, 12, None], "description": "window for a flow (default 12)"},
            "start": {"type": ["string", "null"], "description": "YYYY-MM-DD, with end: an explicit window"},
            "end": {"type": ["string", "null"]},
            "last_n": {"type": ["integer", "null"], "minimum": 1, "maximum": 40, "description": "a series of the last N quarters (flow) or readings (balance)"},
            "at": {"type": ["string", "null"], "description": "YYYY-MM-DD instant for a balance; null = latest"},
        }, "required": ["ticker"], "additionalProperties": False},
        fn=_read_fundamentals, tool_class=READ,
    ))
    reg.register(Tool(
        name="read_filings",
        display="Reading {ticker}'s filings",
        description=(
            "An issuer's filing text: query searches the indexed passages (each a chunk_ id a sentence "
            "can cite and quote verbatim); item reads one Item of the latest filing whole ('1A', '7', '7A'). "
            "Figures stated only in prose (segments, products, customers) are quoted from here, not computed."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "query": {"type": ["string", "null"]},
            "item": {"type": ["string", "null"], "description": "'1', '1A', '7', '7A', … "},
            "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "form_type": _FORM_TYPE,
        }, "required": ["ticker"], "additionalProperties": False},
        shapes=Shapes(("query", "item"),
                      "query searches the passages and item reads one Item whole: "
                      "give one of them, not both"),
        fn=_read_filings, tool_class=READ,
    ))
    reg.register(Tool(
        name="read_prices",
        display="Reading {ticker}'s prices",
        description=(
            "A name's daily adjusted closes over a named window, as one citable series (the level "
            "every return-derived figure is measured on); with no window, one session's close and "
            "adjusted close. Statistics over prices are compute methods (price.*)."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "window": {"type": ["string", "null"], "enum": ["1m", "3m", "6m", "1y", "3y", None]},
            "as_of": {"type": ["string", "null"], "description": "YYYY-MM-DD for a single session; null = latest"},
        }, "required": ["ticker"], "additionalProperties": False},
        fn=_read_prices, tool_class=READ,
    ))
    reg.register(Tool(
        name="compute",
        display="Computing",
        description=(
            "The one place a figure is computed; every result is a citable row. Two shapes. An op over "
            "operands — add/multiply (two or more), subtract/divide (two; or a list with params.by: each "
            "operand divided or multiplied by the one figure `by` names), rank (two or more, with direction), "
            f"regress (two series), or a statistic ({', '.join(compute_service.SERIES_OPS)}) over one "
            "series, or sum/avg/min/max/std over two or more figures — where an operand is a FACT id from a "
            "result's `facts` block (f_…), a fact_/calc_ id, or a figure by name on a run row "
            "(run_…:issuer_exposures.MSFT.weight). Or a method over a subject (a ticker, a run_…, a "
            "port_…) with its params — describe(subject) lists each method with its call; an issuer "
            "measure with params.last_n is its last N periods as one series. method and subject take "
            "lists: ten issuers' net margin is one call. Every result is a fact, so results compose: a "
            "method over a list, then an op over its facts, is two calls. Refusals say why and what would go through."
        ),
        json_schema={"type": "object",
            "$defs": {"method_name": {"type": "string", "enum": nt.method_names(kinds)}},
            "properties": {
            "op": {"type": ["string", "null"], "enum": [*compute_service.OPS, None]},
            "operands": {"type": ["array", "null"], "items": {"type": "string"}, "maxItems": 40},
            "direction": {"type": ["string", "null"], "enum": ["highest", "lowest", None], "description": "for rank"},
            "method": {"type": ["string", "array", "null"], "items": {"$ref": "#/$defs/method_name"}, "maxItems": 40,
                       "if": {"type": "string"}, "then": {"$ref": "#/$defs/method_name"},
                       "description": "a method name from describe(subject), or a list of them"},
            "subject": {"type": ["string", "array", "null"], "items": {"type": "string"}, "maxItems": 40,
                        "description": "ticker | run_… | port_…, or a list"},
            "params": {"type": ["object", "null"], "description": "the method's params (describe lists them)"},
            "as_quantity": {"type": ["string", "null"], "description": "what to call an op's result, e.g. 'dollars_to_sell'"},
        }, "additionalProperties": False},
        # V28 A2: op and method are two shapes of one call, refused before the
        # registry spends a slot — the 2026-09-07 battery paid fifteen slots to
        # be told this by the service.
        shapes=Shapes(("op", "method"),
                      "op and method are two shapes of one call: give op with operands, or method with "
                      "subject, never both. A statistic over a method's results is two calls: the method "
                      "over the list of subjects, then the op over the facts it returned"),
        fn=_compute_for(kinds), tool_class=READ,
    ))
    reg.register(Tool(
        name="think",
        display="Thinking",
        description="Pause and note a thought. Free; no evidence; never an answer.",
        json_schema={"type": "object", "properties": {"thought": {"type": "string"}},
                     "required": ["thought"], "additionalProperties": False},
        fn=_think, tool_class=REFLECTION,
    ))
    register_book_tool(reg)
    return reg


def register_book_tool(reg: ToolRegistry) -> ToolRegistry:
    """read_book is registered on every read registry and listed on the META
    face only (faces.py): a face is what a mount serves, and a registered
    tool outside the face is unknown to that mount (test_mcp_face_scope)."""
    reg.register(Tool(
        name="read_book",
        display="Reading from {ref}",
        description=(
            "The desk's own work, by the names describe lists for that subject. A run or scenario row "
            "(run_…, calc_…): its figures by row name (issuer_exposures.MSFT.weight, "
            "limit_checks.issuer_concentration:MSFT.breach_level, count.alerts) and its sections "
            f"({', '.join(_RUN_SECTIONS)}). A portfolio (port_…): its sections ({', '.join(_PORTFOLIO_SECTIONS)}). "
            "A ticker: brief, alerts. A task (task_…, rrun_…): its state."
        ),
        json_schema={"type": "object", "properties": {
            "ref": {"type": "string"},
            "names": {"type": "array", "minItems": 1, "maxItems": 120, "items": {"type": "string"}},
        }, "required": ["ref", "names"], "additionalProperties": False},
        fn=_read_book, tool_class=READ,
    ))
    return reg
