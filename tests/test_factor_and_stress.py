"""V5 — factor attribution and stress propagation (offline: no DB, no network).

Both modules had ZERO test coverage before this file, which is how a factor
model that counted the market three times and a stress scenario that reported a
gain in a crash both survived to production. Each test states the number it
expects, because in both cases the wrong answer was a plausible-looking float.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from exposure_workbench.analytics.factor_model import calc_factor_attribution
from exposure_workbench.analytics.stress import calc_stress

CONFIG = {
    "factors": {
        "market": {"ticker": "SPY"},
        "growth": {"ticker": "QQQ"},
        "rates": {"ticker": "TLT"},
    }
}


def _dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2026-01-05", periods=n)


def _factors(n: int = 80, seed: int = 7, **series) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = _dates(n)
    return pd.DataFrame(
        {k: (v if v is not None else rng.normal(0, 0.01, n)) for k, v in series.items()},
        index=idx,
    )


# ── the factor model is ONE regression ────────────────────────────────────────

def test_betas_are_recovered_from_a_book_built_out_of_the_factors():
    f = _factors(spy=None, qqq=None)
    f.columns = ["SPY", "QQQ"]
    port = pd.Series(1.5 * f["SPY"] + 0.5 * f["QQQ"], index=f.index)

    out = calc_factor_attribution(port, f, CONFIG, lookback=60)

    betas = out.betas()
    assert betas["SPY"] == pytest.approx(1.5, abs=1e-6)
    assert betas["QQQ"] == pytest.approx(0.5, abs=1e-6)
    assert out.r_squared == pytest.approx(1.0, abs=1e-6)
    assert out.residual == pytest.approx(0.0, abs=1e-9)


def test_two_collinear_factors_do_not_each_claim_the_whole_move():
    """The headline case. Eight univariate regressions were summed as though the
    factors were orthogonal; SPY, QQQ and IWM correlate about 0.9, so the same
    market move was counted once per factor that could see it.

    Here two factors are IDENTICAL and the book is exactly one of them. Two
    univariate fits each return beta 1.0 and the sum explains 200% of a move that
    happened once. One fit splits the coefficient and explains it exactly once.
    """
    f = _factors(SPY=None)
    f["QQQ"] = f["SPY"]                      # perfectly collinear
    port = pd.Series(f["SPY"], index=f.index)

    out = calc_factor_attribution(port, f, CONFIG, lookback=60)

    latest_move = float(f["SPY"].iloc[-1])
    assert out.total_explained == pytest.approx(latest_move, abs=1e-6)
    assert out.total_explained != pytest.approx(2 * latest_move, abs=1e-6), \
        "the double count is back"
    assert sum(out.betas().values()) == pytest.approx(1.0, abs=1e-6)
    assert out.collinear is True
    assert out.max_vif == float("inf"), "perfect collinearity is infinite, not merely large"


def test_independent_factors_are_not_flagged_as_collinear():
    """The flag has to be capable of not firing, or it says nothing when it does."""
    f = _factors(SPY=None, QQQ=None, TLT=None, seed=11)
    port = pd.Series(f["SPY"], index=f.index)
    out = calc_factor_attribution(port, f, CONFIG, lookback=60)
    assert out.collinear is False
    assert out.max_vif < 5.0


def test_the_pieces_add_up_to_the_day_they_describe():
    """alpha + Σ contributions + residual == the portfolio's actual return.

    This identity is what `residual` claims to be and what it was not: subtracting
    a double-counted sum from the return produced a number with no model behind
    it, reported on the page as unexplained risk.
    """
    f = _factors(SPY=None, QQQ=None, TLT=None)
    rng = np.random.default_rng(3)
    port = pd.Series(
        0.9 * f["SPY"] + 0.3 * f["QQQ"] - 0.2 * f["TLT"] + rng.normal(0, 0.002, len(f)),
        index=f.index,
    )

    out = calc_factor_attribution(port, f, CONFIG, lookback=60)

    rebuilt = out.alpha + out.total_explained + out.residual
    assert rebuilt == pytest.approx(float(port.iloc[-1]), abs=1e-9)


def test_the_attribution_names_the_day_it_describes():
    f = _factors(SPY=None, QQQ=None)
    port = pd.Series(f["SPY"], index=f.index)
    out = calc_factor_attribution(port, f, CONFIG, lookback=60)
    assert out.as_of == f.index[-1].date()
    assert out.observations == 60


def test_too_few_observations_yields_no_model_rather_than_a_confident_one():
    f = _factors(n=12, SPY=None, QQQ=None)
    port = pd.Series(f["SPY"], index=f.index)
    out = calc_factor_attribution(port, f, CONFIG, lookback=60, min_observations=30)
    assert out.factors == [] and out.betas() == {}
    assert out.observations == 12


def test_a_regression_needs_more_rows_than_coefficients():
    """min_observations from config is a floor, not the only one: three factors
    and three observations fits perfectly and means nothing."""
    f = _factors(n=4, SPY=None, QQQ=None, TLT=None)
    port = pd.Series(f["SPY"], index=f.index)
    out = calc_factor_attribution(port, f, CONFIG, lookback=60, min_observations=1)
    assert out.factors == []


# ── stress reaches the book through the betas ─────────────────────────────────

MARKET_DOWNSIDE = {
    "market_downside": {
        "description": "Broad market correction -10%",
        "factor_shocks": {"SPY": -0.10, "QQQ": -0.12, "IWM": -0.11,
                          "TLT": 0.03, "GLD": 0.02},
    }
}

LONG_EQUITY_BETAS = {"SPY": 0.6, "QQQ": 0.4, "IWM": 0.05, "TLT": 0.05, "GLD": 0.0}


def test_a_long_equity_book_loses_money_in_a_market_crash():
    """The bug this batch exists for, in one assertion.

    The demo book is eight single stocks plus TLT and HYG. Shocks used to be
    matched by NAME against sector labels and held tickers, so a scenario naming
    SPY, QQQ, IWM, TLT and GLD matched exactly one holding — TLT, at +3% — and a
    −10% equity crash was reported as a GAIN. It was persisted as
    exposure_metrics.stress_loss_market and it could never raise an alert,
    because the limit engine skips non-positive losses.
    """
    out = calc_stress(10_000_000.0, MARKET_DOWNSIDE, LONG_EQUITY_BETAS)

    scenario = out.scenarios[0]
    assert scenario.estimated_loss_pct > 0, "a crash is a loss for a long book"
    assert scenario.estimated_loss_pct == pytest.approx(0.112)
    assert scenario.estimated_loss_usd == pytest.approx(1_120_000.0)
    assert out.worst_case_loss_pct == pytest.approx(0.112)


def test_a_hedged_book_is_allowed_to_gain_in_the_same_scenario():
    """The fix is not "always report a loss" — it is "ask the book". A short
    equity, long duration book genuinely profits here."""
    out = calc_stress(1_000_000.0, MARKET_DOWNSIDE,
                      {"SPY": -0.5, "QQQ": -0.3, "IWM": 0.0, "TLT": 0.8, "GLD": 0.0})
    assert out.scenarios[0].estimated_loss_pct < 0


def test_a_scenario_with_an_unknown_factor_is_unevaluated_not_zero():
    """Dropping the unknown leg and summing the rest understates the loss, and
    understating a stress loss is the one direction that matters. A scenario that
    is absent from `scenarios` is absent from the limit checks too."""
    out = calc_stress(1_000_000.0, MARKET_DOWNSIDE, {"SPY": 1.0})

    assert out.scenarios == []
    assert out.worst_case_loss_pct == 0.0
    assert len(out.unevaluated) == 1
    reason = out.unevaluated[0].reason
    assert "GLD" in reason and "QQQ" in reason and "no beta" in reason


def test_a_scenario_records_the_factors_it_holds_flat():
    """Zero is an assertion about credit, not silence about it. The book's
    largest unshocked beta is exactly the kind of thing that made the old
    scenario wrong, so it is on the record rather than in the YAML's omissions."""
    out = calc_stress(1_000_000.0, MARKET_DOWNSIDE,
                      {**LONG_EQUITY_BETAS, "HYG": 1.29, "USO": -0.02})
    assert out.scenarios[0].factors_held_flat == ["HYG", "USO"]


def test_a_scenario_that_shocks_nothing_is_unevaluated():
    out = calc_stress(1_000_000.0, {"empty": {"description": "d"}}, {"SPY": 1.0})
    assert out.scenarios == []
    assert "no factor_shocks" in out.unevaluated[0].reason


def test_the_loss_is_the_sum_over_shocked_factors_and_nothing_else():
    """One shock, one beta, one multiplication — there is no second path by which
    a shock can reach the answer, which is what made the old double count
    possible for anything held that was also a factor."""
    out = calc_stress(
        100.0,
        {"s": {"description": "d", "factor_shocks": {"TLT": -0.04, "HYG": -0.015}}},
        {"TLT": 0.25, "HYG": 0.10},
    )
    expected = -(0.25 * -0.04 + 0.10 * -0.015)
    assert out.scenarios[0].estimated_loss_pct == pytest.approx(expected)


def test_the_load_window_can_actually_supply_the_regression_window():
    """Two knobs, wired to different estimators, that have to agree.

    `_LOOKBACK_DAYS` decides how much history is loaded; the regression then takes
    `.tail(window_days)` of it. Set the second above what the first can supply and
    the regression silently runs on less than it asks for — which is exactly the
    state V5 shipped in: 90 calendar days yield 61 observations and window_days
    was 60, one to spare, so nobody noticed the two numbers were coupled at all.

    A calendar year holds about 252 trading days, and a margin is required rather
    than a bare fit: a market closure or one ticker's missing bar costs
    observations off the top of the panel, and the regression must not start
    quietly shrinking the first time that happens.
    """
    import yaml
    from pathlib import Path
    from exposure_workbench.workflow.exposure_workflow import _LOOKBACK_DAYS

    root = Path(__file__).resolve().parents[1]
    reg = yaml.safe_load((root / "configs" / "factor_config.yaml").read_text())["regression"]

    supply = _LOOKBACK_DAYS * 252 / 365
    assert reg["window_days"] <= supply * 0.95, (
        f"window_days={reg['window_days']} but {_LOOKBACK_DAYS} calendar days "
        f"supply only about {supply:.0f} observations"
    )
    assert reg["min_observations"] <= reg["window_days"], (
        "the floor cannot exceed the window the regression is allowed to use"
    )


def test_every_shipped_scenario_names_only_configured_factors():
    """A scenario naming a factor the model does not estimate can never be
    evaluated, so the two config files have to agree. They are edited separately
    and nothing else checks them against each other."""
    import yaml
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    factors = yaml.safe_load((root / "configs" / "factor_config.yaml").read_text())
    scenarios = yaml.safe_load((root / "configs" / "stress_scenarios.yaml").read_text())

    known = {cfg["ticker"] for cfg in factors["factors"].values()}
    for name, cfg in scenarios.items():
        shocks = cfg.get("factor_shocks", {})
        assert shocks, f"{name} declares no factor_shocks"
        unknown = set(shocks) - known
        assert not unknown, f"{name} shocks unconfigured factors: {sorted(unknown)}"
