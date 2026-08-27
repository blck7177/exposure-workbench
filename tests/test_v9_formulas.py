"""V9-D — method definitions are data, with sources (offline).

A ratio without its definition is not checkable. "Leverage 2.1x" says nothing
until you know whether the debt is gross or net and whether the earnings are
reported or adjusted — and the SEC says so outright about free cash flow: the
measure "does not have a uniform definition and its title does not describe how
it is calculated" (C&DI 102.07), so the calculation must travel with it.

Hence a registry rather than functions: a formula is a name, an expression over
metrics the corpus actually has, and the authority for defining it that way.
Adding one is an edit to data. What the registry may NOT hold is a threshold —
no healthy, no risky, no band — because this system lays out evidence and the
reading belongs to the user (2026-08-24).
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.services.concept_mapping import SUPPORTED_METRICS


def test_ebit_starts_from_net_income_because_the_sec_says_earnings_means_net_income():
    """C&DI 103.01: "Earnings" means net income as presented under GAAP, and
    measures calculated differently "should not be characterized as EBIT or
    EBITDA". The draft panel had operating income plus D&A under the EBITDA
    name, which is the mislabel the regulator names."""
    f = fm.FORMULAS["ebit"]
    assert set(f.inputs) == {"net_income", "interest_expense", "income_tax_expense"}
    assert "103.01" in f.source_quote or "103.01" in f.note
    assert "operating_income" not in f.expression


def test_ebitda_builds_on_ebit_not_on_operating_income():
    assert set(fm.FORMULAS["ebitda"].inputs) == {"ebit", "depreciation_amortization"}


def test_free_cash_flow_carries_the_reason_it_must_carry_its_formula():
    f = fm.FORMULAS["free_cash_flow"]
    assert set(f.inputs) == {"operating_cash_flow", "capex"}
    assert "does not have a uniform definition" in f.source_quote


def test_net_debt_says_it_is_not_the_agency_measure():
    """S&P nets surplus cash with haircuts we cannot compute. A number carrying
    that name without those inputs would be the well-formed error again."""
    f = fm.FORMULAS["net_debt"]
    assert "not" in f.note.lower() and ("agency" in f.note.lower() or "S&P" in f.note)


@pytest.mark.parametrize("name", sorted(fm.FORMULAS))
def test_every_formula_cites_something(name):
    f = fm.FORMULAS[name]
    assert f.source_url.startswith("http"), f"{name} has no source"
    assert f.source_quote or f.note, f"{name} cites a URL but says nothing about it"


@pytest.mark.parametrize("name", sorted(fm.FORMULAS))
def test_every_input_is_a_metric_or_another_formula(name):
    """An expression over something that does not exist is a formula that can
    only ever fail, and it would fail at the user rather than at import."""
    for i in fm.FORMULAS[name].inputs:
        assert i in SUPPORTED_METRICS or i in fm.FORMULAS, f"{name}: unknown input {i}"


@pytest.mark.parametrize("name", sorted(fm.FORMULAS))
def test_no_formula_carries_a_threshold(name):
    """The product decision, enforced. A band is a judgement, and judgements are
    the reader's."""
    f = fm.FORMULAS[name]
    for banned in ("threshold", "healthy", "risky", "warning", "band", "good", "bad"):
        assert not hasattr(f, banned), f"{name} carries {banned}"
        assert banned not in f.note.lower(), f"{name}'s note reads as a judgement"


def test_the_dependency_order_is_computable_and_acyclic():
    order = fm.evaluation_order()
    seen: set[str] = set()
    for name in order:
        for i in fm.FORMULAS[name].inputs:
            if i in fm.FORMULAS:
                assert i in seen, f"{name} evaluated before its input {i}"
        seen.add(name)
    assert set(order) == set(fm.FORMULAS)


def test_a_formula_states_whether_it_wants_a_balance_or_a_window():
    """debt ÷ EBITDA is a stock over a flow, and the evaluator has to know which
    side is which before it can fetch anything."""
    for name, f in fm.FORMULAS.items():
        assert f.basis in ("instant", "window", "mixed"), f"{name}: {f.basis}"
