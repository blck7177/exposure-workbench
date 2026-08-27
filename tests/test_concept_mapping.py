"""M2b concept mapping + fact row building (offline)."""

from __future__ import annotations

from datetime import date

from exposure_workbench.providers.filing_provider import FactDTO
from exposure_workbench.services import concept_mapping as cm
from exposure_workbench.services import filing_ingestion_service as fis


def test_many_concepts_map_to_one_metric_only_when_they_are_one_quantity():
    """The rule this test used to state was "many concepts map to one metric",
    with `Revenues` and `RevenueFromContractWithCustomerExcludingAssessedTax` as
    the example. V9-M1 found that example to be the counter-example: `Revenues`
    is the whole top line and contract revenue is a subset of it, measured 5.2%
    apart on XOM, and mapping both to `revenue` let the series serve
    whichever was filed last.

    The rule survives with its condition made explicit. SalesRevenueNet is the
    pre-ASC-606 tag for the same quantity as the 606 one, so those two really
    are one metric; `Revenues` is its own."""
    assert cm.normalize_concept("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax") == "revenue"
    assert cm.normalize_concept("us-gaap:SalesRevenueNet") == "revenue"
    assert cm.normalize_concept("us-gaap:Revenues") == "total_revenues"


def test_unmapped_and_foreign_taxonomy_return_none():
    # unknown us-gaap tag -> None (but the fact is still persisted, see below)
    assert cm.normalize_concept("us-gaap:SomeConceptWeDoNotMap") is None
    # dei/custom taxonomies are stored but never normalized
    assert cm.normalize_concept("dei:EntityCommonStockSharesOutstanding") is None
    assert cm.normalize_concept("") is None


def test_pretax_income_is_not_conflated_with_operating_income():
    """Regression guard for a deliberate design decision.

    Several issuers (JPM/XOM/LLY/AMZN/GOOGL) never tag OperatingIncomeLoss. It is
    tempting to map IncomeLossFromContinuingOperationsBeforeIncomeTaxes... onto
    operating_income to 'fill' coverage — but that is a different economic
    quantity (it includes non-operating items). Coverage must stay honestly
    absent rather than silently wrong.
    """
    pretax = "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
    assert cm.normalize_concept(pretax) == "pretax_income"
    assert cm.normalize_concept(pretax) != "operating_income"
    assert cm.normalize_concept("us-gaap:OperatingIncomeLoss") == "operating_income"


def test_cost_of_revenue_is_its_own_metric_not_gross_profit():
    """gross_profit = revenue - cost_of_revenue is a CALCULATION (M3), never a mapping."""
    assert cm.normalize_concept("us-gaap:CostOfRevenue") == "cost_of_revenue"
    assert cm.normalize_concept("us-gaap:CostOfGoodsAndServicesSold") == "cost_of_revenue"
    assert cm.normalize_concept("us-gaap:GrossProfit") == "gross_profit"


def test_no_concept_claimed_by_two_metrics():
    # import-time guard already enforces this; assert the inverted map is consistent
    for metric, concepts in cm._METRIC_CONCEPTS.items():
        for c in concepts:
            assert cm._CONCEPT_TO_METRIC[c] == metric


def _fact(concept, value=1.0, acc="0000-1", period="2026-01-25") -> FactDTO:
    return FactDTO(raw_concept=concept, value=value, period_end=date.fromisoformat(period),
                   source_accession=acc, unit="USD")


def test_unmapped_facts_are_still_persisted_with_null_metric():
    rows = fis.build_fact_rows([_fact("us-gaap:TotallyUnknownTag")], "co_x", "edgartools")
    assert len(rows) == 1                          # kept, not dropped
    assert rows[0]["normalized_metric"] is None    # normalization is additive only
    assert rows[0]["raw_concept"] == "us-gaap:TotallyUnknownTag"   # raw stays faithful


def test_restatement_from_a_different_accession_is_a_separate_row():
    same_period = [_fact("us-gaap:Revenues", 100.0, acc="0000-1"),
                   _fact("us-gaap:Revenues", 111.0, acc="0000-2")]   # restated later
    rows = fis._dedupe_rows(fis.build_fact_rows(same_period, "co_x", "edgartools"))
    assert len(rows) == 2, "restatements must append, not collapse"


def test_same_accession_duplicate_collapses_within_batch():
    dupes = [_fact("us-gaap:Revenues", 100.0, acc="0000-1"),
             _fact("us-gaap:Revenues", 100.0, acc="0000-1")]
    rows = fis._dedupe_rows(fis.build_fact_rows(dupes, "co_x", "edgartools"))
    assert len(rows) == 1


def test_dimensions_hash_stable_and_distinct():
    assert fis.dimensions_hash(None) == ""
    assert fis.dimensions_hash({"a": 1, "b": 2}) == fis.dimensions_hash({"b": 2, "a": 1})
    assert fis.dimensions_hash({"a": 1}) != fis.dimensions_hash({"a": 2})
