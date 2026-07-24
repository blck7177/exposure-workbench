"""MarketDataProvider boundary — raw OHLCV fetch, no persistence.

The provider fetches; the ingestion service persists. Swapping the market-data
source later means writing another provider, with the analytics layer unchanged
(it reads persisted rows from Postgres, never a provider).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class PriceBar:
    """One trading day of prices for one ticker (provider-neutral DTO)."""

    ticker: str
    price_date: date
    close: float
    adj_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None


class MarketDataProvider(Protocol):
    """Fetches raw price history for a single ticker. No DB, no calculation."""

    name: str

    def fetch_prices(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        """Return daily bars for [start, end] inclusive. Empty list if none."""
        ...
