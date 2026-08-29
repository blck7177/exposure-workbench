"""A balance subtracted from a later reading of it is the change between them (offline).

The typed calculator refused `WC@2026-03-28 − WC@2025-03-29` with
different_instants — the refusal R2 exists for, except R2 is about ADDING across
time. The series axis had always allowed the same subtraction element-wise, so
the scalar and series paths disagreed about one semantics, and the scalar
refusal's way out pointed at get_balance_sheet, which reads one instant and
cannot produce a change. The question that needs it ("how much has working
capital moved?") was therefore unanswerable from balances at all.

Found by the out-of-module battery, 2026-08-29 (wc-swing). The numbers below are
AAPL's, from the ledger rows the battery's chain produced.
"""

from __future__ import annotations

from datetime import date

import pytest

from exposure_workbench.services import typed_calculator as tc


def _bal(v: float, on: str, q: str | None = None, sid: str = "fact_x") -> tc.Typed:
    return tc.Typed(value=v, unit_class=tc.MONEY, instant=date.fromisoformat(on),
                    quantity=q, source_id=sid)


def _flow(v: float, start: str, end: str, q: str | None = None, sid: str = "calc_x") -> tc.Typed:
    return tc.Typed(value=v, unit_class=tc.MONEY,
                    interval=(date.fromisoformat(start), date.fromisoformat(end)),
                    quantity=q, source_id=sid)


def test_two_balances_added_across_dates_are_still_refused_and_told_the_way_out():
    """R2 stays: this is the AAPL 82.7 + 8.3 shape, across time instead of
    across containment. What changed is that the refusal now names the
    operation that IS allowed on these two operands."""
    r = tc._check("add", _bal(1, "2026-03-28", sid="a"), _bal(1, "2025-03-29", sid="b"))
    assert r["error"] == "different_instants"
    assert "subtract" in r["detail"]


def test_a_balance_subtracted_from_a_later_reading_is_the_change_over_the_days_between():
    later = _bal(9.473e9, "2026-03-28", sid="calc_wc_now")
    earlier = _bal(-25.897e9, "2025-03-29", sid="calc_wc_then")
    assert tc._check("subtract", later, earlier) is None

    t = tc._result_type("subtract", later, earlier, later.value - earlier.value)
    assert t.value == pytest.approx(35.37e9)
    assert t.instant is None, "a change is not a reading at one instant"
    # The day AFTER the earlier reading through the later one — the same
    # convention the filed flows use, so the delta and a flow over the period
    # carry one interval.
    assert t.interval == (date(2025, 3, 30), date(2026, 3, 28))
    assert t.quantity is None, "a change is not a balance-sheet line; containment has no say"
    assert t.unit_class == tc.MONEY


def test_the_change_is_typed_so_r1_meets_it_with_a_flow_over_the_same_period():
    """ΔWC plus operating cash flow over the same fiscal year is a legitimate
    reconciliation; ΔWC plus one quarter of it is not — the shared days would
    be counted twice. Both verdicts come from R1 unchanged, because the delta
    arrives typed as a flow over exactly the days it accrued."""
    delta = tc._result_type("subtract", _bal(2, "2026-03-28"), _bal(1, "2025-03-29"), 1)
    fiscal_year = _flow(5, "2025-03-30", "2026-03-28", q="operating_cash_flow", sid="calc_fy")
    assert tc._check("add", delta, fiscal_year) is None
    one_quarter = _flow(5, "2025-12-28", "2026-03-28", q="operating_cash_flow", sid="calc_q")
    assert tc._check("add", delta, one_quarter)["error"] == "overlapping_intervals"


def test_operand_order_changes_the_sign_and_not_the_window():
    a, b = _bal(2, "2026-03-28"), _bal(1, "2025-03-29")
    forward = tc._result_type("subtract", a, b, a.value - b.value)
    backward = tc._result_type("subtract", b, a, b.value - a.value)
    assert forward.interval == backward.interval
    assert forward.value == -backward.value


def test_two_readings_at_one_date_subtracted_are_still_a_balance_at_that_date():
    """Working capital AT a date is current assets minus current liabilities at
    that date; nothing about that path moved."""
    t = tc._result_type("subtract",
                        _bal(144.114e9, "2026-03-28", q="current_assets"),
                        _bal(134.641e9, "2026-03-28", q="current_liabilities"),
                        9.473e9)
    assert t.instant == date(2026, 3, 28)
    assert t.interval is None


def test_add_and_subtract_of_balances_are_governed_by_the_same_two_rules():
    """The whole asymmetry in one place: same two operands, the only difference
    is the operator. Add is refused for double-counting across time; subtract
    is the change."""
    a, b = _bal(2, "2026-03-28", q="cash_and_equivalents"), _bal(1, "2025-03-29", q="cash_and_equivalents")
    assert tc._check("add", a, b)["error"] == "different_instants"
    assert tc._check("subtract", a, b) is None
