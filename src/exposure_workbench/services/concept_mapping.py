"""XBRL concept -> normalized metric mapping (M2b), versioned.

Design rules (see MODULE_NOTES M2):
  * Many raw concepts MAY map to one normalized metric — but ONLY when they
    really are the same economic quantity tagged differently. V9-M1 found five
    metrics where they were not, and the corpus proved it: `LongTermDebt`
    INCLUDES current maturities while `LongTermDebtNoncurrent` excludes them
    (AAPL 2026-03-28: 74.404 + 8.310 = 82.714 ≈ 82.700), `ProfitLoss` includes
    noncontrolling interests and `NetIncomeLoss` does not, the two cash concepts
    differ by restricted cash, and `Revenues` is a superset of contract revenue.
    Those are NESTED quantities, and period_ladder._pick_latest resolves
    restatements rather than scopes — so which one reached the answer depended
    on filing order. 24 (issuer, metric) pairs were affected across 8 metrics;
    the worst disagreed by 17,596%.

    The damage was arithmetic, not cosmetic: total_debt = short + long
    double-counted AAPL's current maturities by 8.31B, with every input holding
    a real fact id. So: one metric names one quantity, and where two concepts
    are two quantities they get two names. tests/test_v9_concept_collisions_live
    watches the corpus for the next pair. Definitions and sources:
    docs/spikes/V9_FORMULA_BASIS.md §3.
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

MAPPING_VERSION = "v3"   # v3: split five metrics that were holding two quantities (V9-M1)

# normalized_metric -> the us-gaap concepts (without taxonomy prefix) that mean it
_METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    # Net revenue from customers. `Revenues` is NOT here: it is the total top
    # line and may carry non-contract income (measured: 5.2% apart on XOM), so
    # it is its own metric below. SalesRevenueNet is the pre-ASC-606 tag for the
    # same quantity as the 606 one, which is why those two may share a name.
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ),
    # The whole top line, including revenue that did not arise from contracts
    # with customers. A superset of `revenue`.
    "total_revenues": (
        "Revenues",
    ),
    # Gross of assessed (sales) taxes — a third quantity again. No issuer in the
    # corpus reports it today; it gets its own name anyway, because an unused
    # mapping that is wrong is still wrong the day somebody starts using it.
    "revenue_including_assessed_tax": (
        "RevenueFromContractWithCustomerIncludingAssessedTax",
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
    # Attributable to the parent. This is what "net income" means on the face of
    # the income statement and what EBIT/EBITDA start from (SEC C&DI 103.01).
    "net_income": (
        "NetIncomeLoss",
    ),
    # Including noncontrolling interests — a different number whenever there are
    # any. Measured: 97.5% apart on LLY.
    "net_income_including_noncontrolling": (
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
    # Unrestricted cash and equivalents — the cash a net-debt calculation may
    # net against debt.
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
    ),
    # The cash-flow-statement total, which includes restricted cash and so is
    # NOT available to repay debt. Measured: up to 9.9% apart on AAPL. JPM tags
    # only this one, so JPM has no cash_and_equivalents — correct, and visible.
    "cash_and_restricted_cash": (
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    # ── debt: five concepts, five quantities, and they nest ───────────────────
    # There is no `short_term_debt` or `long_term_debt` any more. Neither name
    # could say whether the current maturities were inside it, and that is
    # exactly what a total has to know. Composing a total is a CALCULATION and
    # belongs above this table — with a rule that picks a non-overlapping set.
    #
    #   long_term_debt_total = long_term_debt_noncurrent + current_portion_ltd
    #   debt_current_total  ⊇ current_portion_ltd, short_term_borrowings
    #
    # All term debt, current maturities INCLUDED.
    "long_term_debt_total": (
        "LongTermDebt",
    ),
    # Term debt due beyond twelve months. Excludes the current maturities.
    "long_term_debt_noncurrent": (
        "LongTermDebtNoncurrent",
    ),
    # The current maturities of long-term debt, on their own.
    "current_portion_long_term_debt": (
        "LongTermDebtCurrent",
    ),
    # Every debt the issuer classifies as current, whatever its origin.
    "debt_current_total": (
        "DebtCurrent",
    ),
    # Short-dated borrowings (commercial paper, revolver draws). A component of
    # debt_current_total, not a synonym for it: measured 50m vs 8.85bn apart on
    # AMZN when both were filed for the same date.
    "short_term_borrowings": (
        "ShortTermBorrowings",
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
