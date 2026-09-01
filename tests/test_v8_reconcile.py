"""V8-B — one call that reconciles a day's move (offline).

The identities are checked live against real rows. Here: the shapes that must
hold whatever the data says, and the two namings the batch is partly about.
"""

from __future__ import annotations

import inspect

import pytest

from exposure_workbench.services import numeric_verification as nv
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import reconcile_service as rs
from exposure_workbench.tools.registries import build_meta_registry


def test_the_ledger_operation_is_typed_as_a_ratio():
    """The failure this prevents is specific and was named in the V8 baseline
    before it could happen: an operation missing from _CALC_RATIO_OPS is typed
    MONEY, so the gate refuses the share figure the tool itself produced and the
    refusal reads as the model having made something up."""
    assert rs.OP_RECONCILE in qn._CALC_RATIO_OPS


def test_the_unexplained_remainder_is_not_called_specific_return():
    """It is alpha + residual: the average daily return the factor set misses
    over the window, plus this day's miss. That is a statement about the MODEL.
    "Specific return" names it as a property of the holdings and licenses a
    sentence about stock selection that nothing here measured."""
    src = inspect.getsource(rs)
    assert "alpha_plus_residual" in src
    assert "specific_return" not in src.replace("specific_return`", "")  # the docstring may name it to forbid it
    payload_names = [ln for ln in src.splitlines() if '"' in ln and "specific" in ln.lower()]
    assert not [ln for ln in payload_names if '"specific_return"' in ln]


def test_no_permission_field(monkeypatch):
    """DP2. Whether a move is best called systematic or idiosyncratic is a
    judgement about wording, and this returns the numbers it would be made from.
    A boolean saying "you may now talk about a stock" would, on a book whose top
    five positions are two thirds of it, resolve to 'the market did it' almost
    always — unfalsifiably."""
    src = inspect.getsource(rs)
    for word in ("may_", "allowed", "permit", "license", "licence", "idiosyncratic_ok"):
        assert f'"{word}' not in src


def test_tolerance_is_derived_from_the_stored_scale_not_chosen():
    """Numeric(12, 8) means one ulp is 1e-8 and each stored term carries at most
    half of that. Summing n terms and comparing against one more stored value
    admits (n+1) halves. A fixed epsilon would be a number somebody picked, and
    stale the moment a column's scale changes; a relative tolerance errs in both
    directions at once (V3)."""
    assert rs._tolerance(0) == pytest.approx(0.5e-8)
    assert rs._tolerance(10) == pytest.approx(5.5e-8)
    # Strictly increasing in the number of terms: more addends, more admitted
    # rounding, and never the other way round.
    assert rs._tolerance(20) > rs._tolerance(10) > rs._tolerance(1)


def test_shares_are_absent_not_null_when_the_identity_fails():
    """A null share invites "unknown share of the move". An absent key cannot be
    read at all. The dataclass is what makes the two mutually exclusive by
    construction rather than by a caller remembering to check a flag."""
    assert set(rs._Shares.__dataclass_fields__) == {"factor_share", "unexplained_share"}
    # V13-S5 fix: the arithmetic lives in reconcile(); reconcile_move is the
    # entry point that also records it.
    src = inspect.getsource(rs.reconcile)
    assert "out |= asdict(shares)" in src, "shares must be merged in only on the holding branch"
    assert "shares_note" in src


def test_identity_b_closes_against_the_total_return_revaluation():
    """The correction the live rows forced on the plan. The plan wrote identity B
    against `daily_return`; the regression was fitted against total-return
    prices, so the residual closes against `attribution_portfolio_return` and
    against nothing else. Measured on the demo book the two differ by 2.4e-6 —
    forty times the tolerance — and written the plan's way the 'unexplained'
    figure silently absorbs a valuation convention."""
    # V13-S5 fix: the arithmetic lives in reconcile(); reconcile_move is the
    # entry point that also records it.
    src = inspect.getsource(rs.reconcile)
    assert "unexplained = attr_return - sum_factors" in src
    assert "unexplained = daily_return" not in src


def test_the_tool_is_registered_and_carries_no_size_argument():
    reg = build_meta_registry()
    tool = reg.tools["reconcile_move"]
    assert set(tool.json_schema["properties"]) == {"run_id"}
