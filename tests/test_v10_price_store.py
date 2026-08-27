"""V10 side item — one rule for which store holds a ticker's prices (offline)."""

from __future__ import annotations

import inspect

from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import drawdown_service as ds
from exposure_workbench.services import market_data_service as mds
from exposure_workbench.tools import definitions as d


def test_the_store_rule_has_one_home():
    """Written in drawdown_service first (V8-D) because explain_episode was the
    caller that found SPY missing; window_return read the holdings store
    unconditionally and so get_market_stats on a benchmark returned nothing for
    any window older than the newest upload. Both read through price_points now
    and neither names a price table."""
    assert "price_points" in inspect.getsource(cs.load_price_series)
    assert "price_points" in inspect.getsource(ds._benchmark_series)
    for fn in (cs.load_price_series, ds._benchmark_series):
        src = inspect.getsource(fn)
        assert "FactorPrice" not in src and "MarketPrice" not in src, fn.__name__
    assert "FactorPrice" in inspect.getsource(mds.price_points)


def test_the_rule_is_decided_from_the_database_not_from_yaml():
    """The api container has no /app/configs mount. A tool reading
    factor_config.yaml to learn which tickers are factors answers fully in the
    mcp container and emptily in the api container — V2-H4's bug."""
    src = inspect.getsource(mds.price_points)
    assert "yaml" not in src.lower().replace("factor_config.yaml", "") or "factor_config.yaml" in src
    assert "_load(" not in src and "configs" not in src.replace("/app/configs", "")


def test_market_stats_reports_on_the_last_completed_session_not_the_clock():
    """V5 fixed the recipe and this tool kept date.today(): the same ticker's
    one-month return was a different number on consecutive days with nothing
    in the ledger row to say the window had moved."""
    src = inspect.getsource(d._get_market_stats)
    assert "date.today()" not in src
    assert "latest_session_date" in src
