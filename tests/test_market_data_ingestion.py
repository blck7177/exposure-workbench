"""M4 ingestion — pure row builders + fail-loud boundary (offline)."""

from __future__ import annotations

from datetime import date

import pytest

from exposure_workbench.providers.market_data_provider import PriceBar
from exposure_workbench.services import market_data_ingestion_service as mdi


def _bar(d: str, close: float, ticker="SPY", adj: float | None = None) -> PriceBar:
    # adj defaults to close, which is what the yfinance provider does when a
    # symbol has no Adj Close column — never None, so ingestion always has an
    # adjusted price to write.
    return PriceBar(
        ticker=ticker, price_date=date.fromisoformat(d), close=close,
        adj_close=close if adj is None else adj,
    )


def test_build_factor_rows_daily_return():
    bars = [_bar("2026-01-03", 100.0), _bar("2026-01-02", 90.0), _bar("2026-01-04", 99.0)]
    rows = mdi.build_factor_rows(bars, "yfinance")
    # sorted by date: 90 -> 100 -> 99
    assert rows[0]["daily_return"] is None                      # first has no prior
    assert rows[1]["daily_return"] == pytest.approx((100 - 90) / 90)
    assert rows[2]["daily_return"] == pytest.approx((99 - 100) / 100)
    assert [r["price_date"].isoformat() for r in rows] == ["2026-01-02", "2026-01-03", "2026-01-04"]


def test_factor_daily_return_is_measured_on_the_adjusted_series():
    """TLT and HYG distribute several percent a year, and the factor panel is one
    side of the regression that produces every beta. On `close` the return is
    short by each distribution — a bias, not noise, because distributions only
    ever push the close down."""
    bars = [_bar("2026-01-02", 100.0, "HYG", adj=99.0),
            _bar("2026-01-03", 99.0, "HYG", adj=99.0)]
    rows = mdi.build_factor_rows(bars, "yfinance")
    assert rows[1]["daily_return"] == pytest.approx(0.0), "a flat total-return day"
    assert rows[1]["adj_close"] == 99.0 and rows[1]["close"] == 99.0


def test_build_market_rows_carries_ohlcv_and_source():
    bar = PriceBar(ticker="AAPL", price_date=date(2026, 1, 2), close=320.0,
                   adj_close=319.5, open=318.0, high=321.0, low=317.0, volume=1000)
    rows = mdi.build_market_rows([bar], "yfinance")
    assert rows[0]["source"] == "yfinance"
    assert rows[0]["adj_close"] == 319.5 and rows[0]["volume"] == 1000


class _EmptyProvider:
    name = "fake"

    def fetch_prices(self, ticker, start, end):
        return []


class _NoExecDB:
    async def execute(self, *a, **k):
        raise AssertionError("execute must not run when provider returns no bars")

    async def commit(self):
        raise AssertionError("commit must not run when provider returns no bars")


async def test_ingest_market_prices_fail_loud_on_empty():
    with pytest.raises(mdi.MarketDataUnavailable):
        await mdi.ingest_market_prices(_NoExecDB(), ["ZZZZ"], date(2026, 1, 1), date(2026, 2, 1), _EmptyProvider())
