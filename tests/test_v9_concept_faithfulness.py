"""V9-M1 — one metric is one economic quantity (offline).

The mapping table's premise, written in its own docstring, is that "many raw
concepts MAY map to one normalized metric" because "issuers tag the same
economic quantity differently". That is true of revenue synonyms. It is false
of debt, and the corpus proves it:

  AAPL, 2026-03-28, consolidated, USD billions
    LongTermDebtNoncurrent   74.404
    LongTermDebtCurrent    +  8.310
                           = 82.714
    LongTermDebt             82.700   <- the same total, within the discount convention

So `LongTermDebt` INCLUDES current maturities and `LongTermDebtNoncurrent`
excludes them: nested quantities, not synonyms. Both mapped to `long_term_debt`,
and the restatement rule resolves restatements rather than scopes, so the
winner was whichever was filed last. Measured across the live corpus, 24
(issuer, metric) pairs collided over 8 metrics and the worst disagreed by
17,596%.

The damage is not the label. `total_debt = short + long` computes 82.700 + 8.310
= 91.010 for AAPL, double-counting the current maturities by 8.31B — with every
input carrying a real fact id and every step a real calc id. A well-formed
error, which is the one shape the citation gate cannot catch.

Sources for the definitions: docs/spikes/V9_FORMULA_BASIS.md §3.
"""

from __future__ import annotations

import pytest

from exposure_workbench.services import concept_mapping as cm


# ── the five metrics the corpus proved ambiguous ──────────────────────────────

@pytest.mark.parametrize("gone", ["long_term_debt", "short_term_debt"])
def test_the_ambiguous_debt_names_are_gone(gone):
    """Neither name says whether current maturities are in it, and a name that
    cannot answer that question is the defect — not the concept behind it."""
    assert gone not in cm.SUPPORTED_METRICS


@pytest.mark.parametrize("metric, concept", [
    ("long_term_debt_total", "LongTermDebt"),
    ("long_term_debt_noncurrent", "LongTermDebtNoncurrent"),
    ("current_portion_long_term_debt", "LongTermDebtCurrent"),
    ("debt_current_total", "DebtCurrent"),
    ("short_term_borrowings", "ShortTermBorrowings"),
    ("net_income", "NetIncomeLoss"),
    ("net_income_including_noncontrolling", "ProfitLoss"),
    ("cash_and_equivalents", "CashAndCashEquivalentsAtCarryingValue"),
    ("cash_and_restricted_cash", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    ("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ("total_revenues", "Revenues"),
])
def test_each_quantity_has_its_own_name(metric, concept):
    assert cm.normalize_concept(f"us-gaap:{concept}") == metric


@pytest.mark.parametrize("metric", [
    "long_term_debt_total", "long_term_debt_noncurrent",
    "current_portion_long_term_debt", "debt_current_total", "short_term_borrowings",
    "net_income", "net_income_including_noncontrolling",
    "cash_and_equivalents", "cash_and_restricted_cash",
    "total_revenues",
])
def test_a_split_metric_accepts_exactly_one_concept(metric):
    """The point of the split. Two concepts under one of these names would put
    the ambiguity straight back, and the next reader would have no way to see it
    — the values only disagree for some issuers in some periods."""
    concepts = cm._METRIC_CONCEPTS[metric]
    assert len(concepts) == 1, f"{metric} accepts {len(concepts)} concepts: {concepts}"


def test_revenue_keeps_only_the_net_of_tax_family():
    """`Revenues` is the total top line and may include non-contract income;
    contract revenue is a subset of it (measured: they differ by 5.2% on XOM).
    Gross-of-assessed-tax revenue is a third quantity again and gets its own
    name rather than being folded in, even though no issuer here reports it —
    an unused mapping that is wrong is still wrong when someone starts using
    it."""
    assert set(cm._METRIC_CONCEPTS["revenue"]) == {
        "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
    }
    assert cm.normalize_concept("us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax") \
        == "revenue_including_assessed_tax"


def test_the_version_moved():
    """Facts carry mapping_version, and a remap that does not change it leaves
    no way to tell which reading produced a stored row."""
    assert cm.MAPPING_VERSION == "v3"


# ── the detector for everything this batch did NOT split ──────────────────────

def test_the_unsplit_multi_concept_metrics_are_named_and_few():
    """Five metrics still accept more than one concept, because the corpus has
    not shown them disagreeing — every issuer that reports two of them reports
    the same number. Each pair is nonetheless nested by definition:

      revenue             ASC-606 revenue vs the pre-606 tag for the same thing
      pretax_income       with and without equity-method income
      cost_of_revenue     CostOfRevenue is broader than CostOfGoodsAndServicesSold
      operating_cash_flow total vs continuing operations only
      capex               PP&E purchases vs productive assets (broader)

    So this is a bounded bet, not a clean bill. What makes it allowable is
    test_no_metric_is_two_quantities_in_the_live_corpus, which goes red the day
    real data disagrees. This test exists so the list of outstanding bets cannot
    grow by one without somebody noticing — it caught its own author leaving
    operating_cash_flow and capex off the list.
    """
    multi = {m for m, cs in cm._METRIC_CONCEPTS.items() if len(cs) > 1}
    assert multi == {"revenue", "pretax_income", "cost_of_revenue",
                     "operating_cash_flow", "capex"}, (
        f"a metric grew or lost a second concept without a decision: {sorted(multi)}"
    )


# ── V9-M1b: the credit metrics the corpus was already carrying ────────────────

@pytest.mark.parametrize("metric, concept, cos", [
    # flows
    ("interest_expense", "InterestExpense", 8),
    # Its own name rather than merged into interest_expense: nested by
    # definition, and merging would switch the series' basis in 2024. Mapped at
    # all because usage moved — InterestExpense stops in 2024 for 7 of 8 issuers
    # and this runs to 2026-06-30 for five of them.
    ("interest_expense_nonoperating", "InterestExpenseNonoperating", 5),
    ("income_tax_expense", "IncomeTaxExpenseBenefit", 8),
    ("depreciation_amortization", "DepreciationDepletionAndAmortization", 5),
    ("depreciation", "Depreciation", 6),
    ("amortization_of_intangibles", "AmortizationOfIntangibleAssets", 6),
    ("interest_paid", "InterestPaidNet", 5),
    # balances
    ("total_assets", "Assets", 8),
    ("total_liabilities", "Liabilities", 6),
    ("stockholders_equity", "StockholdersEquity", 8),
    ("stockholders_equity_including_noncontrolling",
     "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", 2),
    ("noncontrolling_interest", "MinorityInterest", 2),
    ("accounts_receivable", "AccountsReceivableNetCurrent", 7),
    ("inventory", "InventoryNet", 6),
    ("accounts_payable", "AccountsPayableCurrent", 6),
    ("commercial_paper", "CommercialPaper", 6),
    ("operating_lease_liability_total", "OperatingLeaseLiability", 8),
    ("operating_lease_liability_current", "OperatingLeaseLiabilityCurrent", 6),
    ("operating_lease_liability_noncurrent", "OperatingLeaseLiabilityNoncurrent", 7),
])
def test_the_credit_metrics_map(metric, concept, cos):
    """`cos` is the measured issuer coverage in this corpus on 2026-08-24, kept
    in the parameter list so the number a decision was made on stays next to
    the decision."""
    assert cm.normalize_concept(f"us-gaap:{concept}") == metric
    assert len(cm._METRIC_CONCEPTS[metric]) == 1


def test_ebit_has_every_input_it_needs():
    """SEC C&DI 103.01: EBIT and EBITDA start from NET INCOME, not operating
    income — "measures that are calculated differently ... should not be
    characterized as EBIT or EBITDA". All three inputs are mapped and all three
    are 8/8 in this corpus, so EBIT is computable for every issuer held.
    EBITDA adds D&A, which is 5/8, and that is what bounds it.
    See docs/spikes/V9_FORMULA_BASIS.md §1."""
    for m in ("net_income", "interest_expense", "income_tax_expense"):
        assert m in cm.SUPPORTED_METRICS
    assert "depreciation_amortization" in cm.SUPPORTED_METRICS


@pytest.mark.parametrize("wrong_concept, why", [
    ("InterestIncomeExpenseNet",
     "a bank's net interest income is revenue, not an interest expense"),
    ("AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
     "an accumulated balance, not the period's charge"),
    ("FiniteLivedIntangibleAssetsAmortizationExpenseNextTwelveMonths",
     "a forward-looking disclosure, not an incurred expense"),
    ("FiniteLivedIntangibleAssetsAccumulatedAmortization",
     "an accumulated balance again"),
    ("DepreciationAndAmortization",
     "NVDA reports it alongside DepreciationDepletionAndAmortization, so mapping "
     "both to one metric would give one issuer two values for one period"),
])
def test_the_lookalikes_stay_unmapped(wrong_concept, why):
    """Four different things in this corpus contain the word Depreciation or
    Amortization and only one of them is the period's D&A charge. Coverage is
    the temptation — mapping the accumulated balance would take D&A from 5/8 to
    8/8 and every number after it would be wrong by an order of magnitude."""
    assert cm.normalize_concept(f"us-gaap:{wrong_concept}") is None, why
