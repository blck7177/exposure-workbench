"""E5 — the run's single price-freshness judgement (offline: no DB, no network).

_validate_inputs is now the only place that decides whether a run's prices are
good enough. Everything downstream — calc_exposure, calc_pnl,
build_portfolio_returns — dropped its own fallback on the strength of that
guarantee, so a hole here is a hole in all three.

Behaviour change worth stating plainly: a portfolio holding something that has
not priced recently now produces a RED run. It used to produce a green one with
wrong numbers.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from exposure_workbench.app_state.settings import Settings, get_settings
from exposure_workbench.workflow.exposure_workflow import ExposureWorkflow

AS_OF = date(2026, 7, 24)
MAX_AGE = Settings().price_staleness_days


@pytest.fixture
def validate():
    wf = ExposureWorkflow(configs_dir="/app/configs")   # configs are not read by this path
    return wf._validate_inputs


def positions(*tickers: str) -> pd.DataFrame:
    return pd.DataFrame([{"ticker": t, "quantity": 10.0, "sector": "Tech",
                          "asset_class": "equity"} for t in tickers])


def prices(*rows: tuple[str, date, float]) -> pd.DataFrame:
    return pd.DataFrame([{"ticker": t, "price_date": pd.Timestamp(d), "close": c}
                         for t, d, c in rows])


def test_fresh_prices_for_every_holding_pass(validate):
    validate(positions("AAPL", "XOM"),
             prices(("AAPL", AS_OF, 200.0), ("XOM", AS_OF - timedelta(days=1), 50.0)),
             AS_OF)


def test_a_holding_with_no_price_fails_the_run(validate):
    with pytest.raises(ValueError) as e:
        validate(positions("AAPL", "STALE"), prices(("AAPL", AS_OF, 200.0)), AS_OF)
    assert "STALE" in str(e.value)
    assert "no price" in str(e.value)


def test_every_unpriced_holding_is_named_in_one_go(validate):
    """One fix-and-rerun cycle, not one per bad ticker."""
    with pytest.raises(ValueError) as e:
        validate(positions("AAPL", "AAA", "BBB", "CCC"), prices(("AAPL", AS_OF, 1.0)), AS_OF)
    msg = str(e.value)
    assert all(t in msg for t in ("AAA", "BBB", "CCC"))


def test_a_price_older_than_the_threshold_fails_the_run(validate):
    with pytest.raises(ValueError) as e:
        validate(positions("OLD"),
                 prices(("OLD", AS_OF - timedelta(days=MAX_AGE + 1), 42.0)), AS_OF)
    msg = str(e.value)
    assert "OLD" in msg and "older than" in msg
    assert f"{MAX_AGE + 1}d old" in msg, "the message should say how stale, not just that it is"


def test_the_threshold_boundary_is_inclusive(validate):
    """Exactly at the limit is acceptable; one day past is not. Pinned because an
    off-by-one here either fails every long weekend or never fires at all."""
    validate(positions("EDGE"), prices(("EDGE", AS_OF - timedelta(days=MAX_AGE), 1.0)), AS_OF)
    with pytest.raises(ValueError):
        validate(positions("EDGE"), prices(("EDGE", AS_OF - timedelta(days=MAX_AGE + 1), 1.0)),
                 AS_OF)


def test_missing_and_stale_are_reported_together(validate):
    with pytest.raises(ValueError) as e:
        validate(
            positions("GONE", "OLD", "GOOD"),
            prices(("OLD", AS_OF - timedelta(days=MAX_AGE + 5), 1.0), ("GOOD", AS_OF, 1.0)),
            AS_OF,
        )
    msg = str(e.value)
    assert "GONE" in msg and "OLD" in msg
    assert "GOOD" not in msg, "a healthy holding should not appear in the complaint"


def test_prices_after_as_of_do_not_count_as_fresh(validate):
    """A future as_of is the other way a run goes stale: the window still admits
    recent bars, so without this the run would go green on a price that is
    weeks older than the date being reported."""
    future = AS_OF + timedelta(days=MAX_AGE + 20)
    with pytest.raises(ValueError) as e:
        validate(positions("AAPL"), prices(("AAPL", AS_OF, 200.0)), future)
    assert "AAPL" in str(e.value)


def test_empty_inputs_still_fail_first(validate):
    with pytest.raises(ValueError, match="No positions"):
        validate(pd.DataFrame(columns=["ticker"]), prices(("AAPL", AS_OF, 1.0)), AS_OF)
    with pytest.raises(ValueError, match="No market prices"):
        validate(positions("AAPL"), pd.DataFrame(columns=["ticker", "price_date", "close"]), AS_OF)


def test_threshold_comes_from_settings_not_a_literal():
    assert get_settings().price_staleness_days == MAX_AGE
