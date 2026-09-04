"""V21-S3 — a stated share count is carried to the date it is valued on (offline).

positions.quantity is a snapshot as of positions.as_of_date; a run values it
at the run date's as-traded close. A split between the two dates put the count
and the close on different bases and the position at a fraction of itself —
weights, concentration and every limit check on them with it (V5 §5, the one
thing the price convention did not fix). The carry is one pure function, the
splits come from the same provider call as the prices, and the workflow makes
the carry once so every consumer downstream reads one column.
"""

from __future__ import annotations

import sys
import types
from datetime import date

import pandas as pd
import pytest

from exposure_workbench.analytics import splits as sp
from exposure_workbench.providers.market_data_provider import PriceBar
from exposure_workbench.services import market_data_ingestion_service as ing


def _split(ticker: str, d: date, ratio: float) -> sp.Split:
    return sp.Split(ticker=ticker, ex_date=d, ratio=ratio)


# ── the arithmetic ─────────────────────────────────────────────────────────────

def test_a_count_stated_before_a_split_is_multiplied_when_valued_after_it():
    valued, applied = sp.carry_quantity(100.0, date(2024, 6, 1), date(2024, 7, 1),
                                        [_split("NVDA", date(2024, 6, 10), 10.0)])
    assert valued == 1000.0 and [s.ratio for s in applied] == [10.0]


def test_a_count_stated_after_a_split_is_divided_when_valued_before_it():
    valued, applied = sp.carry_quantity(1000.0, date(2024, 7, 1), date(2024, 6, 1),
                                        [_split("NVDA", date(2024, 6, 10), 10.0)])
    assert valued == 100.0 and len(applied) == 1


def test_no_split_in_the_interval_means_the_stated_count_is_the_valued_count():
    valued, applied = sp.carry_quantity(100.0, date(2024, 6, 1), date(2024, 7, 1),
                                        [_split("NVDA", date(2021, 7, 20), 4.0),
                                         _split("NVDA", date(2024, 8, 1), 2.0)])
    assert valued == 100.0 and applied == []


def test_the_interval_is_open_at_the_stated_date_and_closed_at_the_valued_date():
    """A split ON the stated date is already in the stated count; a split ON
    the valued date is in the valued count (the ex-date is the first session
    the new count trades)."""
    on_stated = [_split("X", date(2024, 6, 1), 2.0)]
    on_valued = [_split("X", date(2024, 7, 1), 2.0)]
    assert sp.carry_quantity(10.0, date(2024, 6, 1), date(2024, 7, 1), on_stated)[0] == 10.0
    assert sp.carry_quantity(10.0, date(2024, 6, 1), date(2024, 7, 1), on_valued)[0] == 20.0


def test_several_splits_compound_in_date_order_and_a_reverse_split_divides():
    valued, applied = sp.carry_quantity(
        100.0, date(2020, 1, 1), date(2025, 1, 1),
        [_split("X", date(2024, 1, 1), 0.1), _split("X", date(2021, 1, 1), 4.0)])
    assert valued == pytest.approx(40.0)
    assert [s.ex_date for s in applied] == [date(2021, 1, 1), date(2024, 1, 1)]


def test_the_same_date_carries_nothing_and_a_bad_ratio_is_refused():
    assert sp.carry_quantity(7.0, date(2024, 1, 1), date(2024, 1, 1), [_split("X", date(2024, 1, 1), 2.0)]) == (7.0, [])
    with pytest.raises(ValueError):
        sp.carry_quantity(7.0, date(2024, 1, 1), date(2024, 2, 1), [_split("X", date(2024, 1, 15), 0.0)])


def test_carried_reports_the_factor_between_stated_and_valued():
    c = sp.carry("NVDA", 100.0, date(2024, 6, 1), date(2024, 7, 1), [_split("NVDA", date(2024, 6, 10), 10.0)])
    assert (c.stated, c.valued, c.factor) == (100.0, 1000.0, 10.0)
    assert c.applied[0].ex_date == date(2024, 6, 10)
    assert sp.carry("KO", 5.0, date(2024, 6, 1), date(2024, 7, 1), []).factor == 1.0


# ── the provider and the ingestion ────────────────────────────────────────────

def _fake_yfinance(frame: pd.DataFrame):
    """A yfinance module whose Ticker(...).history(...) returns `frame`."""
    calls: dict = {}

    class _Ticker:
        def __init__(self, symbol):
            calls["symbol"] = symbol

        def history(self, **kw):
            calls["kwargs"] = kw
            return frame

    return types.SimpleNamespace(Ticker=_Ticker), calls


def test_the_provider_reads_the_split_off_the_same_history_call(monkeypatch):
    from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider

    idx = pd.to_datetime(["2024-06-07", "2024-06-10", "2024-06-11"])
    frame = pd.DataFrame({
        "Open": [1200.0, 120.0, 121.0], "High": [1210.0, 122.0, 123.0], "Low": [1190.0, 119.0, 120.0],
        "Close": [1208.9, 121.8, 120.9], "Adj Close": [120.8, 121.7, 120.8],
        "Volume": [1_000, 10_000, 9_000], "Dividends": [0.0, 0.0, 0.01], "Stock Splits": [0.0, 10.0, 0.0],
    }, index=idx)
    fake, calls = _fake_yfinance(frame)
    monkeypatch.setitem(sys.modules, "yfinance", fake)

    bars = YFinanceMarketDataProvider().fetch_prices("NVDA", date(2024, 6, 7), date(2024, 6, 11))

    assert calls["kwargs"]["actions"] is True, "splits ride on the history frame; no second request"
    assert [b.split_ratio for b in bars] == [None, 10.0, None]
    assert bars[1].price_date == date(2024, 6, 10)
    assert bars[0].close == 1208.9 and bars[0].volume == 1_000, "the price columns are unchanged"


def test_a_frame_without_the_actions_column_yields_bars_with_no_split(monkeypatch):
    from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider

    frame = pd.DataFrame({"Close": [10.0], "Adj Close": [10.0], "Volume": [5]},
                         index=pd.to_datetime(["2024-06-07"]))
    fake, _ = _fake_yfinance(frame)
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    bars = YFinanceMarketDataProvider().fetch_prices("KO", date(2024, 6, 7), date(2024, 6, 7))
    assert bars[0].split_ratio is None


def test_split_rows_are_the_bars_that_carry_a_ratio_and_nothing_else():
    bars = [PriceBar("NVDA", date(2024, 6, 7), 1208.9, 120.8),
            PriceBar("NVDA", date(2024, 6, 10), 121.8, 121.7, split_ratio=10.0),
            PriceBar("NVDA", date(2024, 6, 11), 120.9, 120.8, split_ratio=None)]
    rows = ing.build_split_rows(bars, "yfinance")
    assert rows == [{"ticker": "NVDA", "ex_date": date(2024, 6, 10), "ratio": 10.0, "source": "yfinance"}]
    assert len(ing.build_market_rows(bars, "yfinance")) == 3, "price rows are untouched"


# ── the workflow carries once ─────────────────────────────────────────────────

class _Pos:
    def __init__(self, pid, ticker, qty, as_of):
        self.id, self.ticker, self.quantity, self.as_of_date = pid, ticker, qty, as_of
        self.sector, self.asset_class, self.cost_basis, self.price, self.market_value = "Tech", "equity", None, None, None


@pytest.mark.asyncio
async def test_load_inputs_values_every_holding_on_the_run_date_basis(monkeypatch):
    """Two names stated on 2024-06-01; NVDA split 10:1 on 2024-06-10; the run
    is 2024-07-01. NVDA's quantity is ×10 and KO's is what was stated; the
    stated numbers and the factor travel beside them."""
    from exposure_workbench.services import market_data_service as mds
    from exposure_workbench.services import portfolio_service
    from exposure_workbench.workflow.exposure_workflow import ExposureWorkflow

    asked: dict = {}

    async def _splits(_db, tickers, start, end):
        asked.update(tickers=tickers, start=start, end=end)
        return {"NVDA": [_split("NVDA", date(2024, 6, 10), 10.0)], "KO": []}

    async def _prices(_db, tickers, start, end):
        return pd.DataFrame(columns=["ticker", "price_date", "close", "adj_close"])

    async def _limits(_db, _pid, active_only=True):
        return []

    monkeypatch.setattr(mds, "get_splits", _splits)
    monkeypatch.setattr(mds, "get_prices_df", _prices)
    monkeypatch.setattr(mds, "get_factor_prices_df", _prices)
    monkeypatch.setattr(portfolio_service, "get_risk_limits", _limits)

    wf = ExposureWorkflow(configs_dir="configs")
    wf._load_configs()
    positions = [_Pos("pos_1", "NVDA", 100.0, date(2024, 6, 1)), _Pos("pos_2", "KO", 50.0, date(2024, 6, 1))]
    positions_df, *_ = await wf._load_inputs(None, "port_1", date(2024, 7, 1), positions=positions)

    by = positions_df.set_index("ticker")
    assert by.loc["NVDA", "quantity"] == 1000.0 and by.loc["NVDA", "stated_quantity"] == 100.0
    assert by.loc["NVDA", "split_factor"] == 10.0
    assert by.loc["KO", "quantity"] == 50.0 and by.loc["KO", "split_factor"] == 1.0
    assert by.loc["NVDA", "stated_as_of"] == date(2024, 6, 1)
    assert asked["tickers"] == ["KO", "NVDA"]
    assert (asked["start"], asked["end"]) == (date(2024, 6, 1), date(2024, 7, 1)), (
        "the splits asked for are the ones between the stated date and the run date")


def test_the_consumers_read_the_carried_column_and_not_the_stated_one():
    """market value, P&L and the value path all read positions_df['quantity'];
    none reads stated_quantity. The carry is made once, upstream of all three."""
    import inspect
    from exposure_workbench.analytics import exposure, pnl
    from exposure_workbench.services import market_data_service as mds
    for mod in (exposure, pnl, mds):
        src = inspect.getsource(mod)
        assert "stated_quantity" not in src, f"{mod.__name__} reads the stated count"
        assert '"quantity"' in src


def test_the_method_statement_says_the_count_is_carried_through_splits():
    from exposure_workbench.analytics import methods as mt
    assert "carried through the split" in mt.METHODS["market_value"]
    assert "split-adjusted quantities" in mt.METHODS["value_path"]
