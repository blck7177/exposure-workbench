"""E5 — the analytics that value a portfolio (offline: no DB, no network).

These three functions had zero test coverage until now, which is how a silent
$0 valuation survived to production. Each test states the number it expects,
because the whole failure mode was arithmetic that looked plausible.

The headline case: a holding with no price used to be valued at $0 AND left in
the denominator, so it did not merely under-report market value — it inflated
every other name's weight and could fabricate a concentration breach. That is
asserted here as a raise, not as a number.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from exposure_workbench.analytics.exposure import calc_exposure
from exposure_workbench.analytics.pnl import calc_pnl
from exposure_workbench.services.market_data_service import build_portfolio_returns

AS_OF = date(2026, 7, 24)


def positions(*rows: tuple[str, float, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"ticker": t, "quantity": q, "sector": s, "asset_class": "equity",
          "cost_basis": 50.0, "price": 80.0, "market_value": 80.0 * q}
         for t, q, s in rows]
    )


def prices(*rows: tuple[str, str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"ticker": t, "price_date": pd.Timestamp(d), "close": c} for t, d, c in rows]
    )


# ── calc_exposure ─────────────────────────────────────────────────────────────

def test_values_the_book_from_market_prices():
    out = calc_exposure(
        positions(("AAPL", 100, "Tech"), ("XOM", 200, "Energy")),
        prices(("AAPL", "2026-07-24", 200.0), ("XOM", "2026-07-24", 50.0)),
        AS_OF,
    )
    assert out.portfolio_market_value == pytest.approx(30_000.0)   # 20k + 10k
    assert out.issuer_map["AAPL"]["weight"] == pytest.approx(2 / 3)
    assert out.sector_map["Energy"]["weight"] == pytest.approx(1 / 3)


def test_uses_the_last_close_on_or_before_as_of():
    out = calc_exposure(
        positions(("AAPL", 10, "Tech")),
        prices(("AAPL", "2026-07-22", 100.0), ("AAPL", "2026-07-23", 150.0),
               ("AAPL", "2026-07-25", 999.0)),   # after as_of — must be ignored
        AS_OF,
    )
    assert out.portfolio_market_value == pytest.approx(1_500.0)


def test_a_holding_with_no_price_raises_instead_of_being_valued_at_zero():
    """The regression that motivated all of E5.

    Old behaviour: STALE priced at $0, portfolio_market_value 20,000 instead of
    31,000, and AAPL's weight reported as 100% rather than 64.5% — enough to
    trip the 20% issuer-concentration breach on a portfolio that never breached.
    """
    with pytest.raises(ValueError) as e:
        calc_exposure(
            positions(("AAPL", 100, "Tech"), ("STALE", 200, "Energy")),
            prices(("AAPL", "2026-07-24", 200.0)),
            AS_OF,
        )
    assert "STALE" in str(e.value)


def test_the_error_names_every_unpriced_holding_not_just_the_first():
    with pytest.raises(ValueError) as e:
        calc_exposure(
            positions(("AAPL", 1, "Tech"), ("AAA", 1, "Tech"), ("ZZZ", 1, "Energy")),
            prices(("AAPL", "2026-07-24", 200.0)),
            AS_OF,
        )
    assert "AAA" in str(e.value) and "ZZZ" in str(e.value)


# ── calc_pnl ──────────────────────────────────────────────────────────────────

def test_pnl_measures_the_move_between_two_closes():
    out = calc_pnl(
        positions(("AAPL", 100, "Tech")),
        prices(("AAPL", "2026-07-23", 100.0), ("AAPL", "2026-07-24", 110.0)),
        AS_OF,
    )
    assert out.daily_pnl == pytest.approx(1_000.0)
    assert out.daily_return == pytest.approx(0.10)


def test_pnl_refuses_to_fall_back_to_the_stored_snapshot_price():
    """The fallback made a single run report market value from one universe and
    daily return from another: exposure said 20,000 while P&L's denominator was
    27,800, in the same run, off the same inputs."""
    with pytest.raises(ValueError) as e:
        calc_pnl(
            positions(("AAPL", 100, "Tech"), ("STALE", 200, "Energy")),
            prices(("AAPL", "2026-07-23", 100.0), ("AAPL", "2026-07-24", 110.0)),
            AS_OF,
        )
    assert "STALE" in str(e.value)


def test_a_missing_prior_close_is_flat_not_an_error():
    """Distinct from a missing CURRENT price: a name listed yesterday has no
    measurable move, which is a fact rather than a data gap."""
    out = calc_pnl(
        positions(("NEW", 10, "Tech")),
        prices(("NEW", "2026-07-24", 50.0)),
        AS_OF,
    )
    assert out.daily_pnl == pytest.approx(0.0)


# ── build_portfolio_returns ───────────────────────────────────────────────────

def test_return_series_is_weighted_across_the_whole_book():
    series = build_portfolio_returns(
        positions(("AAPL", 100, "Tech"), ("XOM", 100, "Energy")),
        prices(("AAPL", "2026-07-23", 100.0), ("AAPL", "2026-07-24", 110.0),
               ("XOM", "2026-07-23", 100.0), ("XOM", "2026-07-24", 90.0)),
    )
    # equal market values at the last close (11,000 vs 9,000) -> 55% / 45%
    assert series.iloc[-1] == pytest.approx(0.10 * 0.55 + -0.10 * 0.45)


def test_dropping_an_unpriced_holding_and_renormalising_is_refused():
    """The third missing-price convention. Silently keeping the survivors and
    scaling them to 100% fed VaR and every limit check a portfolio the user does
    not hold."""
    with pytest.raises(ValueError) as e:
        build_portfolio_returns(
            positions(("AAPL", 100, "Tech"), ("STALE", 100, "Energy")),
            prices(("AAPL", "2026-07-23", 100.0), ("AAPL", "2026-07-24", 110.0)),
        )
    assert "STALE" in str(e.value)


def test_empty_inputs_stay_empty_rather_than_raising():
    """No holdings is not a data gap — the caller handles an empty book."""
    empty = pd.DataFrame(columns=["ticker", "quantity"])
    assert build_portfolio_returns(empty, prices(("AAPL", "2026-07-24", 1.0))).empty
    assert build_portfolio_returns(positions(("AAPL", 1, "Tech")),
                                   pd.DataFrame(columns=["ticker", "price_date", "close"])).empty
