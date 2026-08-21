"""Market-data ingestion (M4) — provider bars -> market_prices / factor_prices.

This is the WRITE side of the market-data boundary. The existing read side
(`market_data_service`) is unchanged: analytics keep reading persisted rows.

Fail-loud (rule A): a ticker that returns zero bars raises MarketDataUnavailable
rather than silently persisting nothing. Idempotent: upsert on (ticker, price_date).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import FactorPrice, MarketPrice
from exposure_workbench.providers.market_data_provider import MarketDataProvider, PriceBar

logger = logging.getLogger(__name__)


class MarketDataUnavailable(RuntimeError):
    """Raised when a required ticker yields no price data (fail-loud boundary)."""

    def __init__(self, ticker: str):
        super().__init__(f"No price data returned for ticker {ticker!r}")
        self.ticker = ticker


# ── Pure row builders (unit-testable, no DB, no network) ───────────────────────

def build_market_rows(bars: list[PriceBar], source: str) -> list[dict]:
    return [
        {
            "ticker": b.ticker,
            "price_date": b.price_date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "adj_close": b.adj_close,
            "volume": b.volume,
            "source": source,
        }
        for b in bars
    ]


def build_factor_rows(bars: list[PriceBar], source: str) -> list[dict]:
    """Factor rows carry close, adj_close and daily_return.

    daily_return is computed from the ADJUSTED series, like every other return in
    the system. Computed from `close` it was short by each distribution TLT and
    HYG paid, and on any split it was the split.
    """
    ordered = sorted(bars, key=lambda b: b.price_date)
    rows: list[dict] = []
    prev: float | None = None
    for b in ordered:
        adj = b.adj_close
        daily_return = (
            (adj - prev) / prev
            if (adj is not None and prev is not None and prev != 0)
            else None
        )
        prev = adj
        rows.append(
            {
                "ticker": b.ticker,
                "price_date": b.price_date,
                "close": b.close,
                "adj_close": adj,
                "daily_return": daily_return,
                "source": source,
            }
        )
    return rows


# ── Async ingestion (worker/API path; seed reuses these too) ───────────────────

async def _fetch(provider: MarketDataProvider, ticker: str, start: date, end: date) -> list[PriceBar]:
    # provider.fetch_prices is blocking (yfinance) — keep it off the event loop.
    return await asyncio.to_thread(provider.fetch_prices, ticker, start, end)


async def ingest_market_prices(
    db: AsyncSession,
    tickers: list[str],
    start: date,
    end: date,
    provider: MarketDataProvider,
    commit: bool = True,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ticker in tickers:
        bars = await _fetch(provider, ticker, start, end)
        if not bars:
            raise MarketDataUnavailable(ticker)
        rows = build_market_rows(bars, provider.name)
        stmt = pg_insert(MarketPrice).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "price_date"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "adj_close": stmt.excluded.adj_close,
                "volume": stmt.excluded.volume,
                "source": stmt.excluded.source,
            },
        )
        await db.execute(stmt)
        counts[ticker] = len(rows)
        logger.info("ingested %d market rows for %s", len(rows), ticker)
    if commit:
        await db.commit()
    return counts


async def ingest_factor_prices(
    db: AsyncSession,
    tickers: list[str],
    start: date,
    end: date,
    provider: MarketDataProvider,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ticker in tickers:
        bars = await _fetch(provider, ticker, start, end)
        if not bars:
            raise MarketDataUnavailable(ticker)
        rows = build_factor_rows(bars, provider.name)
        stmt = pg_insert(FactorPrice).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "price_date"],
            set_={
                "close": stmt.excluded.close,
                "adj_close": stmt.excluded.adj_close,
                "daily_return": stmt.excluded.daily_return,
                "source": stmt.excluded.source,
            },
        )
        await db.execute(stmt)
        counts[ticker] = len(rows)
        logger.info("ingested %d factor rows for %s", len(rows), ticker)
    await db.commit()
    return counts
