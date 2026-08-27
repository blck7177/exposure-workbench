"""What each named measure means, and who says so. Data, not code.

A ratio without its definition is not checkable — "leverage 2.1x" says nothing
until you know whether the debt is gross or net and the earnings reported or
adjusted. The SEC states the principle for one of these outright: free cash flow
"does not have a uniform definition and its title does not describe how it is
calculated" (C&DI 102.07), so the calculation has to travel beside the number.

So a formula is a name, an expression over metrics this corpus actually holds,
and the authority for defining it that way. Adding one is an edit to data;
nothing here is a function. Two consequences worth stating:

  * EBIT and EBITDA start from NET INCOME, because C&DI 103.01 says "earnings"
    means net income and that measures calculated differently "should not be
    characterized as EBIT or EBITDA". An operating-income lookalike under those
    names is the mislabel the regulator names.
  * Nothing here carries a threshold. No band, no healthy, no risky. This desk
    lays out evidence and the reading belongs to the reader — a decision taken
    on 2026-08-24 and enforced by test_no_formula_carries_a_threshold.

Sources and the corpus measurements behind them: docs/spikes/V9_FORMULA_BASIS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEC_NON_GAAP = "https://www.sec.gov/corpfin/non-gaap-financial-measures"


@dataclass(frozen=True)
class Formula:
    """One named measure. `expression` is for a reader; `inputs` and `op` are
    what the evaluator walks."""

    expression: str                      # human-readable, travels with the number
    inputs: tuple[str, ...]              # metric names or other formula names
    op: str                              # sum | difference | divide
    basis: str                           # instant | window | mixed
    source_url: str
    source_quote: str = ""
    note: str = ""
    unit_class: str = "money"            # money | ratio
    signs: tuple[int, ...] = field(default_factory=tuple)   # for `difference`
    # Other metrics that answer the same question when the primary is not
    # reported. NOT a silent fallback: whichever is used is named in the
    # result's definition, the way the margins name which revenue line they
    # divided by. Data, so adding one is an edit here and not a branch.
    alternatives: dict[str, tuple[str, ...]] = field(default_factory=dict)


FORMULAS: dict[str, Formula] = {
    # ── earnings bases ────────────────────────────────────────────────────────
    "ebit": Formula(
        expression="net income + interest expense + income tax expense",
        inputs=("net_income", "interest_expense", "income_tax_expense"),
        alternatives={"interest_expense": ("interest_expense_nonoperating",)},
        op="sum", basis="window", source_url=SEC_NON_GAAP,
        source_quote=('C&DI 103.01: "Earnings" means net income as presented in the '
                      'statement of operations under GAAP. Measures that are calculated '
                      'differently ... should not be characterized as "EBIT" or "EBITDA".'),
        note=("Starts from net income, never operating income: C&DI 103.02 says operating "
              "income is not the comparable measure 'because EBIT and EBITDA make "
              "adjustments for items that are not included in operating income'. Read it "
              "beside operating income — measured on GOOGL's June 2026 quarter, pretax "
              "income of 138.753bn against operating income of 40.770bn makes a correct "
              "EBIT almost entirely non-operating."),
    ),
    "ebitda": Formula(
        expression="EBIT + depreciation and amortisation",
        inputs=("ebit", "depreciation_amortization"),
        op="sum", basis="window", source_url=SEC_NON_GAAP,
        source_quote='C&DI 103.01 describes EBITDA as "earnings before interest, taxes, '
                     'depreciation and amortization".',
        note=("Available for 5 of the 8 issuers held: GOOGL, JPM and MSFT do not report "
              "DepreciationDepletionAndAmortization, and their separately reported "
              "depreciation and intangible amortisation are not summed into it — their sum "
              "is not guaranteed to be the issuer's D&A."),
    ),

    # ── cash generation ───────────────────────────────────────────────────────
    "free_cash_flow": Formula(
        expression="operating cash flow − capital expenditures",
        inputs=("operating_cash_flow", "capex"), signs=(1, -1),
        op="difference", basis="window", source_url=SEC_NON_GAAP,
        source_quote=('C&DI 102.07: "free cash flow" ... is typically calculated as cash '
                      'flows from operating activities ... less capital expenditures ... '
                      'this measure does not have a uniform definition and its title does '
                      'not describe how it is calculated.'),
        note="The formula travels with the number because the regulator requires it to.",
    ),

    # ── what the book owes ────────────────────────────────────────────────────
    "total_debt": Formula(
        expression="the widest non-overlapping set of reported debt components",
        inputs=(), op="cover", basis="instant", source_url=SEC_NON_GAAP,
        note=("Composed by containment cover rather than a fixed list: which components an "
              "issuer reports varies, and adding a total to its own component double-counts "
              "— 8.31bn on AAPL. What the cover does not reach is reported beside it."),
    ),
    "net_debt": Formula(
        expression="total debt − cash and equivalents",
        inputs=("total_debt", "cash_and_equivalents"), signs=(1, -1),
        op="difference", basis="instant", source_url=SEC_NON_GAAP,
        note=("NOT an agency net debt. S&P nets only surplus cash, with haircuts that need "
              "inputs this desk does not have, so a number carrying that name here would be "
              "a defined term it is not."),
    ),

    # ── ratios ────────────────────────────────────────────────────────────────
    "ebit_interest_coverage": Formula(
        expression="EBIT ÷ interest expense, over the same window",
        inputs=("ebit", "interest_expense"),
        alternatives={"interest_expense": ("interest_expense_nonoperating",)},
        op="divide", basis="window",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="Both sides over one window; the window is stated with the number.",
    ),
    "debt_to_ebitda": Formula(
        expression="total debt ÷ EBITDA",
        inputs=("total_debt", "ebitda"), op="divide", basis="mixed",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="A balance over a flow: the instant and the window are both stated.",
    ),
    "debt_to_operating_cash_flow": Formula(
        expression="total debt ÷ operating cash flow",
        inputs=("total_debt", "operating_cash_flow"), op="divide", basis="mixed",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="A balance over a flow; both bases stated.",
    ),
    "fcf_to_debt": Formula(
        expression="free cash flow ÷ total debt",
        inputs=("free_cash_flow", "total_debt"), op="divide", basis="mixed",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="A flow over a balance; both bases stated.",
    ),
    "current_ratio": Formula(
        expression="current assets ÷ current liabilities",
        inputs=("current_assets", "current_liabilities"), op="divide", basis="instant",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="Both sides at one instant.",
    ),
    "gross_margin": Formula(
        expression="gross profit ÷ revenue",
        inputs=("gross_profit", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="window",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note=("Whichever top line the issuer reports is named in the result: LLY and JPM "
              "report only total revenues, and NVDA changed tagging in 2022."),
    ),
    "operating_margin": Formula(
        expression="operating income ÷ revenue",
        inputs=("operating_income", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="window",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="The revenue line used is named in the result.",
    ),
    "net_margin": Formula(
        expression="net income ÷ revenue",
        inputs=("net_income", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="window",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="The revenue line used is named in the result.",
    ),
    "days_sales_outstanding": Formula(
        expression="accounts receivable ÷ revenue × 365",
        inputs=("accounts_receivable", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="mixed",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note=("Ending balance, not an average: an average needs two dates and doubles the "
              "surface a missing quarter can remove. Stated in the result."),
    ),
    "days_inventory": Formula(
        expression="inventory ÷ cost of revenue × 365",
        inputs=("inventory", "cost_of_revenue"), op="divide", basis="mixed",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="Ending balance, stated in the result.",
    ),
    "days_payable": Formula(
        expression="accounts payable ÷ cost of revenue × 365",
        inputs=("accounts_payable", "cost_of_revenue"), op="divide", basis="mixed",
        unit_class="ratio", source_url=SEC_NON_GAAP,
        note="Ending balance, stated in the result.",
    ),
}

DAYS_FORMULAS = ("days_sales_outstanding", "days_inventory", "days_payable")


def evaluation_order() -> tuple[str, ...]:
    """Formulas first, dependencies before dependents. Raises on a cycle rather
    than looping — a registry that can be edited into a cycle should say so at
    import, not at a user."""
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            raise ValueError(f"formula cycle: {' -> '.join(stack + (name,))}")
        state[name] = 1
        for i in FORMULAS[name].inputs:
            if i in FORMULAS:
                visit(i, stack + (name,))
        state[name] = 2
        order.append(name)

    for n in sorted(FORMULAS):
        visit(n, ())
    return tuple(order)
