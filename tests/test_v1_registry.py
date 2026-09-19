"""V1 step 2 (docs/IMPLEMENTATION_PLAN_V1.md §2.5, §3 步骤 2): one entry, three faces.

A measure is written once, in analytics/registry: the handbook renders what it
is and how it reads, a `metric` tool takes its name, and the fact it births
carries its words. These tests pin the entry's new fields and that the old
reader (analytics/skill) reads the very same objects.
"""

from __future__ import annotations

import pytest

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import registry as R
from exposure_workbench.analytics import skill
from exposure_workbench.services import compute_service
from exposure_workbench.services import fact_adapters as FA
from exposure_workbench.services import facts as F


def test_the_skill_module_reads_the_registrys_own_objects():
    assert skill.METHODS is R.METHODS and skill.READINGS is R.READINGS
    assert skill.Method is R.Method and skill.EXECUTORS is R.EXECUTORS


def test_every_measure_has_a_financial_name_and_valid_words():
    for name, m in R.METHODS.items():
        assert m.reads_as.strip(), name
        assert "_" not in m.reads_as, f"{name}: a financial name is words, not a key ({m.reads_as!r})"
        assert set(m.basis) <= set(R.BASIS) and set(m.faces) <= set(R.FACES), name


def test_every_formula_is_the_issuer_analysts_and_every_executor_is_dispatched():
    issuer = {m.name for m in R.metrics_for("issuer")}
    assert set(fm.FORMULAS) <= issuer and "issuer.panel" in issuer
    assert set(compute_service.executors_dispatched()) == set(R.EXECUTORS)


def test_the_faces_follow_the_resource_families():
    market = {m.name for m in R.metrics_for("market")}
    risk = {m.name for m in R.metrics_for("risk")}
    assert market == {n for n in R.METHODS if n.startswith("price.")}
    # the risk manager asks for a name's beta, volatility and volume BY NAME — it
    # never reads the price table — and owns every derivation of the book
    assert {"price.beta", "price.volatility", "price.adv"} <= risk
    assert {"book.analysis", "book.reconcile", "book.drawdown_episodes", "book.explain_episode"} <= risk
    assert not any(n.startswith("price.") for n in risk - {"price.beta", "price.volatility", "price.adv"})
    # a scenario is an action with its own verb, never a measure asked by name
    assert all(not R.METHODS[n].faces for n in ("book.sell", "book.buy"))
    with pytest.raises(ValueError):
        R.metrics_for("trader")


def test_an_entry_refuses_words_outside_the_vocabulary():
    base = dict(name="x.y", subject_kind="price", family="risk", describes="d", procedure="p",
                authority="a", fails_when="f", executor="price.beta")
    with pytest.raises(ValueError):
        R.Method(**base, basis=("guess",))
    with pytest.raises(ValueError):
        R.Method(**base, faces=("trader",))


def test_a_methods_facts_carry_what_it_is_built_on():
    res = {"method": "days_sales_outstanding", "subject": "MSFT", "formula": "days_sales_outstanding",
           "ticker": "MSFT", "value": 78.4, "calc_id": "calc_1", "unit_class": "count", "as_of": "2025-06-30",
           "periods": {"intervals": [["2024-07-01", "2025-06-30"]]}}
    (fact, *_), _note = FA.compute({"method": "days_sales_outstanding", "subject": "MSFT"}, res)
    assert fact.means == {"basis": ["ending_balance"]}
    assert F.line(fact).split(" — ")[1] == "built on ending balances"


def test_a_substituted_line_is_on_the_fact_a_method_births():
    res = {"method": "ebit_interest_coverage", "subject": "XOM", "formula": "ebit_interest_coverage",
           "ticker": "XOM", "value": 18.4, "calc_id": "calc_2", "unit_class": "multiple",
           "periods": {"intervals": [["2024-07-01", "2025-06-30"]]},
           "substituted_inputs": {"interest_expense": "interest_expense_nonoperating"}}
    (fact, *_), _note = FA.compute({"method": "ebit_interest_coverage", "subject": "XOM"}, res)
    assert fact.params["substituted"] == {"interest_expense": "interest_expense_nonoperating"}
    assert "in place of interest expense" in F.line(fact)


def test_a_measures_name_on_a_row_is_its_entrys():
    assert R.reads_as("price.beta") == "beta to a benchmark"
    assert R.reads_as("ebit_interest_coverage") == "EBIT / interest coverage"
