"""What check_limits emits, pinned before the thresholds move house (offline).

`check_limits` had zero test coverage — no test in the repo imported it, called
it, or asserted on an alert. That is not a coincidence: it is also the function
that has been ignoring its own `db_limits` argument since the day it was
written, so every per-portfolio threshold a user set was inert and nothing went
red.

This file is the net under that repair. The thresholds are about to stop coming
from configs/risk_limits.yaml and the 16 hardcoded cfg() defaults and start
coming from risk_limits rows. Every assertion below describes ALERT OUTPUT, not
where a number came from, so the move must leave them untouched: only `_alerts`
— the one helper that builds the threshold source — changes. An assertion that
has to be edited is a behaviour change that was not asked for.

Each case states its arithmetic, because a limit engine that is merely
plausible is the failure mode being guarded against.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics.exposure import ExposureResult
from exposure_workbench.analytics.limits import AlertResult, LimitBook, check_limits
from exposure_workbench.analytics.pnl import PnlResult
from exposure_workbench.analytics.risk_metrics import RiskResult
from exposure_workbench.analytics.stress import ScenarioResult, StressResult

# The eight (warning, breach) pairs every case is measured against. Deliberately
# equal to the thresholds in force today, so the numbers below keep their meaning
# after the source of truth changes underneath them.
THRESHOLDS: dict[str, tuple[float, float]] = {
    "daily_loss":             (0.020, 0.030),
    "var_95":                 (0.025, 0.035),
    "expected_shortfall_95":  (0.035, 0.050),
    "rolling_volatility_30d": (0.18,  0.25),
    "gross_exposure":         (1.10,  1.20),
    "sector_concentration":   (0.40,  0.50),
    "issuer_concentration":   (0.15,  0.20),
    "stress_loss":            (0.060, 0.080),
}


# ── the one seam this file allows the refactor to move ────────────────────────

def book(pairs: dict[str, tuple[float, float]]) -> LimitBook:
    """A complete set of portfolio-wide rows, in the shape the table stores."""
    return LimitBook([
        {"id": f"rl_{lt}", "limit_type": lt, "entity_id": None,
         "warning_level": w, "breach_level": b, "unit": "fraction", "is_active": True}
        for lt, (w, b) in pairs.items()
    ])


def _alerts(
    *,
    risk: RiskResult | None = None,
    stress: StressResult | None = None,
    exposure: ExposureResult | None = None,
    pnl: PnlResult | None = None,
    thresholds: dict[str, tuple[float, float]] | None = None,
) -> list[AlertResult]:
    """Run check_limits against `thresholds`. THE ONLY THING THE REFACTOR EDITED.

    It used to build the `limits_config` dict the engine read from a YAML; it now
    builds a LimitBook out of risk_limits rows. Not one assertion below moved,
    which is the whole evidence that swapping the source of the numbers did not
    change what the engine does with them.
    """
    return check_limits(
        risk, stress, exposure, pnl,
        book(THRESHOLDS if thresholds is None else thresholds),
    )[0]


# ── builders ──────────────────────────────────────────────────────────────────

def risk(*, vol_30d=None, var_95_1d=None, es_95=None) -> RiskResult:
    return RiskResult(vol_30d=vol_30d, vol_60d=None, var_95_1d=var_95_1d,
                      es_95=es_95, max_drawdown=None)


def pnl(daily_return: float) -> PnlResult:
    return PnlResult(daily_pnl=daily_return * 1_000_000, daily_return=daily_return)


def stress(*scenarios: tuple[str, float]) -> StressResult:
    return StressResult(scenarios=[
        ScenarioResult(name=n, description="", estimated_loss_pct=p,
                       estimated_loss_usd=p * 1_000_000)
        for n, p in scenarios
    ])


def exposure(
    *,
    market_value: float = 1_000_000.0,
    gross: float | None = None,
    sectors: dict[str, float] | None = None,
    issuers: dict[str, float] | None = None,
) -> ExposureResult:
    return ExposureResult(
        portfolio_market_value=market_value,
        gross_exposure=market_value if gross is None else gross,
        net_exposure=market_value,
        sector_map={s: {"market_value": w * market_value, "weight": w}
                    for s, w in (sectors or {}).items()},
        issuer_map={t: {"market_value": w * market_value, "weight": w, "sector": "Tech"}
                    for t, w in (issuers or {}).items()},
    )


def only(alerts: list[AlertResult]) -> AlertResult:
    assert len(alerts) == 1, [a.message for a in alerts]
    return alerts[0]


# ── the eight checks, one warning and one breach each ─────────────────────────

def test_daily_loss_warning():
    a = only(_alerts(pnl=pnl(-0.025)))
    assert a.alert_type == "daily_loss"
    assert a.severity == "warning"
    assert (a.entity_type, a.entity_id) == ("portfolio", "portfolio")
    assert a.current_value == pytest.approx(0.025)
    assert a.limit_value == pytest.approx(0.020)
    assert a.utilization == pytest.approx(0.025 / 0.030)
    assert a.message == "Daily portfolio loss: 2.5% vs limit 2.0% [WARNING]"


def test_daily_loss_breach():
    a = only(_alerts(pnl=pnl(-0.035)))
    assert a.severity == "breach"
    assert a.limit_value == pytest.approx(0.030)
    assert a.utilization == pytest.approx(0.035 / 0.030)
    assert a.message == "Daily portfolio loss: 3.5% vs limit 3.0% [BREACH]"


def test_a_profitable_day_is_not_a_loss():
    # The guard is on the sign of the return, not on the size of the move.
    assert _alerts(pnl=pnl(0.05)) == []


def test_var_95_breach():
    a = only(_alerts(risk=risk(var_95_1d=0.04)))
    assert a.alert_type == "var_95"
    assert a.severity == "breach"
    assert (a.entity_type, a.entity_id) == ("portfolio", "portfolio")
    assert a.limit_value == pytest.approx(0.035)
    assert a.utilization == pytest.approx(0.04 / 0.035)
    assert a.message == "1-day 95% VaR: 4.0% vs limit 3.5% [BREACH]"


def test_expected_shortfall_warning():
    a = only(_alerts(risk=risk(es_95=0.04)))
    assert a.alert_type == "expected_shortfall_95"
    assert a.severity == "warning"
    assert a.limit_value == pytest.approx(0.035)
    assert a.utilization == pytest.approx(0.04 / 0.05)
    assert a.message == "Expected Shortfall (95%): 4.0% vs limit 3.5% [WARNING]"


def test_rolling_volatility_breach():
    a = only(_alerts(risk=risk(vol_30d=0.30)))
    assert a.alert_type == "rolling_volatility_30d"
    assert a.severity == "breach"
    assert a.limit_value == pytest.approx(0.25)
    assert a.utilization == pytest.approx(0.30 / 0.25)
    assert a.message == "30d rolling volatility (annualised): 30.0% vs limit 25.0% [BREACH]"


def test_gross_exposure_warning_is_measured_against_market_value():
    # NAV is taken to be market value for a long-only book: 1.15m gross / 1m MV.
    a = only(_alerts(exposure=exposure(market_value=1_000_000, gross=1_150_000)))
    assert a.alert_type == "gross_exposure"
    assert a.severity == "warning"
    assert (a.entity_type, a.entity_id) == ("portfolio", "portfolio")
    assert a.current_value == pytest.approx(1.15)
    assert a.limit_value == pytest.approx(1.10)
    assert a.utilization == pytest.approx(1.15 / 1.20)
    assert a.message == "Gross exposure % NAV: 115.0% vs limit 110.0% [WARNING]"


def test_sector_concentration_warning():
    a = only(_alerts(exposure=exposure(gross=0, sectors={"Technology": 0.45})))
    assert a.alert_type == "sector_concentration"
    assert a.severity == "warning"
    assert (a.entity_type, a.entity_id) == ("sector", "Technology")
    assert a.limit_value == pytest.approx(0.40)
    assert a.utilization == pytest.approx(0.45 / 0.50)
    assert a.message == "Sector Technology: 45.0% vs limit 40.0% [WARNING]"


def test_issuer_concentration_breach():
    a = only(_alerts(exposure=exposure(gross=0, issuers={"AAPL": 0.25})))
    assert a.alert_type == "issuer_concentration"
    assert a.severity == "breach"
    assert (a.entity_type, a.entity_id) == ("issuer", "AAPL")
    assert a.limit_value == pytest.approx(0.20)
    assert a.utilization == pytest.approx(0.25 / 0.20)
    assert a.message == "Issuer AAPL: 25.0% vs limit 20.0% [BREACH]"


def test_stress_loss_warning_is_keyed_by_scenario_but_scoped_to_the_portfolio():
    # The one check whose key and whose entity_type disagree: it is looked up by
    # scenario name, yet the alert is about the whole book.
    a = only(_alerts(stress=stress(("Rates +100bp", 0.07))))
    assert a.alert_type == "stress_loss"
    assert a.severity == "warning"
    assert (a.entity_type, a.entity_id) == ("portfolio", "Rates +100bp")
    assert a.limit_value == pytest.approx(0.060)
    assert a.utilization == pytest.approx(0.07 / 0.08)
    assert a.message == "Stress scenario: Rates +100bp: 7.0% vs limit 6.0% [WARNING]"


# ── the boundaries ────────────────────────────────────────────────────────────

def test_below_warning_is_silent():
    assert _alerts(risk=risk(vol_30d=0.17, var_95_1d=0.02, es_95=0.03),
                   pnl=pnl(-0.019),
                   exposure=exposure(gross=1_000_000,
                                     sectors={"Technology": 0.39},
                                     issuers={"AAPL": 0.149}),
                   stress=stress(("Rates +100bp", 0.059))) == []


def test_exactly_at_a_level_fires_it():
    # >= on both tiers: the level is the first value that is not allowed.
    assert only(_alerts(risk=risk(var_95_1d=0.025))).severity == "warning"
    assert only(_alerts(risk=risk(var_95_1d=0.035))).severity == "breach"


def test_a_non_positive_reading_never_alerts():
    # Guards a zero-valued book from being read as "0% concentration, all clear"
    # by some future threshold that is itself <= 0.
    assert _alerts(exposure=exposure(gross=0, issuers={"AAPL": 0.0, "MSFT": -0.1})) == []


def test_a_metric_that_could_not_be_computed_is_not_a_pass():
    """Row presence is not check execution — pinned as today's behaviour.

    A book with too little price history gets var_95/es_95/vol_30d = None, and
    check_limits emits nothing for them. The run stays green and the UI reads
    "all limits within bounds" while three of the eight checks never ran. This
    test does not endorse that; it pins it, so the day it changes is deliberate.
    """
    assert _alerts(risk=risk()) == []


def test_breaches_sort_ahead_of_warnings():
    out = _alerts(
        risk=risk(vol_30d=0.30),                                   # breach
        pnl=pnl(-0.025),                                           # warning
        exposure=exposure(gross=0, issuers={"AAPL": 0.25}),        # breach
    )
    assert [(a.severity, a.alert_type) for a in out] == [
        ("breach", "issuer_concentration"),
        ("breach", "rolling_volatility_30d"),
        ("warning", "daily_loss"),
    ]


def test_every_entity_over_its_limit_gets_its_own_alert():
    out = _alerts(exposure=exposure(gross=0,
                                    issuers={"AAPL": 0.25, "MSFT": 0.16, "XOM": 0.05}))
    assert [(a.entity_id, a.severity) for a in out] == [
        ("AAPL", "breach"), ("MSFT", "warning"),
    ]


def test_thresholds_are_read_per_limit_type_not_shared():
    # A tighter issuer limit must not move the sector alert, and vice versa.
    tight = dict(THRESHOLDS, issuer_concentration=(0.05, 0.08))
    out = _alerts(exposure=exposure(gross=0, sectors={"Technology": 0.30},
                                    issuers={"AAPL": 0.10}),
                  thresholds=tight)
    a = only(out)
    assert (a.alert_type, a.entity_id, a.severity) == \
           ("issuer_concentration", "AAPL", "breach")
    assert a.limit_value == pytest.approx(0.08)


def test_nothing_at_all_is_no_alerts():
    assert _alerts() == []


# ── V8-P3: an alert names the check that produced it ──────────────────────────

def test_a_fired_alert_names_a_check_that_actually_ran():
    """The invariant that makes `limit_checks` truthful.

    `evaluated` keys a portfolio-wide check as `daily_loss` and a per-entity one
    as `issuer_concentration:LLY` — the entity is part of the key only when the
    check is looked up per entity. An alert carries neither of those: its
    `entity_id` comes from LIMIT_SPECS ("portfolio" for a book-wide check, the
    scenario name for stress_loss), deliberately, because "entity_type and the
    human label come from LIMIT_SPECS, never from the row that supplied the
    numbers".

    So a writer joining alerts to evaluated by rebuilding the string gets it
    wrong in two different ways at once, and the failure is silent and
    inverted: every check reads as "ran and did not fire" while three alerts sit
    beside it. Reproduced exactly that way on the live book — 27 checks recorded
    clear while LLY, MSFT and market_downside were all alerting.

    The key therefore comes from the checker, derived from the same spec scope
    that decides which getter is legal, and this is the assertion that it lines
    up with what `looked_up` recorded.
    """
    alerts, evaluated = check_limits(
        risk(), stress(("market_downside", 0.09)),
        exposure(issuers={"LLY": 0.30}, sectors={"Healthcare": 0.30}),
        pnl(-0.05),
        book(THRESHOLDS),
    )
    assert alerts, "fixture produced no alerts; the invariant would hold vacuously"
    keys = {a.check_key for a in alerts}
    assert keys <= set(evaluated), (
        f"alerts name checks that never ran: {sorted(keys - set(evaluated))}"
    )
    # And the two shapes really are different, so the test above is not trivial.
    assert any(":" in k for k in keys) and any(":" not in k for k in keys), (
        "fixture did not exercise both a per-entity and a book-wide alert"
    )
