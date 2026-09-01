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
from exposure_workbench.analytics import units
from exposure_workbench.db.models import Company, FinancialFact, Filing
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services.concept_mapping import SUPPORTED_METRICS

# Ledger operation names. Neither is a ratio: a flow and a balance both carry the
# unit of the metric beneath them, which for every citable fact here is USD.
OP_FLOW = "derive.interval"
OP_BALANCE = "read.instant"
# V10-S2. A series of windows / a series of instants. Both carry `points` and a
# `result_type` in params, which is how the resolver types them and how
# typed_calculator lifts them into element-wise arithmetic.
OP_FLOW_SERIES = "flow.series"
OP_BALANCE_SERIES = "balance.series"


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


async def _facts_unit(db: AsyncSession, fact_ids, ticker: str, metric: str) -> str | dict:
    """The one unit a set of facts is denominated in, judged by units.fact_unit.

    One metric's facts share a unit or the derived number is nonsense, and a
    unit the algebra does not know is refused rather than binned as money —
    the bin is how an EPS flow spent two versions typed as money. Refusals are
    dicts in the services' usual shape, returned by the caller as-is.
    """
    raws = set((await db.execute(
        select(FinancialFact.unit).where(FinancialFact.id.in_(list(fact_ids))))
    ).scalars().all())
    judged = {raw: units.fact_unit(raw) for raw in raws}
    unknown = sorted(repr(raw) for raw, u in judged.items() if u is None)
    if unknown:
        return {"error": "unknown_unit", "ticker": ticker, "metric": metric,
                "detail": f"{metric} facts for {ticker} are denominated in "
                          f"{', '.join(unknown)}, which this desk cannot do algebra on"}
    got = sorted(set(judged.values()))
    if len(got) != 1:
        return {"error": "inconsistent_units", "ticker": ticker, "metric": metric,
                "detail": f"{metric} facts for {ticker} mix units ({', '.join(got)}); "
                          f"one metric is one unit, so this window cannot be derived"}
    return got[0]


def _unknown_metric(metric: str) -> dict:
    return {"error": "unknown_metric", "metric": metric,
            "detail": f"{metric} is not a normalised metric; describe_issuer lists them"}


async def _metric_absence(db: AsyncSession, error: str, kind: str, ticker: str, metric: str,
                          why: str, invoked_by: str, **extra) -> dict:
    """A metric refusal that names the stand-in the registry already knows about.

    V11-A. `Formula.alternatives` has recorded since V9 that NVDA's revenue moved
    to total_revenues and MSFT's interest expense to its non-operating tag — and
    only evaluate_formula could read it. Asked for NVDA's last four quarters of
    revenue, the agent tried the retired tag twice and then reported that the
    filings cannot support a quarterly series. get_flow on total_revenues returns
    four quarters. An absence has to carry what the desk knows sits beside it, or
    it is not an absence, it is a dead end.
    """
    from exposure_workbench.services import absence_service as ab
    alts = ab.superseded_by(metric)
    covers = await ab.coverage(db, ticker, (metric,) + alts)
    latest = await ab.issuer_latest(db, ticker)
    instead = [f"{a} through {covers[a]['through']}" for a in alts if covers.get(a)]
    statement = (
        f"{why} "
        + (f"This desk holds {'; '.join(instead)} for {ticker} — the registry records "
           f"{' and '.join(alts)} as what {metric} was superseded by, so ask for that "
           f"metric instead. " if instead else "")
        + (f"{ticker}'s most recent filed period ends {latest}. " if latest else "")
        + "This is a statement about this desk's coverage, not a statement that the "
          "issuer does not disclose the item.")
    return await ab.refuse(
        db, error, kind=kind, ticker=ticker, statement=statement,
        tried={"metric": metric, **{k: v for k, v in extra.items() if k != "detail"}},
        stopped_at={"metric": metric, "coverage": covers.get(metric)},
        neighbours={"superseded_by": list(alts), "coverage": covers,
                    "issuer_latest_period_end": latest},
        invoked_by=invoked_by, metric=metric, **extra)


async def get_flow(
    db: AsyncSession,
    ticker: str,
    metric: str,
    *,
    months: int | None = None,
    start: str | None = None,
    end: str | None = None,
    last_n: int | None = None,
    invoked_by: str = "agent",
) -> dict:
    """A flow over a window — or, with `last_n` > 1, over a run of them.

    One window is "the most recent `months`-long window the filings support"
    (`latest_window`). A series is "the issuer's own reporting periods of that
    length, in order" (`consecutive_windows`), and the two do not share an end:
    the latest derivable twelve months on AAPL run to the June quarter, while
    the annual series ends at September because that is where AAPL ends its
    years. Both are right about what they are; a series of trailing-twelve-month
    windows stepping back a year at a time is what nobody means by "the last
    five years".

    There is no fallback to a shorter period. A window that cannot be derived
    comes back as a refusal naming what stopped it, because a nine-month figure
    served as a year is the silent convention switch this design removes. In a
    series that refusal sits in its slot rather than making the neighbours
    close ranks.
    """
    ticker = ticker.upper()
    if metric not in SUPPORTED_METRICS:
        return _unknown_metric(metric)
    company_id = await _company_id(db, ticker)
    if company_id is None:
        return {"error": "unknown_company", "ticker": ticker}

    facts = await _flow_facts(db, company_id, metric)
    if not facts:
        return await _metric_absence(
            db, "not_reported", "not_reported", ticker, metric,
            why=f"This desk holds no {metric} for {ticker} over any period.",
            invoked_by=invoked_by,
            detail=f"{ticker} reports no {metric} with a period; it may report "
                   f"a related line instead — call describe_issuer")

    if last_n is not None and last_n > 1:
        if start or end:
            return {"error": "invalid_arguments",
                    "detail": "a series is anchored to the issuer's reporting grid; give "
                              "`months` and `last_n`, not start/end"}
        return await _flow_series(db, ticker, metric, facts, months or 12, last_n, invoked_by)

    if start and end:
        window = ia.derive(facts, date.fromisoformat(start), date.fromisoformat(end))
    else:
        window = ia.latest_window(facts, months=months or 12)

    if isinstance(window, ia.Unreachable):
        covers = {"from": window.nearest_start.isoformat() if window.nearest_start else None,
                  "to": window.nearest_end.isoformat() if window.nearest_end else None}
        return await _metric_absence(
            db, "window_not_derivable", "window_not_derivable", ticker, metric,
            why=(f"No such window of {ticker}'s {metric} can be derived from the periods "
                 f"it files; the reported boundaries run {covers['from']} to {covers['to']}."),
            invoked_by=invoked_by, detail=window.reason, data_covers=covers)

    terms = [{"fact_id": fid, "sign": sign} for fid, sign in window.terms]
    unit = await _facts_unit(db, [t["fact_id"] for t in terms], ticker, metric)
    if isinstance(unit, dict):
        return unit
    period = {"start": window.start.isoformat(), "end": window.end.isoformat()}
    calc_id = await cs._record(
        db, ticker, OP_FLOW,
        {"metric": metric, "period": period, "terms": terms, "derivation": window.formula,
         # V16: the row states what it is. Before this, the resolver hardcoded
         # "a derive.interval is money" — which an EPS flow is not.
         "result_type": {"unit_class": unit, "kind": "flow", "quantity": metric}},
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

    best: dict[tuple[str, date], tuple] = {}
    for metric, pe, value, fid, acc, fd in rows:
        key = (metric, pe)
        prev = best.get(key)
        if prev is None or ia.restatement_key(fd, acc) > ia.restatement_key(prev[4], prev[3]):
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


# ── series (V10-S2) ───────────────────────────────────────────────────────────

def _slot(w: ia.SeriesWindow) -> dict:
    base = {"start": w.start.isoformat(), units.POINT_PERIOD_KEY: w.end.isoformat()}
    if isinstance(w.window, ia.Derived):
        return base | {"value": w.window.value,
                       "fact_ids": list(w.window.fact_ids),
                       "terms": [{"fact_id": f, "sign": s} for f, s in w.window.terms],
                       "derivation": w.window.formula}
    return base | {"value": None, "unreachable": w.window.reason}


async def _flow_series(db, ticker, metric, facts, months, last_n, invoked_by) -> dict:
    slots = ia.consecutive_windows(facts, months=months, last_n=last_n)
    derived = [w for w in slots if isinstance(w.window, ia.Derived)]
    if not derived:
        ends = sorted({f.period_end for f in facts})
        covers = {"from": ends[0].isoformat(), "to": ends[-1].isoformat()}
        return await _metric_absence(
            db, "series_not_derivable", "series_not_derivable", ticker, metric,
            why=(f"No {months}-month window of {ticker}'s {metric} can be derived from the "
                 f"periods it files under that tag, which run {covers['from']} to "
                 f"{covers['to']}."),
            invoked_by=invoked_by, months=months, data_covers=covers,
            detail=(f"no {months}-month window of {metric} can be derived from the "
                    f"periods {ticker} reports; it may report this metric only over "
                    f"longer periods — ask for a longer `months`"))
    input_ids = sorted({f for w in derived for f in w.window.fact_ids})
    unit = await _facts_unit(db, input_ids, ticker, metric)
    if isinstance(unit, dict):
        return unit
    points = [_slot(w) for w in slots]
    calc_id = await cs._record(
        db, ticker, OP_FLOW_SERIES,
        {"metric": metric, "months": months, "last_n": last_n,
         # What every point IS, once, so the resolver and the calculator need
         # no table keyed on the operation name. The unit is judged from the
         # facts, not asserted: an EPS series is money_per_share, a share-count
         # series is a count.
         "result_type": {"unit_class": unit, "kind": "flow", "quantity": metric,
                         "months": months}},
        {"points": points},
        input_ids,
        {"unreachable_slots": len(slots) - len(derived)} if len(slots) != len(derived) else {},
        invoked_by,
    )
    return {"calc_id": calc_id, "ticker": ticker, "metric": metric, "months": months,
            "points": points,
            "basis": (f"{len(derived)} consecutive {months}-month windows on {ticker}'s own "
                      f"reporting grid, "
                      f"{points[0]['start']}..{points[-1][units.POINT_PERIOD_KEY]}"
                      + (f"; {len(slots) - len(derived)} slot(s) not derivable, kept in place"
                         if len(slots) != len(derived) else ""))}


async def get_balance_series(
    db: AsyncSession, ticker: str, metric: str, *, last_n: int = 12,
    invoked_by: str = "agent",
) -> dict:
    """One balance-sheet line at each date the issuer reported it, newest last.

    No derivation, no alignment, no filling: a balance is a reading at an
    instant and there is nothing to add across instants (R2). Restatements are
    resolved by the one rule. `get_balance_sheet` is every line at ONE date;
    this is ONE line at every date — the same rows, the other axis.
    """
    ticker = ticker.upper()
    if metric not in SUPPORTED_METRICS:
        return _unknown_metric(metric)
    company_id = await _company_id(db, ticker)
    if company_id is None:
        return {"error": "unknown_company", "ticker": ticker}
    rows = (await db.execute(
        select(FinancialFact.period_end, FinancialFact.value, FinancialFact.id,
               FinancialFact.source_accession, Filing.filing_date)
        .outerjoin(Filing, Filing.id == FinancialFact.filing_id)
        .where(FinancialFact.company_id == company_id,
               FinancialFact.normalized_metric == metric,
               FinancialFact.dimensions_hash == "",
               FinancialFact.period_start.is_(None),
               FinancialFact.value.is_not(None))
    )).all()
    if not rows:
        return await _metric_absence(
            db, "not_reported", "not_reported", ticker, metric,
            why=f"This desk holds no {metric} for {ticker} as a balance at any date.",
            invoked_by=invoked_by,
            detail=f"{ticker} reports no {metric} as a balance; it may be a flow — "
                   f"call get_flow, or describe_issuer to see which it is")
    best: dict[date, tuple] = {}
    for pe, value, fid, acc, fd in rows:
        prev = best.get(pe)
        if prev is None or ia.restatement_key(fd, acc) > ia.restatement_key(prev[3], prev[2]):
            best[pe] = (float(value), fid, acc, fd)
    dates = sorted(best)[-max(1, last_n):]
    unit = await _facts_unit(db, [best[d][1] for d in dates], ticker, metric)
    if isinstance(unit, dict):
        return unit
    points = [{units.POINT_PERIOD_KEY: d.isoformat(), "value": best[d][0],
               "fact_ids": [best[d][1]]}
              for d in dates]
    calc_id = await cs._record(
        db, ticker, OP_BALANCE_SERIES,
        {"metric": metric, "last_n": last_n,
         "result_type": {"unit_class": unit, "kind": "instant", "quantity": metric}},
        {"points": points}, [p["fact_ids"][0] for p in points], {}, invoked_by,
    )
    return {"calc_id": calc_id, "ticker": ticker, "metric": metric, "points": points,
            "basis": f"{metric} as reported at each of {len(points)} instants, "
                     f"{points[0][units.POINT_PERIOD_KEY]}.."
                     f"{points[-1][units.POINT_PERIOD_KEY]}; "
                     f"no value is carried across dates"}


async def quarterly_points(db: AsyncSession, ticker: str, metric: str, *, last_n: int = 8):
    """Derived quarters as (period_end, value, fact_ids), oldest first — for
    in-process callers that need the series without a ledger row (the panel's
    TTM is a sum it records itself). Unreachable slots are omitted here because
    a caller summing quarters has no use for a slot with no value; the tool
    face keeps them, where a reader can see the gap.

    Raises LookupError when the issuer reports nothing under this metric, which
    is the shape the panel already handled for the ladder.
    """
    company_id = await _company_id(db, ticker.upper())
    if company_id is None:
        raise LookupError(ticker)
    facts = await _flow_facts(db, company_id, metric)
    if not facts:
        raise LookupError(metric)
    return [(w.end, w.window.value, tuple(w.window.fact_ids))
            for w in ia.consecutive_windows(facts, months=3, last_n=last_n)
            if isinstance(w.window, ia.Derived)]
