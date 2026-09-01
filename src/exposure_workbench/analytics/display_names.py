"""What things are called when a person reads them (V13-S3/S4).

WHY THIS IS ONE FILE. The canonical names in this system are identifiers: they
are stable, they join across four tables, and the agent reasons about them. They
are also what the page was rendering, so a visitor met `operating_lease_liability_noncurrent`
in a chip, `cash_to_long_term_debt_noncurrent` in a table row and `market_downside`
inside a sentence. Every one of those is correct and none of them is English.

The fix is a table, not a formatter. `revenue` -> "Revenue" is what a
`.replace("_", " ").title()` would give and it is right; `capex` -> "Capital
expenditure", `commercial_paper` -> "Commercial paper" (not "Commercial Paper"),
`operating_cash_flow` -> "Cash from operations" and `pretax_income` -> "Pre-tax
income" are not. A formatter that is right most of the time is worse than a table
here, because the cases it gets wrong are the ones a reader stops on.

WHAT IS NOT HERE. Nothing that carries meaning beyond the name. The semantics —
which metric supersedes which, what may not be added to what — belong to
analytics/semantics.py and are the agent's; these are captions.

THE GUARD. tests/test_display_names.py derives the required key sets from their
sources — concept_mapping.SUPPORTED_METRICS, the recipe's own labels,
factor_config.yaml, stress_scenarios.yaml, limits.LIMIT_SPECS — so adding a
metric without a caption fails the build rather than reaching a page as an
identifier. That is the whole reason this is data and not scattered strings.
"""

from __future__ import annotations

# ── financial metrics (concept_mapping.SUPPORTED_METRICS) ────────────────────
#
# House style, applied consistently: sentence case, no title case; "Cash from
# operations" over "Operating cash flow" because that is what the statement is
# called; the current/non-current split spelled out rather than abbreviated,
# because that distinction is exactly the one this desk refuses to let anyone
# blur (adding a total to a component it contains is the double count the typed
# calculator refuses).
METRIC: dict[str, str] = {
    "revenue": "Revenue",
    "total_revenues": "Total revenues",
    "revenue_including_assessed_tax": "Revenue, including assessed tax",
    "gross_profit": "Gross profit",
    "cost_of_revenue": "Cost of revenue",
    "operating_income": "Operating income",
    "pretax_income": "Pre-tax income",
    "net_income": "Net income",
    "net_income_including_noncontrolling": "Net income, including non-controlling interests",
    "operating_cash_flow": "Cash from operations",
    "capex": "Capital expenditure",
    "cash_and_equivalents": "Cash and equivalents",
    "cash_and_restricted_cash": "Cash, equivalents and restricted cash",
    "long_term_debt_total": "Long-term debt, total",
    "long_term_debt_noncurrent": "Long-term debt, non-current portion",
    "current_portion_long_term_debt": "Long-term debt, current portion",
    "debt_current_total": "Current debt, total",
    "short_term_borrowings": "Short-term borrowings",
    "interest_expense": "Interest expense",
    "interest_expense_nonoperating": "Interest expense, non-operating",
    "interest_paid": "Interest paid in cash",
    "income_tax_expense": "Income tax expense",
    "depreciation_amortization": "Depreciation and amortisation",
    "depreciation": "Depreciation",
    "amortization_of_intangibles": "Amortisation of intangibles",
    "total_assets": "Total assets",
    "total_liabilities": "Total liabilities",
    "stockholders_equity": "Shareholders' equity",
    "stockholders_equity_including_noncontrolling": "Shareholders' equity, including non-controlling interests",
    "noncontrolling_interest": "Non-controlling interests",
    "accounts_receivable": "Accounts receivable",
    "inventory": "Inventory",
    "accounts_payable": "Accounts payable",
    "commercial_paper": "Commercial paper",
    "operating_lease_liability_total": "Operating lease liabilities, total",
    "operating_lease_liability_current": "Operating lease liabilities, current",
    "operating_lease_liability_noncurrent": "Operating lease liabilities, non-current",
    "current_assets": "Current assets",
    "current_liabilities": "Current liabilities",
    # V16 — the per-share and capital-allocation layer (mapping v4). Three share
    # counts, three captions that keep the distinction audible: weighted counts
    # are EPS denominators over a period, outstanding is a point-in-time count.
    "eps_diluted": "Earnings per share, diluted",
    "eps_basic": "Earnings per share, basic",
    "shares_diluted_weighted": "Weighted average shares, diluted",
    "shares_basic_weighted": "Weighted average shares, basic",
    "shares_outstanding": "Shares outstanding",
    "buybacks": "Share repurchases",
    "dividends_paid": "Dividends paid",
    "sbc": "Share-based compensation",
}

# ── regression factors (configs/factor_config.yaml) ──────────────────────────
FACTOR: dict[str, str] = {
    "market": "Market",
    "growth": "Growth",
    "small_cap": "Small cap",
    "rates": "Rates",
    "credit": "Credit",
    "gold": "Gold",
    "oil": "Oil",
    "volatility": "Volatility",
}

# ── stress scenarios (configs/stress_scenarios.yaml) ─────────────────────────
#
# Each says what is shocked, because "market downside" alone does not say by how
# much and the number is what makes the loss beside it mean anything.
SCENARIO: dict[str, str] = {
    "tech_selloff": "Technology sell-off",
    "rates_shock_up": "Rates up 50bp",
    "credit_spread_widening": "Credit spreads +200bp",
    "market_downside": "Market down 10%",
    "energy_shock": "Oil down 20%",
}

# ── mandate checks (analytics.limits.LIMIT_SPECS) ────────────────────────────
#
# Named as the desk speaks about them. `daily_loss` is the loss in one session,
# not a rate; `gross_exposure` is a share of NAV and reads as one.
LIMIT: dict[str, str] = {
    "var_95": "Value at risk, 95% one-day",
    "expected_shortfall_95": "Expected shortfall, 95%",
    "rolling_volatility_30d": "Volatility, 30 sessions",
    "daily_loss": "One-day loss",
    "gross_exposure": "Gross exposure",
    "issuer_concentration": "Issuer weight",
    "sector_concentration": "Sector weight",
    "stress_loss": "Stress loss",
}

# ── recipe rows (services.recipe's own labels) ───────────────────────────────
#
# These are the issuer page's Financials table. Several are derived, and the
# caption says how — "Free cash flow" is not a reported line anywhere, and a
# reader who does not know it is operations minus capital expenditure cannot
# check it against the filing.
RECIPE_ROW: dict[str, str] = {
    "gross_margin": "Gross margin",
    "operating_margin": "Operating margin",
    "net_margin": "Net margin",
    "gross_profit_derived": "Gross profit (revenue − cost of revenue)",
    "free_cash_flow": "Free cash flow (operations − capital expenditure)",
    "current_ratio": "Current ratio",
    "cash_to_long_term_debt_noncurrent": "Cash ÷ long-term debt, non-current",
    "revenue_yoy": "Revenue, year on year",
    "net_income_yoy": "Net income, year on year",
    "operating_income_yoy": "Operating income, year on year",
    "operating_cash_flow_yoy": "Cash from operations, year on year",
    "return_1m": "Return, 1 month",
    "return_3m": "Return, 3 months",
    "return_1y": "Return, 1 year",
    "return_1m_vs_SPY": "Return vs SPY, 1 month",
    "return_3m_vs_SPY": "Return vs SPY, 3 months",
    "return_1y_vs_SPY": "Return vs SPY, 1 year",
}

# ── named measures (analytics.formulas.FORMULAS) ─────────────────────────────
#
# These come out almost readable — `net_debt` is "net debt" — which is exactly
# why they need a table: "almost" is the acronyms, and `debt_to_ebitda` reads as
# "debt to ebitda" under any formatter that does not know EBITDA is a word made
# of letters. A ratio is written with a slash because that is how a credit
# analyst says it out loud.
FORMULA: dict[str, str] = {
    "ebit": "EBIT",
    "ebitda": "EBITDA",
    "free_cash_flow": "free cash flow",
    "total_debt": "total debt",
    "net_debt": "net debt",
    "ebit_interest_coverage": "EBIT / interest coverage",
    "debt_to_ebitda": "debt / EBITDA",
    "debt_to_operating_cash_flow": "debt / cash from operations",
    "fcf_to_debt": "free cash flow / debt",
    "current_ratio": "current ratio",
    "gross_margin": "gross margin",
    "operating_margin": "operating margin",
    "net_margin": "net margin",
    "days_sales_outstanding": "days sales outstanding",
    "days_inventory": "days inventory",
    "days_payable": "days payable",
    # V16 Tier 1 — returns, reinvestment and quality. The acronym rule above
    # holds (ROE stays ROE); a derived numerator says how it was built, because
    # a reader who cannot reconstruct "accruals" cannot check it.
    "roe": "ROE",
    "roa": "ROA",
    "roic": "ROIC",
    "nopat": "NOPAT",
    "tax_burden": "tax burden",
    "invested_capital": "invested capital",
    "asset_turnover": "asset turnover",
    "equity_multiplier": "equity multiplier",
    "quick_assets": "quick assets",
    "quick_ratio": "quick ratio",
    "fcf_margin": "free cash flow margin",
    "capex_intensity": "capex intensity",
    "net_debt_to_ebitda": "net debt / EBITDA",
    "cash_conversion_cycle": "cash conversion cycle",
    "accruals": "accruals (net income − cash from operations)",
    "accruals_ratio": "accruals ratio",
}

# ── sectors (as they arrive from the price provider) ─────────────────────────
SECTOR: dict[str, str] = {
    "Technology": "Technology",
    "Financials": "Financials",
    "Healthcare": "Healthcare",
    "Communication_Services": "Communication services",
    "Consumer_Discretionary": "Consumer discretionary",
    "Consumer_Staples": "Consumer staples",
    "Fixed_Income": "Fixed income",
    "Energy": "Energy",
    "Industrials": "Industrials",
    "Materials": "Materials",
    "Utilities": "Utilities",
    "Real_Estate": "Real estate",
    "Other": "Other",
}

_TABLES = {
    "metric": METRIC,
    "factor": FACTOR,
    "scenario": SCENARIO,
    "limit": LIMIT,
    "recipe_row": RECIPE_ROW,
    "formula": FORMULA,
    "sector": SECTOR,
}


def label(kind: str, key: str | None) -> str:
    """The caption for a key, or the key itself when there is none.

    Returning the key is not a fallback in the sense this codebase bans — there
    is no second, lesser answer being substituted for a real one. It is the
    identifier appearing as itself, which is what happened everywhere before this
    file existed, and it is visible: a page showing `some_new_metric` is a
    missing row here, and the guard fails the build before a reader ever sees it.
    """
    if key is None:
        return ""
    return _TABLES.get(kind, {}).get(key, key)


def metric(key: str | None) -> str:
    return label("metric", key)
