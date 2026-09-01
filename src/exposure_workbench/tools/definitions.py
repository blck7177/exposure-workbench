"""Tool definitions (M10) — read + reflection tools.

Every fn is a THIN wrapper over a service: it validates/normalizes args and
returns a JSON-able dict. What of that result goes on the table is DECLARED at
registration (`evidence=`): the ids it returns, and for a run the child tables
it read (services/table.py). No business logic lives here (that stays in
services/analytics), and no tool touches the network directly.

Delegation and gate tools (ensure_company_ready, start_*, respond, submit_brief)
are registered in P6/P7 where their targets exist.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company, RiskAlert
from exposure_workbench.services import brief_service
from exposure_workbench.services import (
    formula_service, fundamentals_service, typed_calculator,
)
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import company_service
from exposure_workbench.services import filing_retrieval_service as frs
from exposure_workbench.services import job_status_service
from exposure_workbench.services import portfolio_service
from exposure_workbench.services import drawdown_service
from exposure_workbench.services import integration_service
from exposure_workbench.services import reconcile_service
from exposure_workbench.services import run_reads_service
from exposure_workbench.services import series_service
from exposure_workbench.services import trace_service
from exposure_workbench.services import quantities as qn
from exposure_workbench.tools.registry import READ, REFLECTION, Evidence, Tool, ToolRegistry, current_session_id

_PERIOD_TYPES = ["quarterly", "annual", "instant"]



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


# ── V9-A2/A3: a flow over any window, and one instant's balance sheet ─────────

async def _describe_issuer(db: AsyncSession, ticker: str) -> dict:
    """Identity, what the filings hold, and which named measures that supports.

    V10-S2: the one locating tool. It replaces get_issuer_snapshot (identity +
    metrics), list_available_data (metrics alone — the same list) and
    list_formulas (the registry with no ticker), because "what can I ask about
    this company" is one question and three tools made the model ask it three
    times. The formula list is the same sixteen for every issuer; what differs
    per issuer is which of them its filings can feed, and that is stated here
    rather than discovered by a refused evaluate_formula.
    """
    from exposure_workbench.analytics import containment as _ct
    from exposure_workbench.analytics import formulas as _fm
    from exposure_workbench.analytics import semantics as _sem
    from exposure_workbench.services import absence_service as _ab
    from exposure_workbench.services import period_semantics as _ps

    company = await _resolve_company(db, ticker)
    if company.get("error"):
        return company
    metrics = await cs.list_available_metrics(db, ticker.upper())
    have = {m["metric"] for m in metrics["metrics"]}

    # V12-K1. What each metric MEANS, at the moment of choosing one. Every field
    # below already existed — in the containment edges, in the registry's named
    # alternatives, in concept_mapping's comments — and none of it reached the
    # model, which saw a name, a count and a date and chose between strings.
    for row in metrics["metrics"]:
        name = row["metric"]
        # The RULE, not the graph. Shipping `contains` and `contained_by` beside
        # this said the same thing three ways: which one is the wider line is
        # what `for_a_total_call` answers, and the only thing a caller has to
        # act on is that these two may not be summed. A rule the model has to
        # compose out of two facts is the class DABstep measured agents missing,
        # so the conclusion travels and the graph stays in containment.py.
        nested = sorted({c for c in have if _ct.contains(name, c)} |
                        {p for p in have if _ct.contains(p, name)})
        if nested:
            row["do_not_add_to"] = nested
        superseded = [a for a in _ab.superseded_by(name) if a in have]
        if superseded:
            row["superseded_by"] = superseded
        sem = _sem.for_metric(name)
        if sem is None:
            continue
        confusable = [o for o in sem.do_not_combine_with if o in have]
        if confusable:
            row["do_not_combine_with"] = confusable
        if sem.for_a_total_call:
            row["for_a_total_call"] = sem.for_a_total_call
        # Every note in the table warns about a RELATIONSHIP — this line is
        # inside that one, this tag was superseded by that one, this is a
        # component and not the total. Shipped where the other side of the
        # relationship is absent, it is a caveat about a choice this issuer does
        # not offer, and LinkedIn measured irrelevant domain knowledge lowering
        # answer quality rather than raising it. So the note travels with the
        # relationship that makes it true.
        if sem.note and any(k in row for k in
                            ("contains", "contained_by", "superseded_by",
                             "do_not_combine_with", "for_a_total_call")):
            row["note"] = sem.note

    def leaves(name: str, seen: set[str]) -> set[str]:
        f = _fm.FORMULAS.get(name)
        if f is None:
            return {name}
        out: set[str] = set()
        for inp in f.inputs:
            if inp in seen:
                continue
            out |= leaves(inp, seen | {inp})
        return out

    formulas = []
    for name, f in sorted(_fm.FORMULAS.items()):
        needed = leaves(name, {name})
        missing = sorted(needed - have)
        # No `authority` and no `note` here. Both are registry prose — the same
        # bytes for every issuer, and `authority` is the SAME OBJECT sixteen
        # times over in one catalogue. They travel where they are load-bearing:
        # beside the number, in evaluate_formula, which has always shipped them.
        # This is the V11-T lesson applied to the other listing tool; measured,
        # the two cost 3.8kB of an 18.7kB payload against a 12kB cap.
        formulas.append({"name": name, "definition": f.expression, "basis": f.basis,
                         "family": f.family, "unit_class": f.unit_class,
                         "computable": not missing,
                         **({"missing_inputs": missing} if missing else {})})

    out = {"company": company, "available_metrics": metrics["metrics"],
           "formulas": formulas}
    periods = await _ps.describe_periods(db, ticker.upper())
    if periods:
        out["period_semantics"] = periods
    return out


async def _get_balance_series(db: AsyncSession, ticker: str, metric: str, last_n: int = 12) -> dict:
    return await fundamentals_service.get_balance_series(
        db, ticker, metric, last_n=int(last_n), invoked_by=current_session_id())


async def _series_stat(db: AsyncSession, series_id: str, op: str) -> dict:
    return await series_service.series_stat(db, series_id, op, invoked_by=current_session_id())


async def _get_flow(db: AsyncSession, ticker: str, metric: str,
                    months: int | None = None,
                    start: str | None = None, end: str | None = None,
                    last_n: int | None = None) -> dict:
    # int(), because draft 2020-12 counts 12.0
    # as an integer, so the schema cannot refuse the float a model writes when
    # it means twelve, and it would reach a slice.
    return await fundamentals_service.get_flow(
        db, ticker, metric, months=months, start=start, end=end,
        last_n=None if last_n is None else int(last_n),
        invoked_by=current_session_id())


async def _get_balance_sheet(db: AsyncSession, ticker: str, at: str | None = None) -> dict:
    return await fundamentals_service.get_balance_sheet(
        db, ticker, at=at, invoked_by=current_session_id())


async def _calculate(db: AsyncSession, op: str, a: str, b: str) -> dict:
    return await typed_calculator.calculate(db, op, a, b, invoked_by=current_session_id())


async def _evaluate_formula(db: AsyncSession, ticker: str, name: str,
                            months: int | None = None, at: str | None = None) -> dict:
    return await formula_service.evaluate_formula(
        db, ticker, name, months=months or 12, at=at, invoked_by=current_session_id())


async def _get_fundamental_panel(db: AsyncSession, ticker: str,
                                 months: int | None = None, at: str | None = None) -> dict:
    return await formula_service.build_panel(
        db, ticker, months=months or 12, at=at, invoked_by=current_session_id())


# ── portfolio (the entry point for "my portfolio" questions) ──────────────────────

async def _get_portfolio_snapshot(db: AsyncSession) -> dict:
    return {"portfolios": await portfolio_service.snapshot_all(db)}


# ── financial data / calculations ───────────────────────────────────────────────

async def _get_market_stats(db: AsyncSession, ticker: str, window: str = "1y", benchmark: str | None = "SPY") -> dict:
    # The reporting date is a server fact. Reading the clock here made the same
    # ticker's 1m return a different number on consecutive days with nothing in
    # the ledger row to say the window had moved — V5 fixed that for the recipe
    # and this tool kept the clock. `latest_session_date` is the last completed
    # session, which is also what start_exposure_run reports on.
    from exposure_workbench.services import market_data_service
    days = {"1m": 30, "3m": 91, "6m": 182, "1y": 365}.get(window, 365)
    end = await market_data_service.latest_session_date(db)
    if end is None:
        return {"error": "no_price_data", "detail": "no market prices are loaded yet"}
    start = end - timedelta(days=days)
    return await cs.window_return(db, ticker.upper(), start, end, benchmark=benchmark,
                                  invoked_by=current_session_id())


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


# ── the run's own findings (V8-A) ───────────────────────────────────────────────
# Thin, like every fn here. The reason these are four tools rather than one is
# that they answer four different questions and a single "get_run" would make
# every one of them cost the whole payload — which for a ten-position book is
# fine and stops being fine at the first real one.

async def _get_attribution(db: AsyncSession, run_id: str) -> dict:
    return await run_reads_service.get_attribution(db, run_id)


async def _get_risk_state(db: AsyncSession, run_id: str) -> dict:
    return await run_reads_service.get_risk_state(db, run_id)


async def _list_run_alerts(db: AsyncSession, run_id: str) -> dict:
    return await run_reads_service.list_run_alerts(db, run_id)


async def _list_risk_limits(db: AsyncSession, portfolio_id: str) -> dict:
    return await run_reads_service.list_risk_limits(db, portfolio_id)


async def _get_run_freshness(db: AsyncSession, portfolio_id: str) -> dict:
    return await run_reads_service.get_run_freshness(db, portfolio_id)


async def _reconcile_move(db: AsyncSession, run_id: str) -> dict:
    return await reconcile_service.reconcile_move(db, run_id)


async def _get_portfolio_analysis(db: AsyncSession, run_id: str) -> dict:
    return await integration_service.get_portfolio_analysis(db, run_id)


async def _get_drawdown_episodes(db: AsyncSession, portfolio_id: str, span: str = "1y") -> dict:
    return await drawdown_service.get_drawdown_episodes(db, portfolio_id, span)


async def _explain_episode(db: AsyncSession, portfolio_id: str, peak: str, trough: str) -> dict:
    return await drawdown_service.explain_episode(db, portfolio_id, peak, trough)



# ── the book's own manifest (V15-S2b) ───────────────────────────────────────────

# What this face can and cannot do, said where the model reads it. R4 measured
# the failure: with no capability statement, the model called "no operator for
# this" "not enough data" and, asked for a web search, silently searched
# filings instead.
_FACE_CAPABILITIES = {
    "can": [
        "read this book's runs by name (describe_run → read_quantities) and every issuer's "
        "filed figures, filing passages and named measures",
        "compute with calculate / series_stat / evaluate_formula, each minting a citable id",
        "start background work: a readiness pass, an exposure run, an issuer research run",
    ],
    "cannot": [
        "search the web from this face — a research run (start_issuer_research) can, and "
        "its brief is read with read_issuer_brief",
        "produce a figure no tool returned: a quantity not on the table cannot be written",
    ],
}

# The question each family of a run's quantities answers. The groups are how
# the manifest is read; the names inside them are the table's own.
_RUN_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("book", "size, day P&L and net/gross exposure of the whole book",
     ("exposure_metrics.portfolio_market_value", "exposure_metrics.daily_pnl", "exposure_metrics.daily_return",
      "exposure_metrics.gross_exposure", "exposure_metrics.net_exposure",
      "exposure_metrics.gross_exposure_pct", "exposure_metrics.net_exposure_pct")),
    ("concentration", "which issuers and sectors the book is concentrated in",
     ("issuer_exposures.*.weight", "sector_exposures.*.weight", "issuer_exposures.*.market_value")),
    ("mandate", "how each limit check stands against its warning and breach tiers, and the room left",
     ("limit_checks.*.current_value", "limit_checks.*.warning_level", "limit_checks.*.breach_level",
      "portfolio.integration.room_to_warning.*", "portfolio.integration.room_to_breach.*",
      "risk_alerts.*.current_value", "risk_alerts.*.limit_value", "risk_alerts.*.utilization")),
    ("stress", "what each scenario would cost, ranked by get_portfolio_analysis",
     ("stress_results.*.loss_pct", "stress_results.*.loss_usd",
      "exposure_metrics.stress_loss_market", "exposure_metrics.stress_loss_rates",
      "exposure_metrics.stress_loss_credit", "exposure_metrics.stress_loss_tech")),
    ("factor_exposure", "which way the book moves with each risk — net betas with their legs",
     ("portfolio.integration.net_beta.*", "portfolio.integration.gross_beta.*",
      "factor_attributions.*.beta", "factor_attributions.sum_of_contributions")),
    ("attribution", "what moved the book on the run's date, by position and by factor",
     ("issuer_exposures.*.contribution", "issuer_exposures.*.daily_return",
      "factor_attributions.*.contribution", "factor_attributions.*.factor_return",
      "exposure_metrics.attribution_portfolio_return", "exposure_metrics.alpha", "exposure_metrics.residual")),
    ("risk", "volatility, tail measures and drawdown as the run measured them",
     ("exposure_metrics.rolling_vol_30d", "exposure_metrics.rolling_vol_60d", "exposure_metrics.var_95_1d",
      "exposure_metrics.expected_shortfall_95", "exposure_metrics.max_drawdown",
      "exposure_metrics.model_r_squared", "exposure_metrics.observations", "exposure_metrics.max_vif")),
    ("counts", "how many positions, factors, scenarios, alerts and checks the run holds",
     ("count.*",)),
)


def _matches(pattern: str, name: str) -> bool:
    if "*" not in pattern:
        return name == pattern
    head, _, tail = pattern.partition("*")
    return name.startswith(head) and name.endswith(tail) and len(name) > len(head) + len(tail)


def _factored(names: list[str]) -> dict:
    """Names, stated as patterns over their row labels where that is shorter.

    A run's mandate group is 27 checks × 3 columns + 54 distances: 144 names
    that are five patterns over 27 labels. The model composes a name from a
    pattern and a label exactly as it would copy one, and the payload stays
    readable — measured: the flat listing was 18k characters, over the cap.
    Names that do not share a shape with three others are listed whole.
    """
    by_shape: dict[tuple[str, str], list[str]] = {}
    plain: list[str] = []
    for n in names:
        parts = n.split(".")
        if len(parts) == 3:
            by_shape.setdefault((parts[0], parts[2]), []).append(parts[1])
        elif len(parts) == 4 and parts[0] == "portfolio":
            # portfolio.integration.<key>.<label>
            by_shape.setdefault((".".join(parts[:3]), ""), []).append(parts[3])
        else:
            plain.append(n)
    # Patterns that range over the same labels share one label list: the
    # mandate group's five patterns over 27 checks are one list of 27, not five.
    by_labels: dict[tuple[str, ...], list[str]] = {}
    for (head, tail), labels in by_shape.items():
        if len(labels) <= 3:
            plain.extend(f"{head}.{lb}.{tail}" if tail else f"{head}.{lb}" for lb in labels)
            continue
        by_labels.setdefault(tuple(sorted(labels)), []).append(
            f"{head}.<label>.{tail}" if tail else f"{head}.<label>")
    out: dict = {}
    if plain:
        out["names"] = sorted(plain)
    if by_labels:
        out["patterns"] = [{"patterns": pats, "labels": list(labels)} for labels, pats in by_labels.items()]
    return out


async def _describe_run(db: AsyncSession, run_id: str) -> dict:
    """Everything one run holds, named the way the exit takes it, grouped by the
    question each group answers. The values arrive on the table beside this."""
    from exposure_workbench.analytics import resources as _rs
    run = await run_reads_service._run_or_error(db, run_id)
    if isinstance(run, dict):
        return run
    if run.status != "completed":
        return {"error": "run_not_completed", "run_id": run_id, "status": run.status}
    resolved = await qn.of_ref(db, run_id)
    names = [q.label for q in resolved.quantities if q.not_alone is None]
    withheld = sorted({q.label for q in resolved.quantities if q.not_alone is not None})
    # The derived quantities — net betas, room to each tier — live on the row
    # get_portfolio_analysis mints; minting it here puts them on the table with
    # the rest, which is what "the whole book on one page" means.
    analysis = await integration_service.get_portfolio_analysis(db, run_id)
    analysis_id = analysis.get("calc_id") if isinstance(analysis, dict) else None
    derived = [q.label for q in (await qn.of_ref(db, analysis_id)).quantities] if analysis_id else []
    everything = names + derived
    groups, grouped = [], set()
    for key, question, patterns in _RUN_GROUPS:
        members = [n for n in everything if n not in grouped and any(_matches(p, n) for p in patterns)]
        if members:
            grouped.update(members)
            groups.append({"group": key, "answers": question, **_factored(members)})
    rest = [n for n in everything if n not in grouped]
    return {
        "run_id": run_id, "portfolio_id": run.portfolio_id, "as_of": run.as_of_date.isoformat(),
        "how_to_read": ("every name here is a figure on this run's table, with its value beside it "
                        "under `table`. Write it in a slot {ref, name}: ref is the run_id, except "
                        "portfolio.integration.* names, whose ref is analysis_calc_id. A pattern "
                        "with <label> is one name per label"),
        "analysis_calc_id": analysis_id,
        "groups": groups,
        **({"other": _factored(rest)} if rest else {}),
        "units": {r.table: {c.name: c.unit for c in r.columns} for r in _rs.RUN_CHILDREN},
        "not_available": {
            "stress_unevaluated": analysis.get("stress_unevaluated") if isinstance(analysis, dict) else None,
            "headroom_not_recorded": analysis.get("headroom_not_recorded") if isinstance(analysis, dict) else None,
            "withheld_collinear": _factored(withheld) if withheld else None,
        },
        "collinear_note": ("these factors are collinear: no single beta is on the table; "
                           "factor_attributions.sum_of_contributions and the net betas are"
                           if withheld else None),
        "capabilities": _FACE_CAPABILITIES,
    }


async def _read_quantities(db: AsyncSession, run_id: str, names: list[str]) -> dict:
    """The exact quantities a question needs, by name, in one call."""
    run = await run_reads_service._run_or_error(db, run_id)
    if isinstance(run, dict):
        return run
    resolved = await qn.of_ref(db, run_id)
    held = {q.label: q for q in resolved.quantities if q.not_alone is None}
    wanted = [str(n) for n in names]
    found = [n for n in wanted if n in held]
    unknown = [n for n in wanted if n not in held]
    return {"run_id": run_id, "as_of": run.as_of_date.isoformat(), "names": found,
            "units": {n: held[n].unit_class for n in found},
            **({"unknown": unknown, "detail": "not names this run holds; describe_run lists them"}
               if unknown else {})}

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
        name="get_flow",
        display="Reading {ticker}'s {metric} over the periods it reports",
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
                                                        "describe_issuer has them"},
            "months": {"type": ["integer", "null"], "minimum": 1, "maximum": 120,
                       "description": "window length; defaults to 12"},
            "start": {"type": ["string", "null"], "description": "YYYY-MM-DD, first day covered"},
            "end": {"type": ["string", "null"], "description": "YYYY-MM-DD, last day covered"},
            # A floor as well as a ceiling. The predecessor (get_fact_series)
            # learned that 0 asked for none and got all forty, and -20 on a
            # twelve-point series returned an empty series with a citable id.
            "last_n": {"type": ["integer", "null"], "minimum": 1, "maximum": 40,
                       "description": "more than 1 returns a SERIES: that many consecutive "
                                      "windows of `months` each, on the issuer's own "
                                      "reporting grid, oldest first, as one citable calc_id. "
                                      "Use months=3 for quarters, 12 for fiscal years."},
        }, "required": ["ticker", "metric"], "additionalProperties": False},
        fn=_get_flow, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="get_balance_series",
        display="Reading {ticker}'s {metric} at each reported date",
        description=(
            "One balance-sheet line (cash, total debt, receivables, equity …) at each date "
            "the issuer reported it, newest last, as one citable series. Nothing is derived "
            "or carried across dates — a balance is a reading at an instant. get_balance_sheet "
            "is every line at ONE date; this is ONE line over time."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "metric": {"type": "string", "description": "a normalised balance metric; describe_issuer has them"},
            "last_n": {"type": ["integer", "null"], "minimum": 1, "maximum": 40,
                       "description": "how many most-recent dates (default 12)"},
        }, "required": ["ticker", "metric"], "additionalProperties": False},
        fn=_get_balance_series, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="series_stat",
        display="Taking the {op} over that series",
        description=(
            "One operator over one series you already hold (a calc_id from get_flow with "
            "last_n, get_balance_series, or calculate). yoy / qoq / pct / abs return a new "
            "series of changes, each point matched to its prior BY DATE; cagr / avg / min / "
            "max / std / sum / latest return one number. The result is citable. For growth "
            "over the last N quarters: get_flow(months=3, last_n=N) then series_stat(yoy)."
        ),
        json_schema={"type": "object", "properties": {
            "series_id": {"type": "string", "description": "calc_… id of a series"},
            "op": {"type": "string", "enum": list(series_service.OPS)},
        }, "required": ["series_id", "op"], "additionalProperties": False},
        fn=_series_stat, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="describe_issuer",
        display="Looking up what {ticker} reports and what can be computed from it",
        description=(
            "Start here for any issuer: identity (name, CIK, sector, whether it can be "
            "investigated), every financial metric its filings hold with how many periods "
            "each has, and which named measures (leverage, coverage, margins …) those "
            "metrics can feed — with the missing input named for the ones they cannot."
        ),
        json_schema={"type": "object", "properties": {"ticker": _TICKER},
                     "required": ["ticker"], "additionalProperties": False},
        fn=_describe_issuer, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="get_balance_sheet",
        display="Reading {ticker}'s balance sheet",
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
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="calculate",
        display="Computing {op} of two figures",
        description=(
            "Add, subtract, multiply or divide two quantities you already have, by their "
            "ids (fact_… or calc_…). Compose anything: EBIT, leverage, coverage, margins, "
            "turnover — none of these needs to be a built-in. The result gets its own "
            "calc_id and is citable. Combinations that would silently double-count are "
            "refused with the reason: two balances from different dates added together, "
            "two flows over overlapping periods added together, or a total added to "
            "something it already contains. A balance divided by a flow is fine — that is "
            "what leverage is — and a balance subtracted from a later reading of it is the "
            "change over the days between."
        ),
        json_schema={"type": "object", "properties": {
            "op": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]},
            "a": {"type": "string", "description": "fact_… or calc_… id"},
            "b": {"type": "string", "description": "fact_… or calc_… id"},
        }, "required": ["op", "a", "b"], "additionalProperties": False},
        fn=_calculate, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="evaluate_formula",
        display="Evaluating {name} for {ticker}",
        description=(
            "One named measure for one issuer, built from the same primitives you could "
            "call yourself: the value, the definition that produced it, the period basis, "
            "a citable calc_id and the source. An input the issuer does not report is "
            "named rather than left as a hole."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "name": {"type": "string", "description": "a name from describe_issuer's formulas"},
            "months": {"type": ["integer", "null"], "minimum": 1, "maximum": 120},
            "at": {"type": ["string", "null"], "description": "YYYY-MM-DD for balance dates"},
        }, "required": ["ticker", "name"], "additionalProperties": False},
        fn=_evaluate_formula, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="get_fundamental_panel",
        display="Building the measures panel for {ticker}",
        description=(
            "Every named measure at once for one issuer — leverage, coverage, liquidity, "
            "cash generation, margins, turnover — each with its definition, period basis "
            "and calc_id. A shortcut for the whole registry, not a special path: every "
            "line is reproducible by a single evaluate_formula call. Financial issuers are "
            "refused, because interest expense is an operating cost for a bank. No "
            "judgement is attached."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER,
            "months": {"type": ["integer", "null"], "minimum": 1, "maximum": 120},
            "at": {"type": ["string", "null"], "description": "YYYY-MM-DD for balance dates"},
        }, "required": ["ticker"], "additionalProperties": False},
        fn=_get_fundamental_panel, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="get_portfolio_snapshot",
        display="Reading this desk's books and their latest run",
        description="The portfolio(s) this desk manages: latest exposure metrics, largest sector "
                    "and issuer weights, and active risk alerts. Takes no arguments — this is how "
                    "you discover holdings for a portfolio-level question. Each portfolio's numbers "
                    "carry the run_id that produced them; cite run_id (and alert ids) for portfolio claims.",
        json_schema={"type": "object", "properties": {}, "additionalProperties": False},
        fn=_get_portfolio_snapshot, tool_class=READ,
        evidence=Evidence(scope=("exposure_metrics", "issuer_exposures", "sector_exposures", "risk_alerts", "count")),
    ))
    reg.register(Tool(
        name="get_task_status",
        display="Checking whether the delegated work has finished",
        description="Whether delegated work has finished. Accepts the task_/run_/rrun_ id "
                    "that ensure_company_ready, start_exposure_run or start_issuer_research returned.",
        json_schema={"type": "object", "properties": {
            "job_id": {"type": "string", "description": "task_… / run_… / rrun_…"},
        }, "required": ["job_id"], "additionalProperties": False},
        fn=_get_task_status, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_portfolio_positions",
        display="Reading the holdings",
        description="Every holding in a portfolio: pos_id, ticker, quantity, sector, market value "
                    "and weight. Cite the pos_id for a share count. Capped at 50 rows — when "
                    "truncated is set, total_holdings is the real number and say so. "
                    "get_portfolio_snapshot only carries the largest few.",
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
        }, "required": ["portfolio_id"], "additionalProperties": False},
        fn=_get_portfolio_positions, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="read_issuer_brief",
        display="Opening the latest brief on {ticker}",
        description="The latest Issuer Risk Brief for a company, with the evidence ids behind "
                    "each block. Cite those ids, not the brief.",
        json_schema={"type": "object", "properties": {"ticker": _TICKER}, "required": ["ticker"], "additionalProperties": False},
        fn=_read_issuer_brief, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="get_attribution",
        display="Reading what the regression attributed the day to",
        description=(
            "Why a portfolio moved on the run's date: every factor's beta, return and "
            "contribution, and every position's weight, return and contribution — the "
            "complete set, not a selection. Also the regression behind the betas "
            "(observations, window, R², alpha, residual). This is the FIRST tool for any "
            "'why did it move' question; filings describe an issuer over quarters and "
            "cannot explain one day. Cite the run_id. When factors are collinear each "
            "beta carries quotable_individually=false — quote their sum instead."
        ),
        json_schema={"type": "object", "properties": {
            # No top_k. No limit. The absence is asserted by a test: a size
            # argument is how an answer comes to name two positions and imply the
            # other eight did nothing.
            "run_id": {"type": "string", "description": "an exposure run id (run_...)"},
        }, "required": ["run_id"], "additionalProperties": False},
        fn=_get_attribution, tool_class=READ,
        evidence=Evidence(scope=("factor_attributions", "issuer_exposures", "exposure_metrics")),
    ))
    reg.register(Tool(
        name="get_risk_state",
        display="Reading the run's risk measures",
        description=(
            "One run's measured risk state: exposure and volatility metrics, the tail "
            "measures with their confidence and horizon attached, every stress scenario "
            "(including the ones that were refused and why), and how many limit checks ran "
            "versus fired. Describes the book on that date under those shocks; it is not a "
            "forecast. Cite the run_id."
        ),
        json_schema={"type": "object", "properties": {
            "run_id": {"type": "string", "description": "an exposure run id (run_...)"},
        }, "required": ["run_id"], "additionalProperties": False},
        fn=_get_risk_state, tool_class=READ,
        evidence=Evidence(scope=("exposure_metrics", "stress_results", "risk_alerts", "limit_checks", "count")),
    ))
    reg.register(Tool(
        name="list_run_alerts",
        display="Reading which mandate limits the run raised",
        description=(
            "The alerts one run raised, each whole: current value, limit, utilisation, and a "
            "reads_as sentence composed for you. Use reads_as — the three numbers on an alert "
            "row are easy to attribute to the wrong quantity, and utilisation is the share of "
            "the limit consumed, never a level. Cite the alert id or the run id."
        ),
        json_schema={"type": "object", "properties": {
            "run_id": {"type": "string", "description": "an exposure run id (run_...)"},
        }, "required": ["run_id"], "additionalProperties": False},
        fn=_list_run_alerts, tool_class=READ,
        evidence=Evidence(scope=("risk_alerts", "count")),
    ))
    reg.register(Tool(
        name="list_risk_limits",
        display="Reading this book's mandate limits",
        description=(
            "The limit policy in force for a portfolio: each check's warning and breach level. "
            "This is what the desk decided, not a measurement of the world — these rows are "
            "not citable evidence. For a breached level, cite the alert that carries it."
        ),
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
        }, "required": ["portfolio_id"], "additionalProperties": False},
        fn=_list_risk_limits, tool_class=READ,
    ))
    reg.register(Tool(
        name="get_run_freshness",
        display="Checking how current the latest run is",
        description=(
            "How current a portfolio's newest completed run is: the run's date, the latest "
            "market session, how many sessions have traded since, and whether a run is in "
            "flight. Two dates kept apart on purpose — 'the run is from Thursday' and 'the "
            "market has traded twice since' are different facts."
        ),
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
        }, "required": ["portfolio_id"], "additionalProperties": False},
        fn=_get_run_freshness, tool_class=READ,
    ))
    reg.register(Tool(
        name="reconcile_move",
        display="Splitting the day's move into market and stock-specific parts",
        description=(
            "Reconcile one day's portfolio move in a single call: checks that the position "
            "contributions sum to the day's return, splits the move into what the factor "
            "model explains and what it does not (alpha_plus_residual), and names the "
            "largest factor and the largest position. Use this for 'why did the book move' "
            "and 'what drove the drawdown' before reaching for anything else. If the "
            "position identity does not hold, no share of the move is reported at all — "
            "that is a data problem, not a smaller answer. Cite the run_id or the calc_id."
        ),
        json_schema={"type": "object", "properties": {
            "run_id": {"type": "string", "description": "an exposure run id (run_...)"},
        }, "required": ["run_id"], "additionalProperties": False},
        fn=_reconcile_move, tool_class=READ,
        evidence=Evidence(scope=("issuer_exposures", "factor_attributions", "exposure_metrics")),
    ))
    reg.register(Tool(
        name="get_portfolio_analysis",
        display="Ordering the exposures and measuring the room left",
        description=(
            "One run's exposures, already ordered and netted: every stress scenario ranked "
            "by the size of the loss, the book's NET exposure to rates, credit and equity "
            "with the legs that make it up, the distance from each limit check to its own "
            "warning and breach levels, and every holding with its weight and its "
            "contribution to the day. Use this for 'what is this book exposed to', 'which "
            "risk is biggest', 'how much room is left' and 'what should I watch' — it "
            "answers in one call what otherwise takes five, and the ordering and the "
            "netting are done here rather than by you. A risk no factor measures is "
            "reported as unmeasured, not as zero. Cite the run_id, or the calc_id for the "
            "netted betas and the distances."
        ),
        json_schema={"type": "object", "properties": {
            "run_id": {"type": "string", "description": "an exposure run id (run_...)"},
        }, "required": ["run_id"], "additionalProperties": False},
        fn=_get_portfolio_analysis, tool_class=READ,
        evidence=Evidence(scope=("stress_results", "limit_checks", "factor_attributions", "issuer_exposures", "exposure_metrics", "count")),
    ))
    reg.register(Tool(
        name="describe_run",
        display="Reading what the run holds, by name",
        description=(
            "Start here for any question about THIS BOOK: everything one completed run "
            "holds, named exactly as a slot takes it, grouped by the question each group "
            "answers — book size, concentration, mandate (each check against its tiers and "
            "the room left), stress, factor exposure, attribution, risk, counts. The values "
            "come back on the table beside the names. Also says what this face can and "
            "cannot do. Read it before reaching for the per-table tools."
        ),
        json_schema={"type": "object", "properties": {
            "run_id": {"type": "string", "description": "an exposure run id (run_...) from get_portfolio_snapshot"},
        }, "required": ["run_id"], "additionalProperties": False},
        fn=_describe_run, tool_class=READ,
        evidence=Evidence(scope=tuple(qn.RUN_TABLES)),
    ))
    reg.register(Tool(
        name="read_quantities",
        display="Reading the named figures from the run",
        description=(
            "The exact figures a question needs, by name, in one call — names from "
            "describe_run (or any table you have seen), e.g. issuer_exposures.MSFT.weight, "
            "limit_checks.sector_concentration:Technology.breach_level. Unknown names are "
            "returned as unknown, not guessed."
        ),
        json_schema={"type": "object", "properties": {
            "run_id": {"type": "string"},
            "names": {"type": "array", "minItems": 1, "maxItems": 120, "items": {"type": "string"}},
        }, "required": ["run_id", "names"], "additionalProperties": False},
        fn=_read_quantities, tool_class=READ,
        evidence=Evidence(names_from="names"),
    ))
    reg.register(Tool(
        name="get_drawdown_episodes",
        display="Measuring the drawdowns over the window",
        description=(
            "When this portfolio fell and whether it came back: every peak-to-trough "
            "episode at least 5% deep in the span, deepest first, with the trough date and "
            "the recovery date (null while still under water). Use this for 'have there "
            "been drawdowns' and 'what was the worst one'. A depth is a distance below a "
            "running high, not a return."
        ),
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
            # An enum rather than a day count. "The last 37 days" is a window
            # chosen after seeing the answer.
            "span": {"type": ["string", "null"], "enum": ["3m", "6m", "1y", "3y", None],
                     "description": "history to search (default 1y)"},
        }, "required": ["portfolio_id"], "additionalProperties": False},
        fn=_get_drawdown_episodes, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="explain_episode",
        display="Explaining what happened between {peak} and {trough}",
        description=(
            "What happened between a peak and a trough: the book's cumulative return over "
            "that window, the benchmark's over the same window, and each holding's. These "
            "are fixed-window returns — they do NOT break the drawdown's depth into parts, "
            "because depth depends on the path and is not additive. Say the window when "
            "you quote any of these."
        ),
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
            "peak": {"type": "string", "description": "YYYY-MM-DD, from get_drawdown_episodes"},
            "trough": {"type": "string", "description": "YYYY-MM-DD, from get_drawdown_episodes"},
        }, "required": ["portfolio_id", "peak", "trough"], "additionalProperties": False},
        fn=_explain_episode, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="get_market_stats",
        display="Reading {ticker}'s price return",
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
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="search_filing_passages",
        display="Searching {ticker}'s filings for \u201c{query}\u201d",
        description="Semantic search across an issuer's indexed 10-K/10-Q; returns passages with citation anchors.",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER, "query": {"type": "string"},
            "k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            "form_type": _FORM_TYPE,
            "item_code": {"type": ["string", "null"], "minLength": 1,
                          "description": "narrow to an Item, e.g. 'Item 1A'"},
        }, "required": ["ticker", "query"], "additionalProperties": False},
        fn=_search_filing_passages, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="get_filing_section",
        display="Reading {item_code} of {ticker}'s filing in full",
        description="Read a whole SEC Item verbatim from the most recent filing (e.g. Item 1A Risk Factors).",
        json_schema={"type": "object", "properties": {
            "ticker": _TICKER, "item_code": {"type": "string", "minLength": 1},
            "form_type": _FORM_TYPE,
        }, "required": ["ticker", "item_code"], "additionalProperties": False},
        fn=_get_filing_section, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="list_alerts",
        display="Checking for alerts naming {ticker}",
        description="Portfolio risk alerts naming this issuer (concentration, etc.).",
        json_schema={"type": "object", "properties": {"ticker": _TICKER}, "required": ["ticker"], "additionalProperties": False},
        fn=_list_alerts, tool_class=READ,
        evidence=Evidence(),
    ))
    reg.register(Tool(
        name="think",
        display="Making a note before going on",
        description="Pause to write an analytical note before anchoring a conclusion. No side effect, no budget.",
        json_schema={"type": "object", "properties": {
            "thought": {"type": "string"},
        }, "required": ["thought"], "additionalProperties": False},
        fn=_think, tool_class=REFLECTION,
    ))
    return reg
