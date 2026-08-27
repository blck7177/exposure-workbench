"""The two read primitives an agent composes report analysis out of.

`get_flow` answers a metric over a window the caller chooses, derived from
whatever intervals the issuer actually filed (V9 axiom R1, interval_algebra).
`get_balance_sheet` answers every balance at ONE instant (R2).

Between them they are the whole surface: EBIT, leverage, coverage, margins and
turnover are combinations, and the agent may form any of them. What these two
refuse to do is the pair of things the corpus proved dangerous — serving a
shorter window under the name of a longer one, and reading "the latest of each"
balance across different dates. GOOGL's last long_term_debt_total is
2025-12-31 at 49.085bn while its noncurrent balance runs to 2026-06-30 at
98.165bn, so latest-of-each produces a total smaller than its own component.

Every derived value writes a ledger row carrying the signed facts behind it, so
the number the agent quotes resolves through the citation gate exactly as a
reported fact does.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import interval_algebra as ia
from exposure_workbench.db.models import Company, FinancialFact, Filing
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services.concept_mapping import SUPPORTED_METRICS

# Ledger operation names. Neither is a ratio: a flow and a balance both carry the
# unit of the metric beneath them, which for every citable fact here is USD.
OP_FLOW = "derive.interval"
OP_BALANCE = "read.instant"


async def _company_id(db: AsyncSession, ticker: str) -> str | None:
    return (await db.execute(
        select(Company.id).where(Company.ticker == ticker.upper())
    )).scalar_one_or_none()


async def _flow_facts(db: AsyncSession, company_id: str, metric: str) -> list[ia.FlowFact]:
    rows = (await db.execute(
        select(FinancialFact.id, FinancialFact.period_start, FinancialFact.period_end,
               FinancialFact.value, FinancialFact.source_accession, Filing.filing_date)
        .outerjoin(Filing, Filing.id == FinancialFact.filing_id)
        .where(FinancialFact.company_id == company_id,
               FinancialFact.normalized_metric == metric,
               FinancialFact.dimensions_hash == "",          # consolidated only (R4)
               FinancialFact.period_start.is_not(None),      # flows carry a window
               FinancialFact.value.is_not(None))
    )).all()
    return [ia.FlowFact(fact_id=fid, period_start=ps, period_end=pe, value=float(v),
                        source_accession=acc, filing_date=fd)
            for fid, ps, pe, v, acc, fd in rows]


def _unknown_metric(metric: str) -> dict:
    return {"error": "unknown_metric", "metric": metric,
            "detail": f"{metric} is not a normalised metric; call list_available_data"}


async def get_flow(
    db: AsyncSession,
    ticker: str,
    metric: str,
    *,
    months: int | None = None,
    start: str | None = None,
    end: str | None = None,
    invoked_by: str = "agent",
) -> dict:
    """A flow over a window. Either `months` (most recent derivable) or an
    explicit `start`/`end` pair.

    There is no fallback to a shorter period. A window that cannot be derived
    comes back as a refusal naming what stopped it, because a nine-month figure
    served as a year is the silent convention switch this design removes.
    """
    ticker = ticker.upper()
    if metric not in SUPPORTED_METRICS:
        return _unknown_metric(metric)
    company_id = await _company_id(db, ticker)
    if company_id is None:
        return {"error": "unknown_company", "ticker": ticker}

    facts = await _flow_facts(db, company_id, metric)
    if not facts:
        return {"error": "not_reported", "ticker": ticker, "metric": metric,
                "detail": f"{ticker} reports no {metric} with a period; it may report "
                          f"a related line instead — call list_available_data"}

    if start and end:
        window = ia.derive(facts, date.fromisoformat(start), date.fromisoformat(end))
    else:
        window = ia.latest_window(facts, months=months or 12)

    if isinstance(window, ia.Unreachable):
        return {"error": "window_not_derivable", "ticker": ticker, "metric": metric,
                "detail": window.reason,
                "data_covers": {"from": window.nearest_start.isoformat() if window.nearest_start else None,
                                "to": window.nearest_end.isoformat() if window.nearest_end else None}}

    terms = [{"fact_id": fid, "sign": sign} for fid, sign in window.terms]
    period = {"start": window.start.isoformat(), "end": window.end.isoformat()}
    calc_id = await cs._record(
        db, ticker, OP_FLOW,
        {"metric": metric, "period": period, "terms": terms, "derivation": window.formula},
        {"value": window.value}, [t["fact_id"] for t in terms], {}, invoked_by,
    )
    return {"calc_id": calc_id, "ticker": ticker, "metric": metric,
            "value": window.value, "period": period, "terms": terms,
            "derivation": window.formula,
            "basis": f"{period['start']}..{period['end']}, derived as: {window.formula}"}


async def get_balance_sheet(
    db: AsyncSession, ticker: str, *, at: str | None = None, invoked_by: str = "agent",
) -> dict:
    """Every balance this issuer reported at one instant.

    `at` defaults to the most recent instant with any balance. Lines absent at
    that instant are listed separately WITH the date they were last reported, so
    a caller can ask for that date deliberately. What never happens is
    substitution: a balance from another date is a different number about a
    different company-moment, and adding it to these would be arithmetic across
    time.
    """
    ticker = ticker.upper()
    company_id = await _company_id(db, ticker)
    if company_id is None:
        return {"error": "unknown_company", "ticker": ticker}

    rows = (await db.execute(
        select(FinancialFact.normalized_metric, FinancialFact.period_end,
               FinancialFact.value, FinancialFact.id,
               FinancialFact.source_accession, Filing.filing_date)
        .outerjoin(Filing, Filing.id == FinancialFact.filing_id)
        .where(FinancialFact.company_id == company_id,
               FinancialFact.normalized_metric.is_not(None),
               FinancialFact.dimensions_hash == "",
               FinancialFact.period_start.is_(None),         # instants only (R2)
               FinancialFact.value.is_not(None))
    )).all()
    if not rows:
        return {"error": "no_balance_sheet_data", "ticker": ticker}

    from exposure_workbench.analytics.period_ladder import restatement_key
    best: dict[tuple[str, date], tuple] = {}
    for metric, pe, value, fid, acc, fd in rows:
        key = (metric, pe)
        prev = best.get(key)
        if prev is None or restatement_key(fd, acc) > restatement_key(prev[4], prev[3]):
            best[key] = (float(value), fid, pe, acc, fd)

    as_of = date.fromisoformat(at) if at else max(pe for _m, pe in best)
    balances, absent = {}, {}
    for metric in sorted({m for m, _pe in best}):
        here = best.get((metric, as_of))
        if here is not None:
            balances[metric] = {"value": here[0], "fact_id": here[1],
                                "as_of": as_of.isoformat()}
        else:
            seen = [pe for m, pe in best if m == metric]
            last = max((pe for pe in seen if pe < as_of), default=None) or max(seen)
            absent[metric] = {
                "last_reported": last.isoformat(),
                "value_then": best[(metric, last)][0],
                "note": ("reported at another date; ask for that date rather than "
                         "combining it with these"),
            }

    return {"ticker": ticker, "as_of": as_of.isoformat(),
            "balances": balances, "not_reported_at_this_date": absent,
            "basis": f"balance sheet as of {as_of.isoformat()}; one instant, no substitution"}
