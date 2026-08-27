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

from exposure_workbench.analytics import series_ops as so
from exposure_workbench.db.models import CalcLedger, Company, Filing, FinancialFact, MarketPrice
from exposure_workbench.utils.ids import new_calc_id

logger = logging.getLogger(__name__)



class UnknownMetric(Exception):
    def __init__(self, metric: str):
        super().__init__(f"No facts for metric {metric!r}")
        self.metric = metric



async def _company_id(db: AsyncSession, ticker: str) -> str:
    row = await db.execute(select(Company.id).where(Company.ticker == ticker))
    cid = row.scalar_one_or_none()
    if cid is None:
        raise UnknownMetric(f"ticker {ticker}")
    return cid


async def load_price_series(
    db: AsyncSession, ticker: str, start: date, end: date
) -> list[so.PricePoint]:
    """The store rule lives in market_data_service.price_points (V10); this is
    the name window_return has always called."""
    from exposure_workbench.services import market_data_service as mds
    points, _store = await mds.price_points(db, ticker, start, end)
    return points


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
