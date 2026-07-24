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

    def fetch_prices(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        import yfinance as yf

        # yfinance `end` is exclusive — extend by one day to include `end`.
        hist = yf.Ticker(ticker).history(
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
