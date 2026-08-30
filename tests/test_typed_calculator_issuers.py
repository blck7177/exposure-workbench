"""The double-count rules apply within an issuer; a product carries its factors'
periods (offline, pure functions).

Two findings from the round-4 battery (2026-08-29), both deterministic:

The calculator was issuer-blind. `AAPL cash @2026-03-28 + MSFT cash @2026-03-31`
was refused with different_instants — the same words, and the same way out
("ask for both at one date"), as `AAPL @March + AAPL @December`. Only the second
is a double count; the first is a sum of two companies' moments, and two
issuers on different fiscal calendars never share a date, so every book-level
question was unreachable by construction. R2 and R3 exist to stop one whole
being counted twice, which needs the two operands to be parts of one whole.

A product lost its periods. Net margin (flow/flow) and asset turnover
(flow/balance) each carried a basis; their product reached the ledger with
basis `' multiply '`, and an answer that stated the periods was stating what
its row did not hold, while one that did not violated the system prompt's own
rule. Now every derived quantity carries the leaf periods it rests on.
"""

from __future__ import annotations

from datetime import date

import pytest

from exposure_workbench.services import typed_calculator as tc


def bal(v, on, issuer=None, q=None, sid="fact_x"):
    return tc.Typed(value=v, unit_class=tc.MONEY, instant=date.fromisoformat(on),
                    quantity=q, source_id=sid, issuers=(issuer,) if issuer else ())


def flow(v, s, e, issuer=None, q=None, sid="calc_x"):
    return tc.Typed(value=v, unit_class=tc.MONEY,
                    interval=(date.fromisoformat(s), date.fromisoformat(e)),
                    quantity=q, source_id=sid, issuers=(issuer,) if issuer else ())


# ── ③ the issuer dimension ──────────────────────────────────────────────────────

def test_two_issuers_balances_at_different_dates_may_be_summed():
    aapl = bal(45.572e9, "2026-03-28", "AAPL", "cash_and_equivalents", "fact_a")
    msft = bal(32.105e9, "2026-03-31", "MSFT", "cash_and_equivalents", "fact_m")
    assert tc._check("add", aapl, msft) is None

    t = tc._result_type("add", aapl, msft, aapl.value + msft.value)
    assert t.value == pytest.approx(77.677e9)
    assert t.instant is None and t.interval is None, "two moments, not one"
    assert t.unit_class == tc.MONEY, "a sum of money is money, not a ratio"
    assert t.issuers == ("AAPL", "MSFT")
    assert t.recorded_basis["cross_issuer"] is True
    assert t.recorded_basis["mixed"] == "2026-03-28 + 2026-03-31"
    assert t.recorded_basis["leaves"] == {"instants": ["2026-03-28", "2026-03-31"], "intervals": []}


def test_one_issuers_balances_at_different_dates_are_still_refused():
    a = bal(1, "2026-03-28", "AAPL", sid="a")
    b = bal(1, "2025-12-27", "AAPL", sid="b")
    assert tc._check("add", a, b)["error"] == "different_instants"


def test_an_unknown_issuer_counts_as_shared_so_legacy_rows_keep_the_guard():
    """A row recorded before quantities carried an issuer must not become
    combinable with everything by virtue of saying nothing."""
    legacy = bal(1, "2026-03-28", sid="calc_old")
    msft = bal(1, "2026-03-31", "MSFT", sid="b")
    assert tc._check("add", legacy, msft)["error"] == "different_instants"


def test_containment_does_not_reach_across_issuers():
    """AAPL's long-term debt does not contain MSFT's current portion."""
    a = bal(80e9, "2026-03-28", "AAPL", "long_term_debt_total", "a")
    other = bal(3e9, "2026-03-31", "MSFT", "current_portion_long_term_debt", "b")
    assert tc._check("add", a, other) is None
    own = bal(3e9, "2026-03-28", "AAPL", "current_portion_long_term_debt", "c")
    assert tc._check("add", a, own)["error"] == "overlapping_quantities"


def test_overlapping_windows_do_not_double_count_across_issuers():
    a = flow(10, "2025-01-01", "2025-12-31", "GOOGL", "revenue", "a")
    b = flow(20, "2025-07-01", "2026-06-30", "MSFT", "revenue", "b")
    assert tc._check("add", a, b) is None
    t = tc._result_type("add", a, b, 30)
    assert t.recorded_basis["leaves"]["intervals"] == [["2025-01-01", "2025-12-31"],
                                                       ["2025-07-01", "2026-06-30"]]
    same = flow(20, "2025-07-01", "2026-06-30", "GOOGL", "revenue", "c")
    assert tc._check("add", a, same)["error"] == "overlapping_intervals"


def test_units_and_the_stock_flow_rule_hold_across_issuers_too():
    """Being different companies excuses double-counting, not nonsense."""
    a = bal(1, "2026-03-28", "AAPL", sid="a")
    f = flow(1, "2025-03-30", "2026-03-28", "MSFT", sid="f")
    assert tc._check("add", a, f)["error"] == "incompatible_bases"
    r = tc.Typed(value=0.5, unit_class=tc.RATIO, instant=date(2026, 3, 31),
                 issuers=("MSFT",), source_id="r")
    assert tc._check("add", a, r)["error"] == "incompatible_units"


def test_a_cross_issuer_sum_at_one_date_is_a_balance_at_that_date():
    a = bal(1, "2026-03-31", "MSFT", sid="a")
    b = bal(2, "2026-03-31", "LLY", sid="b")
    t = tc._result_type("add", a, b, 3)
    assert t.instant == date(2026, 3, 31)
    assert t.issuers == ("LLY", "MSFT")


def test_a_cross_issuer_sum_is_still_a_balance_and_takes_a_third_issuer():
    """Three issuers' cash, summed pairwise: the running sum has no single
    instant, and the stock/flow rule reads its leaves rather than refusing it
    as 'a flow'."""
    ab = tc._result_type("add", bal(1, "2026-03-28", "AAPL", sid="a"),
                         bal(2, "2026-03-31", "MSFT", sid="b"), 3)
    assert tc._kind(ab) == "instant"
    nvda = bal(3, "2026-07-26", "NVDA", sid="n")
    assert tc._check("add", ab, nvda) is None
    t = tc._result_type("add", ab, nvda, 6)
    assert t.issuers == ("AAPL", "MSFT", "NVDA")
    assert t.recorded_basis["leaves"]["instants"] == ["2026-03-28", "2026-03-31", "2026-07-26"]
    assert t.recorded_basis["mixed"] == "(2026-03-28 + 2026-03-31) + 2026-07-26"


def test_a_cross_issuer_sum_refuses_an_issuer_it_already_holds():
    """The side door: AAPL + MSFT, then AAPL again at another date. Whether
    AAPL's slice is being counted twice cannot be told from the sum, so it
    is refused — the one place this batch errs toward a refusal."""
    ab = tc._result_type("add", bal(1, "2026-03-28", "AAPL", sid="a"),
                         bal(2, "2026-03-31", "MSFT", sid="b"), 3)
    again = bal(1, "2025-12-27", "AAPL", sid="a2")
    r = tc._check("add", ab, again)
    assert r["error"] == "mixed_basis_operand"
    assert "2026-03-28" in r["detail"] and "single-period" in r["detail"]


def test_row_issuers_prefers_the_recorded_list_then_the_company_column():
    assert tc._row_issuers({"issuers": ["AAPL", "MSFT"]}, None) == ("AAPL", "MSFT")
    assert tc._row_issuers({}, "NVDA") == ("NVDA",)
    assert tc._row_issuers(None, None) == ()


def test_as_dict_carries_the_issuers_into_the_ledger():
    t = bal(1, "2026-03-28", "AAPL", "cash_and_equivalents", "fact_a")
    assert t.as_dict()["issuers"] == ["AAPL"]


# ── ② a product carries the periods of its factors ─────────────────────────────

def _dupont_legs():
    ni = flow(132.17e9, "2025-01-01", "2025-12-31", "GOOGL", "net_income", "calc_ni")
    rev = flow(402.836e9, "2025-01-01", "2025-12-31", "GOOGL", "total_revenues", "calc_rev")
    assets = bal(921.983e9, "2026-06-30", "GOOGL", "total_assets", "fact_ta")
    margin = tc._result_type("divide", ni, rev, ni.value / rev.value)
    turnover = tc._result_type("divide", rev, assets, rev.value / assets.value)
    return margin, turnover


def test_a_quotient_carries_both_operands_periods():
    margin, turnover = _dupont_legs()
    assert margin.unit_class == tc.RATIO
    assert margin.recorded_basis["mixed"] == "2025-01-01..2025-12-31 / 2025-01-01..2025-12-31"
    assert turnover.recorded_basis["leaves"] == {"instants": ["2026-06-30"],
                                                 "intervals": [["2025-01-01", "2025-12-31"]]}
    assert "cross_issuer" not in turnover.recorded_basis


def test_a_product_of_two_quotients_keeps_every_leaf_period():
    """The row this test exists for: ROE = margin × turnover × multiplier
    reached the ledger with basis ' multiply ' and nothing else."""
    margin, turnover = _dupont_legs()
    product = tc._result_type("multiply", margin, turnover, margin.value * turnover.value)
    assert product.unit_class == tc.RATIO
    assert product.issuers == ("GOOGL",)
    assert product.recorded_basis["mixed"] == (
        "(2025-01-01..2025-12-31 / 2025-01-01..2025-12-31) × "
        "(2025-01-01..2025-12-31 / 2026-06-30)")
    assert product.recorded_basis["leaves"] == {"instants": ["2026-06-30"],
                                                "intervals": [["2025-01-01", "2025-12-31"]]}


def test_a_derived_quantity_read_back_from_the_ledger_keeps_its_leaves():
    """What _resolve reconstructs from result_type.basis round-trips whole."""
    rec = {"mixed": "(a / b) × (c / d)",
           "leaves": {"instants": ["2026-06-30"], "intervals": [["2025-01-01", "2025-12-31"]]}}
    t = tc.Typed(value=0.14, unit_class=tc.RATIO, recorded_basis=rec,
                 issuers=("GOOGL",), source_id="calc_roe")
    assert t.basis() == rec
    assert tc._leaves(t) == rec["leaves"]
    assert tc._basis_str(t) == "((a / b) × (c / d))"
    assert tc._kind(t) == "mixed"


def test_a_difference_of_two_ratios_carries_its_periods_too():
    this_year = tc.Typed(value=0.30, unit_class=tc.RATIO, issuers=("GOOGL",), source_id="m1",
                         recorded_basis={"mixed": "2025-01-01..2025-12-31 / 2025-01-01..2025-12-31",
                                         "leaves": {"instants": [], "intervals": [["2025-01-01", "2025-12-31"]]}})
    last_year = tc.Typed(value=0.28, unit_class=tc.RATIO, issuers=("GOOGL",), source_id="m0",
                         recorded_basis={"mixed": "2024-01-01..2024-12-31 / 2024-01-01..2024-12-31",
                                         "leaves": {"instants": [], "intervals": [["2024-01-01", "2024-12-31"]]}})
    assert tc._check("subtract", this_year, last_year) is None
    t = tc._result_type("subtract", this_year, last_year, 0.02)
    assert t.recorded_basis["leaves"]["intervals"] == [["2024-01-01", "2024-12-31"],
                                                       ["2025-01-01", "2025-12-31"]]


def test_the_leaves_of_a_plain_fact_are_itself():
    assert tc._leaves(bal(1, "2026-03-28")) == {"instants": ["2026-03-28"], "intervals": []}
    assert tc._leaves(flow(1, "2025-01-01", "2025-12-31")) == {
        "instants": [], "intervals": [["2025-01-01", "2025-12-31"]]}
