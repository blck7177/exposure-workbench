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


def prices(*rows) -> pd.DataFrame:
    """(ticker, date, close) or (ticker, date, close, adj_close).

    Three-element rows mean "no corporate action", i.e. adj_close == close. The
    four-element form is how a split or a dividend is expressed: the two prices
    diverge, and which of them a calculation reads becomes visible.
    """
    return pd.DataFrame(
        [
            {
                "ticker": r[0],
                "price_date": pd.Timestamp(r[1]),
                "close": r[2],
                "adj_close": r[3] if len(r) > 3 else r[2],
            }
            for r in rows
        ]
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


def test_pnl_does_not_report_a_split_as_a_loss():
    """4:1 split: the close falls 75%, the holder has lost nothing.

    Close-to-close P&L reported this position down $30,000 on a $40,000 book —
    the largest single-day loss the system could produce, from an event in which
    no money moved. The move is read off the adjusted series instead.
    """
    out = calc_pnl(
        positions(("AAPL", 100, "Tech")),
        prices(("AAPL", "2026-07-23", 400.0, 100.0),
               ("AAPL", "2026-07-24", 100.0, 100.0)),
        AS_OF,
    )
    assert out.daily_pnl == pytest.approx(0.0)
    assert out.daily_return == pytest.approx(0.0)


def test_pnl_counts_a_dividend_instead_of_reporting_it_as_a_drop():
    """Ex-date: close falls by the dividend, the total return is flat."""
    out = calc_pnl(
        positions(("XOM", 100, "Energy")),
        prices(("XOM", "2026-07-23", 100.0, 99.0),
               ("XOM", "2026-07-24", 99.0, 99.0)),
        AS_OF,
    )
    assert out.daily_pnl == pytest.approx(0.0)


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
    """Distinct from a missing CURRENT price: a name with nothing before its
    first bar has no prior close, which is a fact rather than a data gap.

    Note this is NOT the same as both lookups landing on the same bar — see
    below. Telling those apart is the whole reason _last_bar returns a date.
    """
    out = calc_pnl(
        positions(("NEW", 10, "Tech")),
        prices(("NEW", "2026-07-24", 50.0)),
        AS_OF,
    )
    assert out.daily_pnl == pytest.approx(0.0)


def test_a_book_priced_entirely_off_one_bar_refuses_to_report_a_flat_day():
    """Found by review, reproduced on the live system: a run dated today, before
    today's close exists, resolved both sides of the comparison to yesterday's
    bar and reported daily_pnl 0.00 on a $10.4M portfolio. Perfectly flat reads
    as a calm day, not as missing data."""
    with pytest.raises(ValueError) as e:
        calc_pnl(
            positions(("AAPL", 100, "Tech"), ("XOM", 50, "Energy")),
            # newest bar predates as_of, so as_of and prev_date both land on it
            prices(("AAPL", "2026-07-22", 200.0), ("AAPL", "2026-07-23", 210.0),
                   ("XOM", "2026-07-22", 50.0), ("XOM", "2026-07-23", 51.0)),
            date(2026, 7, 27),
        )
    assert "no daily move" in str(e.value).lower()


def test_one_untraded_name_among_many_is_still_a_real_flat_position():
    """A subset being stale must NOT fail the run — that is a genuine, measurable
    zero, and failing on it would make illiquid holdings unusable."""
    out = calc_pnl(
        positions(("AAPL", 100, "Tech"), ("QUIET", 10, "Utilities")),
        prices(("AAPL", "2026-07-23", 100.0), ("AAPL", "2026-07-24", 110.0),
               ("QUIET", "2026-07-20", 5.0)),
        AS_OF,
    )
    assert out.daily_pnl == pytest.approx(1_000.0), "AAPL's move still counts"


# ── build_portfolio_returns ───────────────────────────────────────────────────

def test_the_return_series_weights_by_yesterday_not_by_hindsight():
    """The look-ahead case, stated as the number it used to get wrong.

    100 shares of each name, both at $100 on day one: the book is exactly half in
    each. One rises 10%, the other falls 10%, so the book is flat and the series
    must say 0.0%.

    It used to say +1.0%. Weights were computed from the LAST close in the
    window — 11,000 vs 9,000, i.e. 55%/45% — and applied backwards to every day,
    including the day before those closes existed. The bias is not noise: the
    winner is always the one weighted up, so every book in the system reported a
    return series flattered by exactly the dispersion of its own holdings.
    """
    series = build_portfolio_returns(
        positions(("AAPL", 100, "Tech"), ("XOM", 100, "Energy")),
        prices(("AAPL", "2026-07-23", 100.0), ("AAPL", "2026-07-24", 110.0),
               ("XOM", "2026-07-23", 100.0), ("XOM", "2026-07-24", 90.0)),
    )
    assert series.iloc[-1] == pytest.approx(0.0)
    assert series.iloc[-1] != pytest.approx(0.01), "the hindsight weights are back"


def test_returns_are_measured_on_the_adjusted_series_not_the_close():
    """A 4:1 split is a −75% close and a 0% return. VaR must see the 0%."""
    series = build_portfolio_returns(
        positions(("AAPL", 100, "Tech")),
        prices(("AAPL", "2026-07-23", 400.0, 100.0),
               ("AAPL", "2026-07-24", 100.0, 100.0)),
    )
    assert series.iloc[-1] == pytest.approx(0.0)


def test_a_stale_bar_is_a_hole_not_a_flat_day():
    """ffill() used to invent the middle day at AAPL's previous close.

    The invented day carries a 0.0% return that no estimator can tell from a
    real one, and it lands in the sample variance as if the market had been
    quiet. Here the book genuinely has two observations, not three.
    """
    series = build_portfolio_returns(
        positions(("AAPL", 100, "Tech"), ("XOM", 100, "Energy")),
        prices(("AAPL", "2026-07-22", 100.0), ("AAPL", "2026-07-24", 110.0),
               ("XOM", "2026-07-22", 100.0), ("XOM", "2026-07-23", 100.0),
               ("XOM", "2026-07-24", 100.0)),
    )
    assert len(series) == 1, "only 07-22 -> 07-24 is priced on both legs"
    assert series.index[-1] == pd.Timestamp("2026-07-24")


def test_a_return_spanning_a_gap_is_dropped_rather_than_labelled_one_day():
    """Two bars a month apart make a monthly move wearing a daily label."""
    series = build_portfolio_returns(
        positions(("AAPL", 100, "Tech")),
        prices(("AAPL", "2026-06-24", 100.0), ("AAPL", "2026-07-24", 130.0)),
    )
    assert series.empty


def test_a_long_weekend_is_still_a_one_day_return():
    """The gap rule must not eat Friday-to-Monday, which is 3 calendar days."""
    series = build_portfolio_returns(
        positions(("AAPL", 100, "Tech")),
        prices(("AAPL", "2026-07-24", 100.0), ("AAPL", "2026-07-27", 101.0)),
    )
    assert len(series) == 1
    assert series.iloc[-1] == pytest.approx(0.01)


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
