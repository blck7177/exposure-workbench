"""Tool definitions (M10) — read + reflection tools.

Every fn is a THIN wrapper over a service: it validates/normalizes args and
returns a JSON-able dict whose id-shaped fields the wrapper harvests as evidence
refs. No business logic lives here (that stays in services/analytics), and no
tool touches the network directly.

Delegation and gate tools (ensure_company_ready, start_*, respond, submit_brief)
are registered in P6/P7 where their targets exist.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company, RiskAlert
from exposure_workbench.services import brief_service
from exposure_workbench.services import fundamentals_service, typed_calculator
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import company_service
from exposure_workbench.services import filing_retrieval_service as frs
from exposure_workbench.services import job_status_service
from exposure_workbench.services import portfolio_service
from exposure_workbench.services import trace_service
from exposure_workbench.tools.registry import READ, REFLECTION, Tool, ToolRegistry, current_session_id

_PERIOD_TYPES = ["quarterly", "annual", "instant"]

# A floor as well as a ceiling. load_fact_series does `min(last_n or 40, 40)`
# and then `points[-limit:]`, so 0 asked for none and got all forty (with the
# ledger recording 0), -4 silently dropped the four OLDEST points, and -20 on a
# twelve-point series returned an empty series — successfully, with a calc_id
# the agent could then cite.
_LAST_N = {"type": "integer", "default": 12, "minimum": 1, "maximum": 40,
           "description": "how many most-recent periods (cap 40)"}


# ── company / snapshot ──────────────────────────────────────────────────────────

async def _resolve_company(db: AsyncSession, ticker: str) -> dict:
    try:
        c = await company_service.get_by_ticker(db, ticker.upper())
    except company_service.CompanyNotFound:
        return {"error": "company_not_found", "ticker": ticker.upper()}
    return {
        "id": c.id, "ticker": c.ticker, "name": c.name, "cik": c.cik,
        "exchange": c.exchange, "sector": c.sector, "industry": c.industry,
        "is_investigable": c.is_investigable,
    }


async def _get_issuer_snapshot(db: AsyncSession, ticker: str) -> dict:
    company = await _resolve_company(db, ticker)
    if company.get("error"):
        return company
    metrics = await cs.list_available_metrics(db, ticker.upper())
    return {"company": company, "available_metrics": metrics["metrics"]}


async def _list_available_data(db: AsyncSession, ticker: str) -> dict:
    return await cs.list_available_metrics(db, ticker.upper())


# ── V9-A2/A3: a flow over any window, and one instant's balance sheet ─────────

async def _get_flow(db: AsyncSession, ticker: str, metric: str,
                    months: int | None = None,
                    start: str | None = None, end: str | None = None) -> dict:
    return await fundamentals_service.get_flow(
        db, ticker, metric, months=months, start=start, end=end,
        invoked_by=current_session_id())


async def _get_balance_sheet(db: AsyncSession, ticker: str, at: str | None = None) -> dict:
    return await fundamentals_service.get_balance_sheet(
        db, ticker, at=at, invoked_by=current_session_id())


async def _calculate(db: AsyncSession, op: str, a: str, b: str) -> dict:
    return await typed_calculator.calculate(db, op, a, b, invoked_by=current_session_id())


# ── portfolio (the entry point for "my portfolio" questions) ──────────────────────

async def _get_portfolio_snapshot(db: AsyncSession) -> dict:
    return {"portfolios": await portfolio_service.snapshot_all(db)}


# ── financial data / calculations ───────────────────────────────────────────────

def _spec(ticker: str, metric: str, period_type: str, last_n: int | None) -> cs.SeriesSpec:
    # int(last_n), because the schema cannot say this. Draft 2020-12 counts 12.0
    # as an integer — deliberately, and jsonschema implements it — so no keyword
    # rejects the float a model writes when it means twelve. It would reach
    # `points[-12.0:]` and raise TypeError, surfacing as tool_error. The single
    # place last_n enters the series layer, and the same coercion
    # filing_retrieval_service already does for k.
    return cs.SeriesSpec(ticker=ticker.upper(), metric=metric,
                         period_type=period_type,
                         last_n=None if last_n is None else int(last_n))


async def _get_fact_series(db: AsyncSession, ticker: str, metric: str,
                           period_type: str = "quarterly", last_n: int = 12) -> dict:
    # Ledgered, not just returned. A quarterly series contains a DERIVED Q4
    # (annual minus the three filed quarters) whose value equals no row anywhere:
    # the fact ids beside it point at four different numbers. Without a calc id
    # of its own, quoting Q4 correctly AND citing it correctly is unverifiable by
    # construction — four such refusals in one live brief.
    try:
        out = await cs.series(db, _spec(ticker, metric, period_type, last_n),
                              invoked_by=current_session_id())
    except cs.UnknownMetric as e:
        return {"error": "metric_unavailable", "detail": str(e)}
    return {"ticker": ticker.upper(), "metric": metric, "period_type": period_type, **out}


async def _compute_change(db: AsyncSession, ticker: str, metric: str, mode: str,
                          period_type: str = "quarterly", last_n: int = 12) -> dict:
    try:
        return await cs.change(db, _spec(ticker, metric, period_type, last_n), mode, invoked_by=current_session_id())
    except cs.UnknownMetric as e:
        return {"error": "metric_unavailable", "detail": str(e)}


async def _compute_ratio(db: AsyncSession, ticker: str, numerator: str, denominator: str,
                         period_type: str = "quarterly", last_n: int = 12) -> dict:
    try:
        return await cs.combine(
            db, _spec(ticker, numerator, period_type, last_n),
            _spec(ticker, denominator, period_type, last_n), "divide",
            invoked_by=current_session_id(),
        )
    except cs.UnknownMetric as e:
        return {"error": "metric_unavailable", "detail": str(e)}


async def _compute_stat(db: AsyncSession, ticker: str, metric: str, op: str,
                        period_type: str = "quarterly", last_n: int = 12) -> dict:
    try:
        return await cs.stat(db, _spec(ticker, metric, period_type, last_n), op, invoked_by=current_session_id())
    except cs.UnknownMetric as e:
        return {"error": "metric_unavailable", "detail": str(e)}


async def _get_market_stats(db: AsyncSession, ticker: str, window: str = "1y", benchmark: str | None = "SPY") -> dict:
    days = {"1m": 30, "3m": 91, "6m": 182, "1y": 365}.get(window, 365)
    end = date.today()
    start = end - timedelta(days=days)
    return await cs.window_return(db, ticker.upper(), start, end, benchmark=benchmark,
                                  invoked_by=current_session_id())


async def _compute_combine(db: AsyncSession, ticker: str, metric_a: str, metric_b: str, op: str,
                           period_type: str = "quarterly", last_n: int = 12) -> dict:
    """add / sub / divide over two metric series. compute_ratio is the divide case
    under its domain name; the other two had been unreachable from every agent
    face since M3, which is why free cash flow — operating_cash_flow minus capex,
    the example in the module notes — could not be computed as a ledgered calc."""
    if op not in ("add", "sub", "divide"):
        return {"error": "unsupported_op", "op": op, "supported": ["add", "sub", "divide"]}
    try:
        return await cs.combine(
            db, _spec(ticker, metric_a, period_type, last_n),
            _spec(ticker, metric_b, period_type, last_n), op,
            invoked_by=current_session_id(),
        )
    except cs.UnknownMetric as e:
        return {"error": "metric_unavailable", "detail": str(e)}


async def _get_task_status(db: AsyncSession, job_id: str) -> dict:
    try:
        row = await job_status_service.status_of(db, job_id)
    except job_status_service.NoOwner:
        return {"error": "sign_in_required", "detail": "task status is per-account"}
    if row is None:
        return {"error": "unknown_job", "job_id": job_id}
    return row


async def _get_portfolio_positions(db: AsyncSession, portfolio_id: str) -> dict:
    out = await portfolio_service.positions_with_weights(db, portfolio_id)
    if out is None:
        return {"error": "unknown_portfolio", "portfolio_id": portfolio_id}
    return out


async def _read_issuer_brief(db: AsyncSession, ticker: str) -> dict:
    company = await _resolve_company(db, ticker)
    if company.get("error"):
        return company
    brief = await brief_service.latest_visible(db, company["id"])
    if brief is None:
        return {"error": "no_brief", "ticker": ticker.upper(),
                "hint": "start_issuer_research produces one"}
    return {"ticker": ticker.upper(), **brief}


# ── filing retrieval ────────────────────────────────────────────────────────────

async def _search_filing_passages(db: AsyncSession, ticker: str, query: str, k: int = 5,
                                  form_type: str | None = None, item_code: str | None = None) -> dict:
    company = await _resolve_company(db, ticker)
    if company.get("error"):
        return company
    try:
        # int(k) here as well as in the retrieval service: the coercion belongs
        # where the model's value enters the tool layer, so the rule reads the
        # same for every window size (see _spec on why the schema cannot say it).
        passages = await frs.search_passages(db, company["id"], query, k=int(k),
                                             form_type=form_type, item_code=item_code)
    except frs.NotIndexed:
        return {"error": "not_indexed", "ticker": ticker.upper(),
                "hint": "run a readiness pass for this company first"}
    return {
        "ticker": ticker.upper(), "query": query,
        "passages": [
            {"chunk_id": p.chunk_id, "text": p.text, "score": round(p.score, 4),
             "item": p.item_code, "section_title": p.section_title,
             "citation": p.citation()}
            for p in passages
        ],
    }


async def _get_filing_section(db: AsyncSession, ticker: str, item_code: str, form_type: str | None = None) -> dict:
    company = await _resolve_company(db, ticker)
    if company.get("error"):
        return company
    section = await frs.get_section(db, company["id"], item_code, form_type=form_type)
    if section is None:
        return {"error": "section_not_found", "ticker": ticker.upper(), "item_code": item_code}
    return {
        "ticker": ticker.upper(), "item_code": section.item_code, "title": section.title,
        "text": section.text, "citation": {
            "type": "chunk", "accession": section.accession_number,
            "form_type": section.form_type, "item": section.item_code,
            "source_url": section.source_url,
        },
    }


# ── risk alerts (portfolio context) ─────────────────────────────────────────────

async def _list_alerts(db: AsyncSession, ticker: str) -> dict:
    tk = ticker.upper()
    rows = (await db.execute(
        select(RiskAlert).where(RiskAlert.entity_id == tk).order_by(RiskAlert.created_at.desc()).limit(20)
    )).scalars().all()
    return {"ticker": tk, "alerts": [
        {"id": a.id, "type": a.alert_type, "severity": a.severity,
         "message": a.message, "utilization": float(a.utilization) if a.utilization is not None else None}
        for a in rows
    ]}


# ── reflection ──────────────────────────────────────────────────────────────────

async def _think(db: AsyncSession, thought: str) -> dict:
    """Low-friction pause: no side effect, no budget, only a trace line.

    session_id comes from the tool context, never from the model — the trace row
    for the think step is written by the registry wrapper itself.
    """
    return {"noted": True, "thought": thought[:400]}


# ── registration ────────────────────────────────────────────────────────────────

_TICKER = {"type": "string", "description": "Issuer ticker, e.g. NVDA"}

# The forms a filing can actually HAVE, which is not the two anyone would list.
# edgartools' get_filings defaults amendments=True and expands a requested form
# to {form, form + '/A'}; ingest_filings_metadata records is_amendment and never
# skips on it. So '10-K/A' reaches filing_chunks, a passage's own citation names
# it — and with the old enum the model was refused for passing back the form the
# previous call had just handed it. null is the "any form" the fn already means
# by None.
_FORM_TYPE = {
    "type": ["string", "null"],
    "enum": ["10-K", "10-Q", "10-K/A", "10-Q/A", None],
    "description": "narrow to one form; omit for any",
}


def build_read_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(Tool(
        name="get_issuer_snapshot",
        description="Company identity plus the list of financial metrics available for this issuer.",
        json_schema={"type": "object", "properties": {"ticker": _TICKER}, "required": ["ticker"], "additionalProperties": False},
        fn=_get_issuer_snapshot, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_flow",
        description=(
            "A flow metric (revenue, net income, interest expense, operating cash flow, "
            "capex …) over a window YOU choose. Give `months` for the most recent window "
            "of that length, or an explicit start/end. Issuers file flows over whatever "
            "periods they file — quarters, half-years, year-to-date, full years — and this "
            "derives your window from them by adding and subtracting the ones they did "
            "report, returning the exact interval covered and which facts went in with "
            "which sign. It never returns a shorter period than you asked for: a window "
            "that cannot be derived is refused."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "metric": {"type": "string", "description": "a normalised metric name; "
                                                        "list_available_data has them"},
            "months": {"type": ["integer", "null"], "minimum": 1, "maximum": 120,
                       "description": "window length; defaults to 12"},
            "start": {"type": ["string", "null"], "description": "YYYY-MM-DD, first day covered"},
            "end": {"type": ["string", "null"], "description": "YYYY-MM-DD, last day covered"},
        }, "required": ["ticker", "metric"], "additionalProperties": False},
        fn=_get_flow, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_balance_sheet",
        description=(
            "Every balance this issuer reported at ONE date — debt components, cash, "
            "working capital, equity. Balances from different dates are different "
            "company-moments and must not be combined, so lines the issuer did not report "
            "at this date are listed separately with the date they were last reported, "
            "never substituted in. `at` defaults to the most recent such date."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "at": {"type": ["string", "null"], "description": "YYYY-MM-DD; defaults to latest"},
        }, "required": ["ticker"], "additionalProperties": False},
        fn=_get_balance_sheet, tool_class=READ,
    ))
    reg.register(Tool(
        name="calculate",
        description=(
            "Add, subtract, multiply or divide two quantities you already have, by their "
            "ids (fact_… or calc_…). Compose anything: EBIT, leverage, coverage, margins, "
            "turnover — none of these needs to be a built-in. The result gets its own "
            "calc_id and is citable. Combinations that would silently double-count are "
            "refused with the reason: two balances from different dates, two flows over "
            "overlapping periods added together, or a total added to something it already "
            "contains. A balance divided by a flow is fine — that is what leverage is."
        ),
        json_schema={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]},
            "a": {"type": "string", "description": "fact_… or calc_… id"},
            "b": {"type": "string", "description": "fact_… or calc_… id"},
        }, "required": ["op", "a", "b"], "additionalProperties": False},
        fn=_calculate, tool_class=READ,
    ))
    reg.register(Tool(
        name="list_available_data",
        description="Which financial metrics exist for this issuer and how many periods each has.",
        json_schema={"type": "object", "properties": {"ticker": _TICKER}, "required": ["ticker"], "additionalProperties": False},
        fn=_list_available_data, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_portfolio_snapshot",
        description="The portfolio(s) this desk manages: latest exposure metrics, largest sector "
                    "and issuer weights, and active risk alerts. Takes no arguments — this is how "
                    "you discover holdings for a portfolio-level question. Each portfolio's numbers "
                    "carry the run_id that produced them; cite run_id (and alert ids) for portfolio claims.",
        json_schema={"type": "object", "properties": {}, "additionalProperties": False},
        fn=_get_portfolio_snapshot, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_fact_series",
        description="A period-aligned series of one financial metric (values carry the fact ids they came from).",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "metric": {"type": "string", "description": "normalized metric, e.g. revenue, net_income, cost_of_revenue"},
            "period_type": {"type": "string", "enum": _PERIOD_TYPES, "default": "quarterly"},
            "last_n": _LAST_N,
        }, "required": ["ticker", "metric"], "additionalProperties": False},
        fn=_get_fact_series, tool_class=READ,
    ))
    reg.register(Tool(
        name="compute_change",
        description="Growth of a metric: yoy / qoq / pct / abs. Writes a ledger entry; returns its calc_id.",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER, "metric": {"type": "string"},
            "mode": {"type": "string", "enum": ["yoy", "qoq", "pct", "abs"]},
            "period_type": {"type": "string", "enum": _PERIOD_TYPES, "default": "quarterly"},
            "last_n": _LAST_N,
        }, "required": ["ticker", "metric", "mode"], "additionalProperties": False},
        fn=_compute_change, tool_class=READ,
    ))
    reg.register(Tool(
        name="compute_ratio",
        description="Ratio of two metrics (e.g. gross_profit / revenue = margin). Writes a ledger entry.",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER, "numerator": {"type": "string"}, "denominator": {"type": "string"},
            "period_type": {"type": "string", "enum": _PERIOD_TYPES, "default": "quarterly"},
            "last_n": _LAST_N,
        }, "required": ["ticker", "numerator", "denominator"], "additionalProperties": False},
        fn=_compute_ratio, tool_class=READ,
    ))
    reg.register(Tool(
        name="compute_combine",
        description="Combine two metric series: add / sub / divide "
                    "(e.g. operating_cash_flow sub capex = free cash flow). Writes a ledger entry.",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER, "metric_a": {"type": "string"}, "metric_b": {"type": "string"},
            "op": {"type": "string", "enum": ["add", "sub", "divide"]},
            "period_type": {"type": "string", "enum": _PERIOD_TYPES, "default": "quarterly"},
            "last_n": _LAST_N,
        }, "required": ["ticker", "metric_a", "metric_b", "op"], "additionalProperties": False},
        fn=_compute_combine, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_task_status",
        description="Whether delegated work has finished. Accepts the task_/run_/rrun_ id "
                    "that ensure_company_ready, start_exposure_run or start_issuer_research returned.",
        json_schema={"type": "object", "properties": {
            "job_id": {"type": "string", "description": "task_… / run_… / rrun_…"},
        }, "required": ["job_id"], "additionalProperties": False},
        fn=_get_task_status, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_portfolio_positions",
        description="Every holding in a portfolio: pos_id, ticker, quantity, sector, market value "
                    "and weight. Cite the pos_id for a share count. Capped at 50 rows — when "
                    "truncated is set, total_holdings is the real number and say so. "
                    "get_portfolio_snapshot only carries the largest few.",
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
        }, "required": ["portfolio_id"], "additionalProperties": False},
        fn=_get_portfolio_positions, tool_class=READ,
    ))
    reg.register(Tool(
        name="read_issuer_brief",
        description="The latest Issuer Risk Brief for a company, with the evidence ids behind "
                    "each block. Cite those ids, not the brief.",
        json_schema={"type": "object", "properties": {"ticker": _TICKER}, "required": ["ticker"], "additionalProperties": False},
        fn=_read_issuer_brief, tool_class=READ,
    ))
    reg.register(Tool(
        name="compute_stat",
        description="A scalar statistic over a metric series: cagr / avg / min / max / std / sum / latest.",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER, "metric": {"type": "string"},
            "op": {"type": "string", "enum": ["cagr", "avg", "min", "max", "std", "sum", "latest"]},
            "period_type": {"type": "string", "enum": _PERIOD_TYPES, "default": "quarterly"},
            "last_n": _LAST_N,
        }, "required": ["ticker", "metric", "op"], "additionalProperties": False},
        fn=_compute_stat, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_market_stats",
        description="Price return over a window (1m/3m/6m/1y), optionally relative to a benchmark (default SPY).",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "window": {"type": "string", "enum": ["1m", "3m", "6m", "1y"], "default": "1y"},
            # str | None in the signature: None means "no benchmark comparison",
            # which calc_service branches on. Omitting and sending null are the
            # same intent, and a model with non-strict function calling sends both.
            "benchmark": {"type": ["string", "null"], "default": "SPY"},
        }, "required": ["ticker"], "additionalProperties": False},
        fn=_get_market_stats, tool_class=READ,
    ))
    reg.register(Tool(
        name="search_filing_passages",
        description="Semantic search across an issuer's indexed 10-K/10-Q; returns passages with citation anchors.",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER, "query": {"type": "string"},
            "k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            "form_type": _FORM_TYPE,
            "item_code": {"type": ["string", "null"], "minLength": 1,
                          "description": "narrow to an Item, e.g. 'Item 1A'"},
        }, "required": ["ticker", "query"], "additionalProperties": False},
        fn=_search_filing_passages, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_filing_section",
        description="Read a whole SEC Item verbatim from the most recent filing (e.g. Item 1A Risk Factors).",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER, "item_code": {"type": "string", "minLength": 1},
            "form_type": _FORM_TYPE,
        }, "required": ["ticker", "item_code"], "additionalProperties": False},
        fn=_get_filing_section, tool_class=READ,
    ))
    reg.register(Tool(
        name="list_alerts",
        description="Portfolio risk alerts naming this issuer (concentration, etc.).",
        json_schema={"type": "object", "properties": {"ticker": _TICKER}, "required": ["ticker"], "additionalProperties": False},
        fn=_list_alerts, tool_class=READ,
    ))
    reg.register(Tool(
        name="think",
        description="Pause to write an analytical note before anchoring a conclusion. No side effect, no budget.",
        json_schema={"type": "object", "properties": {
            "thought": {"type": "string"},
        }, "required": ["thought"], "additionalProperties": False},
        fn=_think, tool_class=REFLECTION,
    ))
    return reg
