"""V14-A. The arithmetic that happens before the analysis.

What these hold is mostly one shape: a quantity that could not be computed must
not come back as zero, and a quantity that has two sides must carry both.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import integration as ig


def _factor(name, ticker, beta, source="run_x"):
    return {"factor_name": name, "factor_ticker": ticker, "beta": beta, "source_id": source}


# ── ranking ───────────────────────────────────────────────────────────────────

def test_ranking_is_by_magnitude_not_by_sign():
    # A -7.4% loss outranks a +2.0% gain. Ordering by value would bury the
    # worst case under everything that went well.
    items = [
        ig.RankedItem("gain", 0.020, "RATIO", "run_x", "l1"),
        ig.RankedItem("worst", -0.074, "RATIO", "run_x", "l2"),
        ig.RankedItem("small", -0.015, "RATIO", "run_x", "l3"),
    ]
    assert [i.name for i in ig.rank_by_magnitude(items)] == ["worst", "gain", "small"]


def test_ranking_ties_keep_a_stable_order():
    # Two scenarios with equal loss must not swap between identical calls: "the
    # largest" changing on a page refresh is a defect a reader cannot see.
    items = [
        ig.RankedItem("beta", -0.05, "RATIO", "run_x", "l1"),
        ig.RankedItem("alpha", -0.05, "RATIO", "run_x", "l2"),
    ]
    once = [i.name for i in ig.rank_by_magnitude(items)]
    twice = [i.name for i in ig.rank_by_magnitude(list(reversed(items)))]
    assert once == twice == ["alpha", "beta"]


# ── netting ───────────────────────────────────────────────────────────────────

def test_a_risk_no_factor_measures_has_no_net_rather_than_zero():
    # The stress module's rule, one layer up: a scenario whose factors have no
    # beta is unevaluated, not harmless. A 0.0 here would say the book is flat
    # to a risk nothing ever looked at.
    assert ig.net_factor_exposure([_factor("market", "SPY", 1.0)], "rates_up", False) is None


def test_the_legs_survive_the_net():
    # A net of -0.4 hiding +1.1 against -1.5 is a different book from one with a
    # single -0.4 leg. Both are reported, and gross says how much disagreement
    # the net is standing on.
    factors = [_factor("rates", "TLT", 1.1), _factor("credit", "HYG", 0.4)]
    net = ig.net_factor_exposure(factors, "rates_up", False)
    assert net is not None
    assert [l.name for l in net.legs] == ["rates"]     # HYG speaks to credit, not rates
    assert net.net == pytest.approx(-1.1)              # long duration loses if rates rise
    assert net.gross == pytest.approx(1.1)


def test_the_net_of_offsetting_legs_is_smaller_than_the_gross():
    factors = [_factor("rates", "TLT", 1.0), _factor("rates_short", "TLT", -0.6)]
    net = ig.net_factor_exposure(factors, "rates_up", False)
    assert net is not None
    assert net.net == pytest.approx(-0.4)
    assert net.gross == pytest.approx(1.6)
    assert abs(net.net) < net.gross


def test_direction_is_a_word_and_zero_is_neither():
    long_duration = ig.net_factor_exposure([_factor("rates", "TLT", 1.0)], "rates_up", False)
    short_duration = ig.net_factor_exposure([_factor("rates", "TLT", -1.0)], "rates_up", False)
    flat = ig.net_factor_exposure(
        [_factor("a", "TLT", 1.0), _factor("b", "TLT", -1.0)], "rates_up", False)
    assert long_duration.direction == "loses"    # rates up hurts a duration long
    assert short_duration.direction == "gains"
    assert flat.direction == "flat"


def test_a_collinear_run_keeps_the_net_quotable_and_says_the_legs_are_not():
    # The net IS the sum, and the sum is what a collinear regression determines
    # well. This is the one place the collinearity rule loosens rather than
    # tightens, and it loosens for a stated reason.
    net = ig.net_factor_exposure([_factor("rates", "TLT", 1.0)], "rates_up", collinear=True)
    assert net.quotable_individually is False


def test_unknown_collinearity_is_not_reported_as_fine():
    net = ig.net_factor_exposure([_factor("rates", "TLT", 1.0)], "rates_up", collinear=None)
    assert net.quotable_individually is None


def test_a_factor_with_no_beta_is_not_a_leg():
    assert ig.net_factor_exposure([_factor("rates", "TLT", None)], "rates_up", False) is None


# ── headroom ──────────────────────────────────────────────────────────────────

def _check(limit_type, current, warning, breach, evaluated=True, entity=None):
    return {"limit_type": limit_type, "entity_id": entity, "current_value": current,
            "warning_level": warning, "breach_level": breach, "evaluated": evaluated,
            "source_id": "run_x"}


def test_a_check_that_did_not_run_has_no_headroom():
    # V7-U4 one layer up: a check that never ran must not look like one that
    # passed, and here it must not look like one with room to spare.
    assert ig.headroom([_check("issuer_weight", 0.10, 0.12, 0.15, evaluated=False)]) == []


def test_both_distances_are_carried_and_a_breach_reads_as_negative_room():
    [h] = ig.headroom([_check("issuer_weight", 0.155, 0.12, 0.15)])
    assert h.status == "breach"
    assert h.to_warning == pytest.approx(-0.035)
    assert h.to_breach == pytest.approx(-0.005)


def test_headroom_is_ordered_by_the_nearest_breach():
    rows = ig.headroom([
        _check("sector_weight", 0.20, 0.35, 0.40, entity="Tech"),
        _check("issuer_weight", 0.145, 0.12, 0.15, entity="MSFT"),
    ])
    assert [r.entity for r in rows] == ["MSFT", "Tech"]


def test_a_check_missing_a_level_is_skipped_not_defaulted():
    # limits.py refuses to hold a threshold that is not in risk_limits; the same
    # refusal has to survive the trip through here, or the module becomes the
    # place a default gets invented.
    assert ig.headroom([_check("issuer_weight", 0.10, None, 0.15)]) == []


# ── integration matrix ────────────────────────────────────────────────────────

def test_the_matrix_is_ordered_by_weight_and_carries_both_halves():
    rows = ig.integration_matrix(
        [{"ticker": "AAPL", "sector": "Tech", "weight": 0.14, "contribution": -0.0025,
          "market_value": 1_500_000.0, "source_id": "run_x"},
         {"ticker": "MSFT", "sector": "Tech", "weight": 0.16, "contribution": 0.0010,
          "market_value": 1_700_000.0, "source_id": "run_x"}],
        coverage={"MSFT": ["total_debt", "net_margin"]},
    )
    assert [r.ticker for r in rows] == ["MSFT", "AAPL"]
    assert rows[0].measures_available == ["net_margin", "total_debt"]
    assert rows[0].contribution == pytest.approx(0.0010)


def test_coverage_not_asked_for_is_empty_not_a_claim_of_none():
    # An empty list here means "not looked up". The caller decides whether to,
    # because looking it up in a pure function means reaching for a database.
    [row] = ig.integration_matrix([{"ticker": "XOM", "weight": 0.05}])
    assert row.measures_available == []


def test_a_position_without_a_weight_sorts_last_rather_than_as_zero_weight():
    rows = ig.integration_matrix(
        [{"ticker": "NEW", "weight": None}, {"ticker": "OLD", "weight": 0.01}])
    assert [r.ticker for r in rows] == ["OLD", "NEW"]
    assert rows[1].weight is None
