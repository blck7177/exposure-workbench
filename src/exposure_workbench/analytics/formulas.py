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
CFA_FAT = ("https://www.cfainstitute.org/insights/professional-learning/refresher-readings/"
           "2026/financial-analysis-techniques")
DAMODARAN_RETURNS = "https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/returnmeasures.pdf"
SLOAN_1996 = "https://www.stern.nyu.edu/sites/default/files/assets/documents/con_032093.pdf"

# Why a measure is refused for a financial issuer, as data. The default is the
# sentence the service has always used — V11-A found it was the best refusal
# sentence this codebase produced, so it stays verbatim — and a formula whose
# reason is DIFFERENT (a bank has no inventory; a bank's debt is raw material)
# carries its own sentence in `not_for_financials`. None means the measure DOES
# apply to a financial issuer: ROE is the profitability measure banks report.
NOT_FOR_FINANCIALS_DEFAULT = (
    "these are non-financial credit measures and they do not apply to a "
    "financial issuer: interest expense is an operating cost for a bank, so "
    "coverage and leverage built on adding it back describe nothing")
_NOT_FOR_BANKS_CAPITAL = (
    "for a financial issuer debt is not financing to be netted against "
    "operations — deposits and borrowings are the raw material of the "
    "business — so an invested capital assembled as debt plus equity minus "
    "cash describes nothing")
_NOT_FOR_BANKS_CLASSIFIED_BS = (
    "a financial issuer does not present a classified balance sheet: current "
    "assets, inventory and current liabilities are not lines a bank reports, "
    "so this measure has no inputs and no meaning there")
_NOT_FOR_BANKS_WORKING_CAPITAL = (
    "a financial issuer holds no inventory and its receivables and payables "
    "are not trade credit, so a working-capital cycle measured in days "
    "describes nothing")
_NOT_FOR_BANKS_CAPEX = (
    "operating cash flow less capital expenditure does not describe a bank, "
    "whose cash generation and reinvestment run through the loan book and "
    "deposits rather than property and equipment")


@dataclass(frozen=True)
class Formula:
    """One named measure. `expression` is for a reader; `inputs` and `op` are
    what the evaluator walks."""

    expression: str                      # human-readable, travels with the number
    inputs: tuple[str, ...]              # metric names or other formula names
    op: str                              # sum | difference | divide
    basis: str                           # instant | window | mixed
    source_url: str
    # What a reader may SAY the authority is. The url alone could not be spoken:
    # the model spliced it into `src_https://www.sec.gov/...` and the citation
    # gate refused it (sess_6acc3b20069d), so the answer fell back to "the
    # formula returned by the issuer panel" — a desk whose whole argument is
    # that the definition travels with the number, unable to name the section.
    citation: str = "SEC non-GAAP C&DIs"
    # Which question this measure answers, for a caller comparing two issuers:
    # "more leveraged" is a question about a ratio, and a dollar amount of debt
    # is not one. Data, so adding a family is an edit here.
    family: str = ""
    source_quote: str = ""
    note: str = ""
    unit_class: str = "money"            # money | ratio | count
    signs: tuple[int, ...] = field(default_factory=tuple)   # for `difference`
    # Other metrics that answer the same question when the primary is not
    # reported. NOT a silent fallback: whichever is used is named in the
    # result's definition, the way the margins name which revenue line they
    # divided by. Data, so adding one is an edit here and not a branch.
    alternatives: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Refused for a financial issuer, and WHY, or None when the measure applies
    # to banks (ROE, ROA, the accruals ratio). A reason, not a flag, so the
    # refusal the reader sees is about the measure and never a tautology about
    # the sector. The default keeps every pre-V16 formula refusing exactly as
    # it always did.
    not_for_financials: str | None = NOT_FOR_FINANCIALS_DEFAULT
    # For a divide formula: refuse when the denominator is ≤ 0, and say why.
    # Empty means no such condition. ROE over negative equity is the canonical
    # case — a loss over negative equity prints as a positive return, so the
    # number is suppressed rather than displayed (Damodaran, return measures).
    denominator_must_be_positive: str = ""


FORMULAS: dict[str, Formula] = {
    # ── earnings bases ────────────────────────────────────────────────────────
    "ebit": Formula(
        expression="net income + interest expense + income tax expense",
        inputs=("net_income", "interest_expense", "income_tax_expense"),
        alternatives={"interest_expense": ("interest_expense_nonoperating",)},
        op="sum", basis="window", family="earnings", citation="SEC C&DI 103.01, 103.02", source_url=SEC_NON_GAAP,
        source_quote=('C&DI 103.01: "Earnings" means net income as presented in the '
                      'statement of operations under GAAP. Measures that are calculated '
                      'differently ... should not be characterized as "EBIT" or "EBITDA".'),
        note=("Starts from net income, never operating income: C&DI 103.02 says operating "
              "income is not the comparable measure 'because EBIT and EBITDA make "
              "adjustments for items that are not included in operating income'. Read it "
              "beside operating income: where an issuer carries large non-operating income "
              "the two are far apart, and a correct EBIT is then mostly non-operating. The "
              "measurements behind that are in V9_FORMULA_BASIS."),
    ),
    "ebitda": Formula(
        expression="EBIT + depreciation and amortisation",
        inputs=("ebit", "depreciation_amortization"),
        op="sum", basis="window", family="earnings", citation="SEC C&DI 103.01, 103.02", source_url=SEC_NON_GAAP,
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
        op="difference", basis="window", family="cash", citation="SEC C&DI 102.07", source_url=SEC_NON_GAAP,
        source_quote=('C&DI 102.07: "free cash flow" ... is typically calculated as cash '
                      'flows from operating activities ... less capital expenditures ... '
                      'this measure does not have a uniform definition and its title does '
                      'not describe how it is calculated.'),
        note="The formula travels with the number because the regulator requires it to.",
    ),

    # ── what the book owes ────────────────────────────────────────────────────
    "total_debt": Formula(
        expression="the widest non-overlapping set of reported debt components",
        inputs=(), op="cover", basis="instant", family="leverage", source_url=SEC_NON_GAAP,
        note=("Composed by containment cover rather than a fixed list: which components an "
              "issuer reports varies, and adding a total to its own component double-counts. "
              "What the cover does not reach is reported beside it."),
    ),
    "net_debt": Formula(
        expression="total debt − cash and equivalents",
        inputs=("total_debt", "cash_and_equivalents"), signs=(1, -1),
        op="difference", basis="instant", family="leverage", source_url=SEC_NON_GAAP,
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
        unit_class="ratio", family="coverage", source_url=SEC_NON_GAAP,
        note="Both sides over one window; the window is stated with the number.",
    ),
    "debt_to_ebitda": Formula(
        expression="total debt ÷ EBITDA",
        inputs=("total_debt", "ebitda"), op="divide", basis="mixed",
        unit_class="ratio", family="leverage", source_url=SEC_NON_GAAP,
        note="A balance over a flow: the instant and the window are both stated.",
    ),
    "debt_to_operating_cash_flow": Formula(
        expression="total debt ÷ operating cash flow",
        inputs=("total_debt", "operating_cash_flow"), op="divide", basis="mixed",
        unit_class="ratio", family="leverage", source_url=SEC_NON_GAAP,
        note="A balance over a flow; both bases stated.",
    ),
    "fcf_to_debt": Formula(
        expression="free cash flow ÷ total debt",
        inputs=("free_cash_flow", "total_debt"), op="divide", basis="mixed",
        unit_class="ratio", family="coverage", source_url=SEC_NON_GAAP,
        note="A flow over a balance; both bases stated.",
    ),
    "current_ratio": Formula(
        expression="current assets ÷ current liabilities",
        inputs=("current_assets", "current_liabilities"), op="divide", basis="instant",
        unit_class="ratio", family="liquidity", source_url=SEC_NON_GAAP,
        note="Both sides at one instant.",
    ),
    "gross_margin": Formula(
        expression="gross profit ÷ revenue",
        inputs=("gross_profit", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="window",
        unit_class="ratio", family="margin", source_url=SEC_NON_GAAP,
        note=("Whichever top line the issuer reports is named in the result: LLY and JPM "
              "report only total revenues, and NVDA changed tagging in 2022."),
    ),
    "operating_margin": Formula(
        expression="operating income ÷ revenue",
        inputs=("operating_income", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="window",
        unit_class="ratio", family="margin", source_url=SEC_NON_GAAP,
        note="The revenue line used is named in the result.",
    ),
    "net_margin": Formula(
        expression="net income ÷ revenue",
        inputs=("net_income", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="window",
        unit_class="ratio", family="margin", source_url=SEC_NON_GAAP,
        note="The revenue line used is named in the result.",
    ),
    "days_sales_outstanding": Formula(
        expression="accounts receivable ÷ revenue × 365",
        inputs=("accounts_receivable", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="mixed",
        unit_class="count", family="turnover", source_url=SEC_NON_GAAP,
        note=("Ending balance, not an average: an average needs two dates and doubles the "
              "surface a missing quarter can remove. Stated in the result."),
    ),
    "days_inventory": Formula(
        expression="inventory ÷ cost of revenue × 365",
        inputs=("inventory", "cost_of_revenue"), op="divide", basis="mixed",
        unit_class="count", family="turnover", source_url=SEC_NON_GAAP,
        note="Ending balance, stated in the result.",
    ),
    "days_payable": Formula(
        expression="accounts payable ÷ cost of revenue × 365",
        inputs=("accounts_payable", "cost_of_revenue"), op="divide", basis="mixed",
        unit_class="count", family="turnover", source_url=SEC_NON_GAAP,
        note="Ending balance, stated in the result.",
    ),

    # ── returns on capital (V16, Tier 1) ─────────────────────────────────────
    "roe": Formula(
        expression="net income ÷ stockholders' equity",
        inputs=("net_income", "stockholders_equity"), op="divide", basis="mixed",
        unit_class="ratio", family="returns",
        citation="CFA Institute, Financial Analysis Techniques", source_url=CFA_FAT,
        not_for_financials=None,
        denominator_must_be_positive=(
            "stockholders' equity at or below zero makes ROE meaningless: a loss "
            "divided by negative equity prints as a positive return, so the ratio "
            "is refused rather than displayed"),
        note=("Ending equity, not a two-point average: an average needs two dates and "
              "doubles the surface a missing quarter can remove; stated in the result. "
              "Applies to financial issuers — ROE is the profitability measure banks "
              "themselves report. DuPont: roe = net_margin × asset_turnover × "
              "equity_multiplier, an identity, so a move in ROE can be read against "
              "which leg moved."),
    ),
    "roa": Formula(
        expression="net income ÷ total assets",
        inputs=("net_income", "total_assets"), op="divide", basis="mixed",
        unit_class="ratio", family="returns",
        citation="CFA Institute, Financial Analysis Techniques", source_url=CFA_FAT,
        not_for_financials=None,
        note=("Ending total assets, not an average; stated in the result. This is the "
              "common form with net income in the numerator — after interest, over "
              "assets financed partly by debt — not the after-tax-EBIT variant."),
    ),
    "tax_burden": Formula(
        expression="net income ÷ pretax income",
        inputs=("net_income", "pretax_income"), op="divide", basis="window",
        unit_class="ratio", family="returns",
        citation="CFA Institute, Financial Analysis Techniques (DuPont five-step)",
        source_url=CFA_FAT, not_for_financials=None,
        note=("The DuPont tax-burden term. Equals one minus the effective tax rate "
              "exactly when net income is pretax income less tax expense; items "
              "between the tax line and net income (noncontrolling interests) are "
              "the gap, and the division is on the page either way."),
    ),
    "nopat": Formula(
        expression="operating income × tax burden",
        inputs=("operating_income", "tax_burden"), op="product", basis="window",
        unit_class="money", family="earnings",
        citation="Damodaran, Return Measures (NYU Stern working paper)",
        source_url=DAMODARAN_RETURNS, not_for_financials=_NOT_FOR_BANKS_CAPITAL,
        note=("Operating income × (1 − effective tax rate), with the DuPont tax "
              "burden standing in for one minus the effective rate — see tax_burden "
              "for what the stand-in assumes. Effective rate, not marginal: a period "
              "with discrete tax items moves it, and the period is stated."),
    ),
    "invested_capital": Formula(
        expression="total debt + stockholders' equity − cash and equivalents",
        inputs=("total_debt", "stockholders_equity", "cash_and_equivalents"),
        signs=(1, 1, -1), op="difference", basis="instant",
        unit_class="money", family="leverage",
        citation="Damodaran, Return Measures (NYU Stern working paper)",
        source_url=DAMODARAN_RETURNS, not_for_financials=_NOT_FOR_BANKS_CAPITAL,
        note=("The financing-side book construction, at ending balances of one "
              "instant. All cash is netted, not only surplus cash — the operating/"
              "excess split needs inputs this desk does not hold, and which "
              "construction was used travels with the number."),
    ),
    "roic": Formula(
        expression="NOPAT ÷ invested capital",
        inputs=("nopat", "invested_capital"), op="divide", basis="mixed",
        unit_class="ratio", family="returns",
        citation="Damodaran, Return Measures (NYU Stern working paper)",
        source_url=DAMODARAN_RETURNS, not_for_financials=_NOT_FOR_BANKS_CAPITAL,
        note=("Ending invested capital, not beginning-of-period or an average: one "
              "date, one filing surface. Damodaran notes ending-balance ROIC "
              "understates when capital grew during the period; the instant used is "
              "stated with the number."),
    ),

    # ── efficiency and structure (V16, Tier 1) ───────────────────────────────
    "asset_turnover": Formula(
        expression="revenue ÷ total assets",
        inputs=("revenue", "total_assets"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="mixed",
        unit_class="ratio", family="turnover",
        citation="CFA Institute, Financial Analysis Techniques", source_url=CFA_FAT,
        not_for_financials=None,
        note=("Ending total assets, not an average; stated in the result. The middle "
              "DuPont term. Whichever top line the issuer reports is named in the "
              "result."),
    ),
    "equity_multiplier": Formula(
        expression="total assets ÷ stockholders' equity",
        inputs=("total_assets", "stockholders_equity"), op="divide", basis="instant",
        unit_class="ratio", family="leverage",
        citation="CFA Institute, Financial Analysis Techniques", source_url=CFA_FAT,
        not_for_financials=None,
        denominator_must_be_positive=(
            "stockholders' equity at or below zero makes the equity multiplier "
            "meaningless: assets over negative equity prints as a negative "
            "multiple of leverage, so the ratio is refused rather than displayed"),
        note=("Both sides at one instant. The leverage leg of DuPont: assets per "
              "unit of equity."),
    ),

    # ── liquidity (V16, Tier 1) ──────────────────────────────────────────────
    "quick_assets": Formula(
        expression="current assets − inventory",
        inputs=("current_assets", "inventory"), signs=(1, -1),
        op="difference", basis="instant", unit_class="money", family="liquidity",
        citation="CFA Institute, Financial Analysis Techniques", source_url=CFA_FAT,
        not_for_financials=_NOT_FOR_BANKS_CLASSIFIED_BS,
        note=("Current assets less inventory, one instant. An approximation of the "
              "textbook numerator (cash + short-term securities + receivables): it "
              "keeps prepaid expenses in, and which construction was used travels "
              "with the number."),
    ),
    "quick_ratio": Formula(
        expression="(current assets − inventory) ÷ current liabilities",
        inputs=("quick_assets", "current_liabilities"), op="divide", basis="instant",
        unit_class="ratio", family="liquidity",
        citation="CFA Institute, Financial Analysis Techniques", source_url=CFA_FAT,
        not_for_financials=_NOT_FOR_BANKS_CLASSIFIED_BS,
        note=("Both sides at one instant. Differs from the current ratio only by "
              "inventory, which it declines to treat as near-cash; see quick_assets "
              "for what the numerator approximates."),
    ),

    # ── cash generation as a share of revenue (V16, Tier 1) ──────────────────
    "fcf_margin": Formula(
        expression="free cash flow ÷ revenue",
        inputs=("free_cash_flow", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="window",
        unit_class="ratio", family="margin",
        citation="SEC C&DI 102.07", source_url=SEC_NON_GAAP,
        not_for_financials=_NOT_FOR_BANKS_CAPEX,
        note=("Both sides over one window. Free cash flow carries its own definition "
              "(C&DI 102.07: the title does not describe how it is calculated), so "
              "the margin inherits it; the revenue line used is named in the "
              "result."),
    ),
    "capex_intensity": Formula(
        expression="capital expenditures ÷ revenue",
        inputs=("capex", "revenue"),
        alternatives={"revenue": ("total_revenues",)}, op="divide", basis="window",
        unit_class="ratio", family="reinvestment",
        citation="CFA Institute, Financial Analysis Techniques", source_url=CFA_FAT,
        not_for_financials=_NOT_FOR_BANKS_CAPEX,
        note=("Both sides over one window. Read beside asset_turnover: capex as a "
              "share of revenue is the reinvestment the turnover has to earn a "
              "return on."),
    ),

    # ── leverage (V16, Tier 1) ───────────────────────────────────────────────
    "net_debt_to_ebitda": Formula(
        expression="net debt ÷ EBITDA",
        inputs=("net_debt", "ebitda"), op="divide", basis="mixed",
        unit_class="ratio", family="leverage", source_url=SEC_NON_GAAP,
        note=("A balance over a flow — the covenant form; the instant and the window "
              "are both stated. Net debt here is total debt less all cash, NOT an "
              "agency net debt (see net_debt)."),
    ),

    # ── the working-capital cycle (V16, Tier 1) ──────────────────────────────
    "cash_conversion_cycle": Formula(
        expression="days sales outstanding + days inventory − days payable",
        inputs=("days_sales_outstanding", "days_inventory", "days_payable"),
        signs=(1, 1, -1), op="difference", basis="mixed",
        unit_class="count", family="turnover",
        citation="CFA Institute, Financial Analysis Techniques", source_url=CFA_FAT,
        not_for_financials=_NOT_FOR_BANKS_WORKING_CAPITAL,
        note=("A count of days: how long operations must be self-funded. Each days "
              "measure is built on ending balances and states its own window in the "
              "result."),
    ),

    # ── earnings quality (V16, Tier 1) ───────────────────────────────────────
    "accruals": Formula(
        expression="net income − operating cash flow",
        inputs=("net_income", "operating_cash_flow"), signs=(1, -1),
        op="difference", basis="window", unit_class="money", family="quality",
        citation="Sloan (1996), The Accounting Review 71(3); Hribar & Collins (2002)",
        source_url=SLOAN_1996, not_for_financials=None,
        note=("The cash-flow construction (Hribar & Collins 2002), not Sloan's "
              "balance-sheet one: acquisitions and divestitures contaminate the "
              "balance-sheet form, which is why the cash-flow form became standard. "
              "Both flows over one window."),
    ),
    "accruals_ratio": Formula(
        expression="(net income − operating cash flow) ÷ total assets",
        inputs=("accruals", "total_assets"), op="divide", basis="mixed",
        unit_class="ratio", family="quality",
        citation="Sloan (1996), The Accounting Review 71(3)",
        source_url=SLOAN_1996, not_for_financials=None,
        note=("Sloan deflates by average total assets; this desk uses the ending "
              "balance for the same one-date reason as the days measures, and says "
              "so. Sloan's finding is about persistence — the accrual component of "
              "earnings is less persistent than the cash component — and the "
              "reading of any level belongs to the reader."),
    ),
}

# The ops the evaluator dispatches on. Nothing else may appear in a Formula:
# an op outside this set used to fall through an else-branch into `divide`,
# which is the quietest possible way to compute the wrong thing.
KNOWN_OPS = ("sum", "difference", "divide", "product", "cover")
UNIT_CLASSES = ("money", "ratio", "count")


def validate(formulas: dict[str, "Formula"]) -> None:
    """Refuse a malformed registry at import, not at a user.

    Each rule below removes a silent-failure class the V16 audit found in the
    evaluator: `difference` with signs=() looped zero times and returned its
    first operand as the answer; an unknown op fell through to divide; a
    divide with three inputs evaluated the first two and dropped the third.
    None of those can now be WRITTEN, so the evaluator does not need a branch
    for any of them.
    """
    for name, f in formulas.items():
        if f.op not in KNOWN_OPS:
            raise ValueError(f"{name}: op {f.op!r} is not one of {KNOWN_OPS}")
        if f.unit_class not in UNIT_CLASSES:
            raise ValueError(f"{name}: unit_class {f.unit_class!r} is not one of "
                             f"{UNIT_CLASSES}")
        if f.op in ("divide", "product") and len(f.inputs) != 2:
            raise ValueError(f"{name}: {f.op} takes exactly two inputs, got "
                             f"{len(f.inputs)}")
        if f.op in ("sum", "difference") and len(f.inputs) < 2:
            raise ValueError(f"{name}: {f.op} needs at least two inputs — a "
                             f"one-term {f.op} is its input under another name, "
                             f"and the evaluator would return it unrenamed")
        if f.op == "difference":
            if len(f.signs) != len(f.inputs):
                raise ValueError(f"{name}: difference needs one sign per input "
                                 f"({len(f.inputs)}), got {len(f.signs)} — with "
                                 f"too few, trailing inputs are silently dropped")
            if f.signs[0] != 1:
                raise ValueError(f"{name}: signs[0] must be +1 — the evaluator "
                                 f"starts FROM the first operand and never reads "
                                 f"its sign, so -1 there would be silently ignored")
            if any(s not in (1, -1) for s in f.signs):
                raise ValueError(f"{name}: signs must be +1 or -1, got {f.signs}")
        elif f.signs:
            raise ValueError(f"{name}: signs are only read by difference; on "
                             f"{f.op} they would be silently ignored")
        if f.op == "divide" and f.unit_class == "count" and "365" not in f.expression:
            # A count that comes out of a division IS a days measure: the
            # evaluator scales the quotient by 365 and the expression must say
            # so, or the printed formula and the printed number disagree.
            raise ValueError(f"{name}: a divide formula with unit_class 'count' "
                             f"is scaled by 365, and its expression must state "
                             f"the × 365")
        if f.denominator_must_be_positive and f.op != "divide":
            raise ValueError(f"{name}: denominator_must_be_positive only means "
                             f"something on a divide formula")


validate(FORMULAS)


def authority(f: "Formula") -> dict:
    """What a reader may say the authority is, and where to read it.

    An object rather than a joined string, and that is the point: handed a bare
    url the model built `src_https://www.sec.gov/...` out of it and the gate
    refused the answer (sess_6acc3b20069d). There is no flat, id-shaped value
    here to splice. `Evidence.tsx` already renders any key named `url` as a
    link, so the UI needs nothing.
    """
    return {"cite_as": f.citation, "url": f.source_url}


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


# The reading order (V16-S3). An analyst reads a company cash-first — cash →
# earnings → margins → returns → activity → balance sheet → screens — and the
# catalogue lists measures in the order the method reads them, so the model
# meets them the way an analyst does. Data, not behaviour: reordering is an
# edit here and changes every describe_issuer at once.
FAMILY_ORDER: tuple[str, ...] = (
    "cash", "earnings", "margin", "returns", "turnover",
    "liquidity", "coverage", "leverage", "reinvestment", "quality",
)

_UNORDERED_FAMILIES = {f.family for f in FORMULAS.values()} - set(FAMILY_ORDER)
if _UNORDERED_FAMILIES:
    raise ValueError(
        f"formulas carry families the reading order does not place: "
        f"{sorted(_UNORDERED_FAMILIES)} — add them to FAMILY_ORDER"
    )
