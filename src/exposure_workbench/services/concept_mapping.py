"""XBRL concept -> normalized metric mapping (M2b), versioned.

Design rules (see MODULE_NOTES M2):
  * Many raw concepts MAY map to one normalized metric (issuers tag the same
    economic quantity differently — e.g. NVDA uses us-gaap:Revenues while others
    use RevenueFromContractWithCustomerExcludingAssessedTax).
  * Mapping is strictly 1 fact -> 1 metric. NO aggregation here
    (total_debt = short + long is a CALCULATION and belongs to M3).
  * A concept that is not in this table is still persisted, with
    normalized_metric = NULL. Mapping status NEVER decides whether a fact is
    stored — raw stays faithful, normalization is an additive annotation.

Empirically grounded (measured against live EDGAR data):
  * NVDA has no PaymentsToAcquirePropertyPlantAndEquipment -> capex stays NULL
    for it; free cash flow is then unavailable, not guessed.
  * JPM (a bank) has no GrossProfit and no Revenues -> those metrics are simply
    absent. There is deliberately no industry special-casing.
"""

from __future__ import annotations

MAPPING_VERSION = "v2"   # v2: added cost_of_revenue + pretax_income as their own metrics

# normalized_metric -> the us-gaap concepts (without taxonomy prefix) that mean it
_METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ),
    "gross_profit": (
        "GrossProfit",
    ),
    # Cost of revenue is its own reported concept. It is NOT gross_profit — but it
    # lets M3 CALCULATE gross profit (revenue - cost_of_revenue) for the many
    # issuers that never tag GrossProfit (measured: AMZN/GOOGL/LLY/XOM/JPM).
    # Deriving it is M3's job; M2 stays strictly 1 fact -> 1 metric.
    "cost_of_revenue": (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ),
    "operating_income": (
        "OperatingIncomeLoss",
    ),
    # Pre-tax income is deliberately its OWN metric and is NOT folded into
    # operating_income. They are different economics (pre-tax income includes
    # non-operating items such as interest and other income). Mapping it onto
    # operating_income would make coverage *look* complete while silently
    # reporting a different quantity — precisely the kind of fallback this
    # architecture forbids. Issuers lacking OperatingIncomeLoss simply have no
    # operating_income, and that absence stays visible.
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "net_income": (
        "NetIncomeLoss",
        "ProfitLoss",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "capex": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "short_term_debt": (
        "LongTermDebtCurrent",
        "DebtCurrent",
        "ShortTermBorrowings",
    ),
    "long_term_debt": (
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ),
    "current_assets": (
        "AssetsCurrent",
    ),
    "current_liabilities": (
        "LiabilitiesCurrent",
    ),
}

# Inverted at import: concept -> metric. Guards against a concept being claimed
# by two metrics (that would make normalization order-dependent).
_CONCEPT_TO_METRIC: dict[str, str] = {}
for _metric, _concepts in _METRIC_CONCEPTS.items():
    for _c in _concepts:
        if _c in _CONCEPT_TO_METRIC:
            raise RuntimeError(
                f"concept {_c!r} mapped to both {_CONCEPT_TO_METRIC[_c]!r} and {_metric!r}"
            )
        _CONCEPT_TO_METRIC[_c] = _metric

SUPPORTED_METRICS: tuple[str, ...] = tuple(_METRIC_CONCEPTS)


def normalize_concept(raw_concept: str) -> str | None:
    """'us-gaap:Revenues' -> 'revenue'. Unknown/other taxonomies -> None."""
    if not raw_concept:
        return None
    taxonomy, _, tag = raw_concept.partition(":")
    if not tag:
        taxonomy, tag = "", raw_concept
    if taxonomy and taxonomy != "us-gaap":
        return None            # dei/srt/custom tags are stored but not normalized
    return _CONCEPT_TO_METRIC.get(tag)
