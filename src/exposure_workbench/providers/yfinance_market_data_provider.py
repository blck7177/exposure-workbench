"""yfinance implementation of MarketDataProvider.

yfinance objects/DataFrames are consumed here and never leak upward — callers
receive plain PriceBar DTOs.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from exposure_workbench.providers.market_data_provider import PriceBar

logger = logging.getLogger(__name__)


def _f(v) -> float | None:
    """float-or-None, treating NaN as None."""
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if fv != fv else fv  # NaN check


class YFinanceMarketDataProvider:
    name = "yfinance"

    @staticmethod
    def _yf_symbol(ticker: str) -> str:
        # yfinance uses '-' where exchange listings use '.' (BRK.A -> BRK-A). The
        # conversion lives ONLY here, at the provider boundary; the canonical dot
        # form is what we store (PriceBar.ticker below stays the original).
        return ticker.replace(".", "-")

    def fetch_prices(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        import yfinance as yf

        # yfinance `end` is exclusive — extend by one day to include `end`.
        hist = yf.Ticker(self._yf_symbol(ticker)).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=False,
        )
        if hist is None or hist.empty:
            logger.warning("yfinance returned no rows for %s [%s..%s]", ticker, start, end)
            return []

        has_adj = "Adj Close" in hist.columns
        bars: list[PriceBar] = []
        for idx, row in hist.iterrows():
            close = _f(row.get("Close"))
            if close is None:
                continue  # skip rows without a usable close
            adj = _f(row.get("Adj Close")) if has_adj else None
            pd_date = idx.date() if hasattr(idx, "date") else idx
            vol = _f(row.get("Volume"))
            bars.append(
                PriceBar(
                    ticker=ticker,
                    price_date=pd_date,
                    close=close,
                    adj_close=adj if adj is not None else close,
                    open=_f(row.get("Open")),
                    high=_f(row.get("High")),
                    low=_f(row.get("Low")),
                    volume=int(vol) if vol is not None else None,
                )
            )
        return bars

    def fetch_sector(self, ticker: str) -> str | None:
        """Best-effort GICS sector for a newly-added equity (V2-D). yfinance
        .info is slow/flaky, so any failure returns None (caller -> 'Unclassified')."""
        import yfinance as yf

        try:
            info = yf.Ticker(self._yf_symbol(ticker)).info
            sector = (info or {}).get("sector")
            return sector or None
        except Exception:  # noqa: BLE001 — sector is best-effort, never fatal
            return None
