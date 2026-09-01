"""XBRL concept -> normalized metric mapping (M2b), versioned.

Design rules (see MODULE_NOTES M2):
  * Many raw concepts MAY map to one normalized metric — but ONLY when they
    really are the same economic quantity tagged differently. V9-M1 found five
    metrics where they were not, and the corpus proved it: `LongTermDebt`
    INCLUDES current maturities while `LongTermDebtNoncurrent` excludes them
    (AAPL 2026-03-28: 74.404 + 8.310 = 82.714 ≈ 82.700), `ProfitLoss` includes
    noncontrolling interests and `NetIncomeLoss` does not, the two cash concepts
    differ by restricted cash, and `Revenues` is a superset of contract revenue.
    Those are NESTED quantities, and the restatement rule (interval_algebra.restatement_key) resolves
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

MAPPING_VERSION = "v4"   # v4: per-share/capital-allocation layer (V16 Lane B); v3: V9-M1 splits

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
    # ── V9-M1b: the credit lines the corpus was already carrying ──────────────
    # Every one of these was stored with normalized_metric NULL since ingest —
    # mapping status never decided storage — so adding them is a backfill, not a
    # re-ingest. Issuer coverage measured on 2026-08-24 (8 issuers, consolidated
    # facts) is quoted per line: it is why each concept was chosen and, for the
    # ones that fall short, what bounds the metrics built on them.

    # Accrual interest expense. NOT InterestIncomeExpenseNet (a bank's net
    # interest income is revenue, not an expense — mapping it would show 8/8
    # coverage over two different economics) and NOT InterestExpenseNonoperating
    # (a component). 8/8.
    "interest_expense": (
        "InterestExpense",
    ),
    # Interest expense classified as non-operating. Its OWN metric, never folded
    # into interest_expense: they are nested by definition, and merging them
    # would produce a series that switches basis in 2024 — the NVDA revenue
    # situation, which V9-M1 split rather than merged.
    #
    # It exists because usage moved. `InterestExpense` stops in 2024 for 7 of the
    # 8 issuers held (only XOM runs to 2026) while this tag runs to 2026-06-30
    # for AMZN, GOOGL, LLY, MSFT and NVDA. Without it EBIT is uncomputable for a
    # recent window for almost every issuer here — measured, not assumed.
    "interest_expense_nonoperating": (
        "InterestExpenseNonoperating",
    ),
    # Cash interest actually paid, which is not the accrued charge. 5/8.
    "interest_paid": (
        "InterestPaidNet",
    ),
    # 8/8. With net_income and interest_expense this completes EBIT for every
    # issuer held — SEC C&DI 103.01 puts net income at the start of EBIT and
    # EBITDA, so the corpus supports the correctly-named measure rather than an
    # operating-income lookalike.
    "income_tax_expense": (
        "IncomeTaxExpenseBenefit",
    ),
    # The period's D&A charge. 5/8 — GOOGL, JPM and MSFT do not report it, and
    # that is what bounds EBITDA. Four other concepts in this corpus contain
    # "Depreciation" or "Amortization" and none of them is this: two are
    # ACCUMULATED balances, one is a five-year forward disclosure, and
    # DepreciationAndAmortization is filed by NVDA alongside this one. Mapping
    # any of them would raise coverage and destroy the number.
    "depreciation_amortization": (
        "DepreciationDepletionAndAmortization",
    ),
    # Depreciation alone (6/8) and intangible amortization alone (6/8). They are
    # NOT summed into D&A here: their sum is not guaranteed to be the issuer's
    # reported D&A, and a number carrying that name has to be that number. They
    # are mapped so an absence can say what the issuer does report instead.
    "depreciation": (
        "Depreciation",
    ),
    "amortization_of_intangibles": (
        "AmortizationOfIntangibleAssets",
    ),

    # Balance sheet. 8/8, 6/8, 8/8.
    "total_assets": (
        "Assets",
    ),
    "total_liabilities": (
        "Liabilities",
    ),
    # Attributable to the parent. The including-NCI version is a different
    # quantity and gets its own name, for the same reason NetIncomeLoss and
    # ProfitLoss do (V9-M1). 8/8 and 2/8.
    "stockholders_equity": (
        "StockholdersEquity",
    ),
    "stockholders_equity_including_noncontrolling": (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "noncontrolling_interest": (
        "MinorityInterest",
    ),

    # Working capital. 7/8, 6/8, 6/8.
    "accounts_receivable": (
        "AccountsReceivableNetCurrent",
    ),
    "inventory": (
        "InventoryNet",
    ),
    "accounts_payable": (
        "AccountsPayableCurrent",
    ),

    # Commercial paper (6/8) — short-dated debt outside the term structure, and
    # a component of debt_current_total rather than a synonym for it.
    "commercial_paper": (
        "CommercialPaper",
    ),

    # Operating lease liabilities nest exactly as term debt does: measured on
    # MSFT at 2026-03-31, the total is 22.238bn against 16.703bn noncurrent. So
    # three names, and a caller that wants the total asks for the total. 8/8,
    # 6/8, 7/8.
    "operating_lease_liability_total": (
        "OperatingLeaseLiability",
    ),
    "operating_lease_liability_current": (
        "OperatingLeaseLiabilityCurrent",
    ),
    "operating_lease_liability_noncurrent": (
        "OperatingLeaseLiabilityNoncurrent",
    ),

    "current_assets": (
        "AssetsCurrent",
    ),
    "current_liabilities": (
        "LiabilitiesCurrent",
    ),

    # ── V16 Lane B: the per-share and capital-allocation layer ────────────────
    # Corpus verified before mapping (V11 rule), 2026-09-01: every concept below
    # carries exactly ONE unit string ("USD per share" for EPS, "shares" for the
    # three counts, "USD" for the cash flows) and exactly ONE period shape — EPS,
    # the weighted counts and the cash flows are all durations; the outstanding
    # count is instant-only. No mixed-shape concept was found.

    # Per-share earnings as the issuer computed them. Diluted and basic are two
    # quantities by construction — different denominators — so two names.
    # Neither is derivable here from net_income and a share count: the issuer's
    # own division handles participating securities and the treasury stock
    # method, and recomputing it is a CALCULATION (M3), not a mapping. 8/8 each.
    "eps_diluted": (
        "EarningsPerShareDiluted",
    ),
    "eps_basic": (
        "EarningsPerShareBasic",
    ),

    # ── share counts: three concepts, three quantities ────────────────────────
    # The weighted averages are DURATIONS — ASC 260's EPS denominators, the
    # average count over a period — while CommonStockSharesOutstanding is an
    # INSTANT, the count on one date. Same word "shares", three numbers; the
    # corpus shows the shapes directly (weighted rows all carry a period_start,
    # outstanding rows never do), so mapping any two onto one name would merge a
    # flow denominator with a stock denominator. 7/8, 8/8, 7/8.
    #
    # dei:EntityCommonStockSharesOutstanding (the cover-page count, 157 rows) is
    # deliberately NOT here: normalize_concept normalizes us-gaap only, and
    # widening that rule is its own decision, not a side effect of this batch.
    "shares_diluted_weighted": (
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ),
    "shares_basic_weighted": (
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ),
    "shares_outstanding": (
        "CommonStockSharesOutstanding",
    ),

    # ── capital returns and the SBC add-back ──────────────────────────────────
    # Cash paid to repurchase common stock — the financing outflow, which is not
    # the change in the share count (timing and treasury reissuance sit between
    # them; the count has its own metrics above). 8/8.
    "buybacks": (
        "PaymentsForRepurchaseOfCommonStock",
    ),
    # Cash dividends paid. Two tags, ONE metric — and this time the corpus
    # supports the merge where it refused the V9 ones: each issuer files exactly
    # one of the two (five file PaymentsOfDividends, two file the CommonStock
    # variant; zero overlap in issuers, so zero overlap in periods), so no
    # series can switch basis and no last-filed-wins is possible. The residual
    # semantic gap — the broader tag may include preferred/NCI dividends where
    # the variant is common-only — is stated in semantics.METRICS, not hidden.
    "dividends_paid": (
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ),
    # Non-cash share-based compensation expense, the cash-flow add-back. 7/8.
    "sbc": (
        "ShareBasedCompensation",
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
