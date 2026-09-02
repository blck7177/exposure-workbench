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
from exposure_workbench.analytics import units
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


# ── V12-S0: what the registry may hand a model ───────────────────────────────

def test_no_note_carries_a_figure():
    """A note is a rule, not a measurement.

    Measured (V12 §10): `evaluate_formula` ships `note` on every call — 42 times
    in two days — and two notes carried other issuers' figures (138.753bn /
    40.770bn on GOOGL, 8.31bn on AAPL). Relaying one is refused, because nothing
    the caller cited holds it, and the refusal reads as the model's fault. The
    consequence sentence is what does the work; the measurements live in
    docs/spikes/V9_FORMULA_BASIS.md, for the people who read code.
    """
    import re
    figure = re.compile(r"\d[\d.,]*\s*(?:%|bn\b|billion|million|trillion|trn\b)", re.IGNORECASE)
    offenders = {name: figure.findall(f.note) for name, f in fm.FORMULAS.items()
                 if f.note and figure.findall(f.note)}
    assert not offenders, offenders


def test_every_formula_says_what_it_may_be_cited_as():
    """The url alone could not be spoken: handed it, the model built
    `src_https://www.sec.gov/...` and the gate refused the answer."""
    for name, f in fm.FORMULAS.items():
        auth = fm.authority(f)
        assert auth["url"].startswith("https://"), name
        assert auth["cite_as"], name
        assert "http" not in auth["cite_as"], f"{name}: cite_as is a name, not a link"
        assert set(auth) == {"cite_as", "url"}, f"{name}: no flat id-shaped value"


def test_every_formula_belongs_to_a_family():
    """"More leveraged" is a question about a ratio; a dollar amount of debt is
    not one. The family is what lets a comparison pick a commensurable measure."""
    known = {"earnings", "cash", "leverage", "coverage", "liquidity", "margin",
             "turnover",
             # V16 Tier 1: returns on capital, reinvestment intensity, and
             # earnings quality are questions none of the pre-V16 families ask.
             "returns", "reinvestment", "quality"}
    for name, f in fm.FORMULAS.items():
        assert f.family in known, f"{name}: {f.family!r}"


# ── V17: which dimensionless measures are read as multiples ──────────────────
#
# Nineteen of the registry's measures are money ÷ money. Eleven are shares of a
# whole and read as percents; eight are coverages, turnovers and leverage
# ratios, and reading THOSE as percents is what put "230.0%" on a debt/EBITDA
# of 2.3 and "185.0%" on a current ratio of 1.85. The algebra cannot tell the
# two groups apart (test_unit_algebra §d), so the registry names them here and
# the list is the claim.

MULTIPLES = {"ebit_interest_coverage", "debt_to_ebitda", "debt_to_operating_cash_flow",
             "net_debt_to_ebitda", "current_ratio", "quick_ratio",
             "asset_turnover", "equity_multiplier"}


def test_the_measures_read_as_multiples_are_exactly_the_declared_eight():
    declared = {n for n, f in fm.FORMULAS.items() if f.unit_class == "multiple"}
    assert declared == MULTIPLES


@pytest.mark.parametrize("name", sorted(MULTIPLES))
def test_a_multiple_is_a_quotient_the_evaluator_can_actually_declare(name):
    """The declaration is checked at evaluation by units.refine, so a measure
    declaring `multiple` on anything but a dimensionless quotient would refuse
    itself at runtime rather than here."""
    f = fm.FORMULAS[name]
    assert f.op == "divide", f"{name} declares multiple but is a {f.op}"
    assert units.refine(units.RATIO, f.unit_class) == units.MULTIPLE


PERCENTS = {"gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic",
            "tax_burden", "fcf_margin", "capex_intensity", "accruals_ratio",
            "fcf_to_debt"}


def test_every_dimensionless_measure_is_named_in_exactly_one_of_the_two_lists():
    """No heuristic decides this — a name is not evidence (fcf_to_debt says
    "to" and is a percent, the way the agencies report it). Every measure that
    comes out dimensionless is written down as a share or as a multiple, and a
    new one fails here until someone decides which it is."""
    dimensionless = {n for n, f in fm.FORMULAS.items()
                     if f.unit_class in ("ratio", "multiple")}
    assert MULTIPLES | PERCENTS == dimensionless
    assert not (MULTIPLES & PERCENTS)


@pytest.mark.parametrize("name", sorted(PERCENTS))
def test_a_share_of_a_whole_stays_a_percent(name):
    """Turning one of these into a multiple would print "0.25×" for a margin."""
    assert fm.FORMULAS[name].unit_class == "ratio", name
