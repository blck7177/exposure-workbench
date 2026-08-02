"""Calc service (M3) — data primitives + ledgered calculation primitives.

Every calculation writes ONE append-only row to calc_ledger and returns its
calc_id. That is what makes "the LLM may not do arithmetic" enforceable rather
than aspirational: an agent can only quote a number that some named, replayable
operation actually produced, and the ledger records the inputs it came from.

Series specs are STATELESS (each call carries its full data spec), per the M3
decision; calc_id chaining is a later evolution.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import period_ladder as pl
from exposure_workbench.analytics import series_ops as so
from exposure_workbench.db.models import CalcLedger, Company, FinancialFact, MarketPrice
from exposure_workbench.utils.ids import new_calc_id

logger = logging.getLogger(__name__)

MAX_SERIES_POINTS = 40          # hard cap so a tool can't pull unbounded history


class UnknownMetric(Exception):
    def __init__(self, metric: str):
        super().__init__(f"No facts for metric {metric!r}")
        self.metric = metric


@dataclass(frozen=True)
class SeriesSpec:
    """Full, self-contained description of a data series."""

    ticker: str
    metric: str
    period_type: str = pl.QUARTERLY     # 'quarterly' | 'annual'
    last_n: int | None = 12

    def as_params(self) -> dict:
        return asdict(self)


# ── Data primitives (read-only) ────────────────────────────────────────────────

async def _company_id(db: AsyncSession, ticker: str) -> str:
    row = await db.execute(select(Company.id).where(Company.ticker == ticker))
    cid = row.scalar_one_or_none()
    if cid is None:
        raise UnknownMetric(f"ticker {ticker}")
    return cid


async def load_fact_series(db: AsyncSession, spec: SeriesSpec) -> tuple[list[so.SeriesPoint], dict]:
    """financial_facts -> aligned SeriesPoints (via period_ladder), newest last.

    Quarterly series automatically include the derived Q4, because issuers file
    only three quarterly facts per year.
    """
    company_id = await _company_id(db, spec.ticker)
    rows = (
        await db.execute(
            select(
                FinancialFact.id, FinancialFact.period_start, FinancialFact.period_end,
                FinancialFact.value, FinancialFact.source_accession,
            ).where(
                FinancialFact.company_id == company_id,
                FinancialFact.normalized_metric == spec.metric,
                FinancialFact.value.is_not(None),
            )
        )
    ).all()
    if not rows:
        raise UnknownMetric(spec.metric)

    facts = [
        pl.FactPoint(
            fact_id=fid, period_end=pe, value=float(val),
            period_start=ps, source_accession=acc,
        )
        for fid, ps, pe, val, acc in rows
    ]

    ladder = pl.build_ladder(facts, spec.metric, spec.period_type)
    if spec.period_type == pl.QUARTERLY:
        annual = pl.build_ladder(facts, spec.metric, pl.ANNUAL)
        ladder = pl.derive_q4(ladder, annual)

    points = [
        so.SeriesPoint(
            period_end=p.period_end,
            value=p.value,
            input_fact_ids=list(p.input_fact_ids),
            quality_flags=dict(p.quality_flags),
        )
        for p in ladder.points
    ]
    limit = min(spec.last_n or MAX_SERIES_POINTS, MAX_SERIES_POINTS)
    return points[-limit:], dict(ladder.quality_flags)


async def load_price_series(
    db: AsyncSession, ticker: str, start: date, end: date
) -> list[so.PricePoint]:
    rows = (
        await db.execute(
            select(MarketPrice.price_date, MarketPrice.adj_close, MarketPrice.close).where(
                MarketPrice.ticker == ticker,
                MarketPrice.price_date >= start,
                MarketPrice.price_date <= end,
            ).order_by(MarketPrice.price_date)
        )
    ).all()
    # adj_close preferred (splits/dividends), close as the as-traded value
    return [so.PricePoint(d, float(adj if adj is not None else c)) for d, adj, c in rows]


# ── Ledger ─────────────────────────────────────────────────────────────────────

async def _record(
    db: AsyncSession,
    company_ticker: str | None,
    operation: str,
    params: dict,
    result: dict,
    input_refs: list[str],
    quality_flags: dict,
    invoked_by: str,
) -> str:
    calc_id = new_calc_id()
    db.add(
        CalcLedger(
            id=calc_id,
            company_id=company_ticker,
            operation=operation,
            params=params,
            result={**result, "quality_flags": quality_flags},
            input_refs=input_refs,
            primitive_version=so.PRIMITIVE_VERSION,
            invoked_by=invoked_by,
        )
    )
    await db.flush()
    return calc_id


def _series_payload(r: so.SeriesResult) -> dict:
    return {
        "points": [
            {"period_end": p.period_end.isoformat(), "value": p.value,
             **({"flags": p.quality_flags} if p.quality_flags else {})}
            for p in r.points
        ]
    }


# ── Calculation primitives (each writes exactly one ledger row) ────────────────

async def combine(
    db: AsyncSession, a: SeriesSpec, b: SeriesSpec, op: str, invoked_by: str = "recipe"
) -> dict:
    pa, fa = await load_fact_series(db, a)
    pb, fb = await load_fact_series(db, b)
    res = so.combine_series(pa, pb, op)
    flags = {**fa, **fb, **res.quality_flags}
    calc_id = await _record(
        db, a.ticker, res.operation,
        {"a": a.as_params(), "b": b.as_params(), "op": op},
        _series_payload(res), res.input_fact_ids(), flags, invoked_by,
    )
    return {"calc_id": calc_id, "operation": res.operation,
            **_series_payload(res), "quality_flags": flags}


async def series(
    db: AsyncSession, spec: SeriesSpec, invoked_by: str = "recipe"
) -> dict:
    """The identity primitive: a period-aligned series, ledgered like any other.

    It looks redundant — the points come straight from financial_facts — and it
    is not, because of the derived Q4. Issuers file three quarterly facts a year,
    so load_fact_series computes Q4 = annual - Q1 - Q2 - Q3. That number is equal
    to no row in any table: it carries the four input fact ids, and each of those
    facts holds a DIFFERENT value. A model quoting the Q4 figure and citing the
    facts it came from is quoting correctly and citing correctly, and V3-A1's
    numeric check would refuse it for ever — measured as four refusals in one
    live brief. Recording the series gives that value an id of its own.
    """
    points, flags = await load_fact_series(db, spec)
    res = so.SeriesResult(operation="series", points=points, quality_flags=flags)
    calc_id = await _record(
        db, spec.ticker, res.operation, {"series": spec.as_params()},
        _series_payload(res), res.input_fact_ids(), flags, invoked_by,
    )
    # Richer than the ledger payload on purpose: the caller shows per-point fact
    # ids so a reader can drill from a period straight to the filings behind it,
    # while the ledger row stays the same shape as every other primitive's.
    return {
        "calc_id": calc_id, "operation": res.operation,
        "points": [
            {"period_end": p.period_end.isoformat(), "value": p.value,
             "fact_ids": list(p.input_fact_ids),
             **({"flags": p.quality_flags} if p.quality_flags else {})}
            for p in points
        ],
        "quality_flags": flags,
    }


async def change(
    db: AsyncSession, spec: SeriesSpec, mode: str, invoked_by: str = "recipe"
) -> dict:
    points, sf = await load_fact_series(db, spec)
    res = so.compute_change(points, mode)
    flags = {**sf, **res.quality_flags}
    calc_id = await _record(
        db, spec.ticker, res.operation, {"series": spec.as_params(), "mode": mode},
        _series_payload(res), res.input_fact_ids(), flags, invoked_by,
    )
    return {"calc_id": calc_id, "operation": res.operation,
            **_series_payload(res), "quality_flags": flags}


async def stat(
    db: AsyncSession, spec: SeriesSpec, op: str, invoked_by: str = "recipe"
) -> dict:
    points, sf = await load_fact_series(db, spec)
    res = so.compute_stat(points, op)
    flags = {**sf, **res.quality_flags}
    calc_id = await _record(
        db, spec.ticker, res.operation, {"series": spec.as_params(), "op": op},
        {"value": res.value}, res.input_fact_ids, flags, invoked_by,
    )
    return {"calc_id": calc_id, "operation": res.operation,
            "value": res.value, "quality_flags": flags}


async def window_return(
    db: AsyncSession,
    ticker: str,
    start: date,
    end: date,
    benchmark: str | None = None,
    invoked_by: str = "recipe",
) -> dict:
    prices = await load_price_series(db, ticker, start, end)
    bench = await load_price_series(db, benchmark, start, end) if benchmark else None
    res = so.compute_window_return(prices, start, end, benchmark=bench)
    params = {"ticker": ticker, "start": start.isoformat(), "end": end.isoformat(),
              "benchmark": benchmark}
    refs = [f"price:{ticker}:{start.isoformat()}:{end.isoformat()}"]
    if benchmark:
        refs.append(f"price:{benchmark}:{start.isoformat()}:{end.isoformat()}")
    calc_id = await _record(
        db, ticker, res.operation, params, {"value": res.value}, refs,
        res.quality_flags, invoked_by,
    )
    return {"calc_id": calc_id, "operation": res.operation,
            "value": res.value, "quality_flags": res.quality_flags}


async def list_available_metrics(db: AsyncSession, ticker: str) -> dict:
    """The agent's map: which metrics exist for this issuer, and how deep."""
    company_id = await _company_id(db, ticker)
    rows = (
        await db.execute(
            select(FinancialFact.normalized_metric, FinancialFact.period_end)
            .where(FinancialFact.company_id == company_id,
                   FinancialFact.normalized_metric.is_not(None))
        )
    ).all()
    out: dict[str, set] = {}
    for metric, pe in rows:
        out.setdefault(metric, set()).add(pe)
    return {
        "ticker": ticker,
        "metrics": sorted(
            ({"metric": m, "periods": len(p),
              "latest_period_end": max(p).isoformat()} for m, p in out.items()),
            key=lambda d: d["metric"],
        ),
    }
