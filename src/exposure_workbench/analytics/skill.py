"""The skill registry: every method this desk knows, one shape (V23).

WHY THIS EXISTS. Until V23 a "method" had three shapes: a formula was a row
of data run by `calculate` (analytics/formulas.py); a price statistic was a
TOOL of its own (price_analytics_service._TOOL_SPECS, nine of them); a book
derivation was a panel service (integration_service, reconcile_service,
drawdown_service). Three shapes meant three ways to call, three kinds of
description in front of the model, and thirteen tools that existed only
because a method needed an entry point. The conversation battery and the
2026-09-04 review traced the desk's complexity to that one seam, and the
boss's decision was: one registry, one `compute`, and the tools that remain
are the desk's DATA DOMAINS, not its methods.

So a method here is DATA: what it is called, what kind of subject it is
about, what it computes, on whose authority, when it fails, and what
parameters it takes. `services/compute_service` executes it; `describe`
lists it beside the subject it applies to. Nothing here is a function the
model calls — the executor is a name compute resolves.

TWO RULES THE CONSTRUCTOR ENFORCES (the "author must remember" rule made a
construction-time error): every method states an `authority` and a
`fails_when`. A price statistic moved here without either is a tool with a
new name, which is the migration this module exists to refuse.

THRESHOLDS. None. `test_no_formula_carries_a_threshold` (2026-08-24)
extends to every entry: a method computes; a reading (READINGS, below) may
say how a figure is read, with its authority, and never enters a computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from exposure_workbench.analytics import formulas as fm

SUBJECT_KINDS = ("issuer", "price", "run", "portfolio", "series")

# Where compute finds the code that runs a method. A name, not a callable, so
# this module imports no service and the registry stays importable anywhere
# (the tool container, a test, the catalogue).
EXECUTORS = (
    "formula", "formula.panel",
    "price.rolling_volatility", "price.beta", "price.momentum_12_1",
    "price.distance_from_52w_high", "price.adv", "price.drawdown", "price.window_return",
    "book.analysis", "book.reconcile", "book.drawdown_episodes", "book.explain_episode",
    "book.sell", "book.buy",
)


@dataclass(frozen=True)
class Method:
    """One named method. `describes` is one sentence for a reader; `procedure`
    is what the number is made of; `authority` is who says it is made that way."""

    name: str
    subject_kind: str
    family: str
    describes: str
    procedure: str
    authority: str
    fails_when: str
    executor: str
    params_schema: dict = field(default_factory=lambda: {"type": "object", "properties": {},
                                                          "additionalProperties": False})
    unit_class: str | None = None
    source_url: str = ""
    inputs: tuple[str, ...] = ()
    # Which quantities the result puts on the table, as the reader will see
    # them named — for `describe`, so the model knows what a method yields
    # before paying for it.
    yields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.subject_kind not in SUBJECT_KINDS:
            raise ValueError(f"{self.name}: subject_kind {self.subject_kind!r} is not one of {SUBJECT_KINDS}")
        if self.executor not in EXECUTORS:
            raise ValueError(f"{self.name}: executor {self.executor!r} is not one compute knows")
        if not self.authority.strip():
            raise ValueError(f"{self.name}: a method states its authority; none given")
        if not self.fails_when.strip():
            raise ValueError(f"{self.name}: a method states when it fails or is meaningless; none given")
        if self.params_schema.get("type") != "object":
            raise ValueError(f"{self.name}: params_schema must describe an object")


# ── issuer methods: the formula registry, one entry per formula ──────────────

_ISSUER_PARAMS = {"type": "object", "properties": {
    "months": {"type": ["integer", "null"], "enum": [3, 6, 9, 12, None],
               "description": "window for flow-based measures (default 12)"},
    "at": {"type": ["string", "null"], "description": "YYYY-MM-DD instant for balance-based measures; omitted = latest"},
}, "additionalProperties": False}


def _fails_when_formula(f: fm.Formula) -> str:
    parts = ["an input the issuer did not file at the window or instant asked"]
    if f.not_for_financials is not None:
        parts.append("the issuer is a financial company: " + f.not_for_financials.split(":")[0])
    if f.denominator_must_be_positive:
        parts.append(f.denominator_must_be_positive)
    return "; ".join(parts)


def _issuer_methods() -> dict[str, Method]:
    out: dict[str, Method] = {}
    for name, f in fm.FORMULAS.items():
        out[name] = Method(
            name=name, subject_kind="issuer", family=f.family, describes=f.expression,
            procedure=f"{f.op} over {', '.join(f.inputs)}", authority=f.citation,
            source_url=f.source_url, fails_when=_fails_when_formula(f), executor="formula",
            params_schema=_ISSUER_PARAMS, unit_class=f.unit_class, inputs=f.inputs,
            yields=(name,),
        )
    out["issuer.panel"] = Method(
        name="issuer.panel", subject_kind="issuer", family="panel",
        describes="every named issuer measure this desk knows, evaluated once, with each one's own refusal where an input is missing",
        procedure="evaluate every entry of the formula registry", authority="the registry's own entries, each with its citation",
        fails_when="never as a whole; each measure fails on its own terms",
        executor="formula.panel", params_schema=_ISSUER_PARAMS, yields=tuple(fm.FORMULAS),
    )
    return out


# ── price methods: what price_analytics_service computes, as data ────────────

_TICKER_WINDOW = {"type": "object", "properties": {
    "window": {"type": ["string", "null"], "enum": ["1m", "3m", "6m", "1y", "3y", None],
               "description": "named span (default 1y)"},
}, "additionalProperties": False}

_PRICE_METHODS: tuple[Method, ...] = (
    Method(
        name="price.volatility", subject_kind="price", family="risk",
        describes="annualised volatility of the last N daily returns",
        procedure="standard deviation of daily simple returns over the window × √252",
        authority="CFA Program, Quantitative Methods (return volatility); √252 annualisation is the industry convention",
        fails_when="fewer than 20 sessions in the window (VOL_MIN_OBS): refused with the counts, never shortened",
        executor="price.rolling_volatility", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "window_days": {"type": ["integer", "null"], "enum": [21, 30, 63, 126, 252, None],
                            "description": "sessions in the window (default 30)"}},
            "additionalProperties": False},
        yields=("{ticker}.vol.{n}d",),
    ),
    Method(
        name="price.beta", subject_kind="price", family="risk",
        describes="OLS beta, alpha and R² of a name's daily returns on a benchmark's (default SPY)",
        procedure="ordinary least squares of adjusted daily returns on the benchmark's, aligned by date",
        authority="Sharpe (1964) market model; CFA Program, Portfolio Management (beta estimation)",
        fails_when="fewer than 60 aligned observations (BETA_MIN_OBS); a benchmark with no price history",
        executor="price.beta", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "benchmark": {"type": ["string", "null"], "description": "benchmark ticker (default SPY); a factor ETF such as TLT gives the name's sensitivity to that factor"},
            "window": _TICKER_WINDOW["properties"]["window"]},
            "additionalProperties": False},
        yields=("{ticker}.beta", "{ticker}.alpha", "{ticker}.r_squared"),
    ),
    Method(
        name="price.momentum_12_1", subject_kind="price", family="momentum",
        describes="cumulative adjusted return from ~12 months back through 21 sessions back, the last month skipped",
        procedure="adjusted close 21 sessions back ÷ adjusted close ~252 sessions back − 1",
        authority="Jegadeesh & Titman (1993), Returns to Buying Winners and Selling Losers",
        fails_when="fewer than 200 sessions of history (MOMENTUM_MIN_OBS); a formation window under 252 sessions is flagged",
        executor="price.momentum_12_1", unit_class="ratio", yields=("{ticker}.momentum_12_1",),
    ),
    Method(
        name="price.distance_from_52w_high", subject_kind="price", family="momentum",
        describes="how far the adjusted close sits below its trailing-year high, with the date the high was set",
        procedure="close ÷ max(close over the trailing year) − 1",
        authority="George & Hwang (2004), The 52-Week High and Momentum Investing",
        fails_when="fewer than 200 sessions of history (MOMENTUM_MIN_OBS)",
        executor="price.distance_from_52w_high", unit_class="ratio",
        yields=("{ticker}.distance_from_52w_high",),
    ),
    Method(
        name="price.adv", subject_kind="price", family="liquidity",
        describes="average daily volume over the last N sessions, in shares and in dollars",
        procedure="mean of daily volume, and of close × volume, over the window; sessions without volume dropped and counted",
        authority="desk convention for days-to-liquidate arithmetic (20/30/60-session windows)",
        fails_when="fewer than 20 sessions (ADV_MIN_OBS) or no recorded volume",
        executor="price.adv", unit_class="count",
        params_schema={"type": "object", "properties": {
            "window_days": {"type": ["integer", "null"], "enum": [20, 30, 60, None],
                            "description": "sessions in the window (default 20)"}},
            "additionalProperties": False},
        yields=("{ticker}.adv.shares", "{ticker}.adv.dollars"),
    ),
    Method(
        name="price.drawdown", subject_kind="price", family="risk",
        describes="the deepest peak-to-trough fall of the adjusted close over a window: peak, trough, fall and depth, dated, with the recovery date if regained",
        procedure="max over the window of (running peak − close); fall = peak − trough, depth = fall ÷ peak",
        authority="the standard drawdown definition (Magdon-Ismail, Atiya, Pratap & Abu-Mostafa, 2004)",
        fails_when="fewer than 20 sessions (DRAWDOWN_MIN_OBS); a window that never fell is stated, not zero",
        executor="price.drawdown", unit_class="ratio", params_schema=_TICKER_WINDOW,
        yields=("{ticker}.drawdown.peak", "{ticker}.drawdown.trough", "{ticker}.drawdown.fall", "{ticker}.drawdown.depth"),
    ),
    Method(
        name="price.window_return", subject_kind="price", family="return",
        describes="total return over a named window, and relative to a benchmark when one is given",
        procedure="adjusted close at the window's end ÷ at its start − 1; relative = the name's return − the benchmark's",
        authority="total-return convention on split- and dividend-adjusted closes",
        fails_when="no price on or before either end of the window",
        executor="price.window_return", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "window": {"type": ["string", "null"], "enum": ["1m", "3m", "6m", "1y", None], "description": "default 1y"},
            "benchmark": {"type": ["string", "null"], "description": "benchmark ticker for the relative return; null for none"}},
            "additionalProperties": False},
        yields=("{ticker}.window_return", "{ticker}.window_return.relative"),
    ),
)


# ── book methods: what the run's readers derive, as data ─────────────────────

_BOOK_METHODS: tuple[Method, ...] = (
    Method(
        name="book.analysis", subject_kind="run", family="book",
        describes="one run's exposures ordered and netted, and the distance from every limit check to its warning and breach tiers",
        procedure="net beta per risk = Σ beta_i × direction_i (TLT and HYG move opposite to the risk they proxy); room = tier − current; positions ordered by weight",
        authority="arithmetic over the run's own rows; instrument directions are properties of the factor ETFs, not of any issuer",
        fails_when="the run is not completed; a risk no factor in the regression measures is reported unmeasured, not zero",
        executor="book.analysis", unit_class="ratio",
        yields=("portfolio.integration.net_beta.<risk>", "portfolio.integration.gross_beta.<risk>",
                "portfolio.integration.room_to_warning.<check>", "portfolio.integration.room_to_breach.<check>"),
    ),
    Method(
        name="book.reconcile", subject_kind="run", family="attribution",
        describes="one day's portfolio move reconciled: position contributions against the day's return, and the factor-explained share against the residual",
        procedure="Σ position contributions = portfolio return; Σ factor contributions + alpha + residual = portfolio return; factor_share = Σ factor / total",
        authority="the two accounting identities of return attribution (Brinson-style position attribution; the factor model's own decomposition)",
        fails_when="the position identity does not hold within tolerance — then no share of the move is reported at all",
        executor="book.reconcile", unit_class="ratio",
        yields=("portfolio.reconcile.sum_of_position_contributions", "portfolio.reconcile.factor_share", "portfolio.reconcile.unexplained_share"),
    ),
    Method(
        name="book.drawdown_episodes", subject_kind="portfolio", family="risk",
        describes="every peak-to-trough episode of the book at least 5% deep in a span, deepest first, with trough and recovery dates",
        procedure="episodes of the portfolio value path; depth = (peak − trough) ÷ peak",
        authority="the standard drawdown definition; the 5% floor is a producer parameter",
        fails_when="fewer sessions than the span needs; a span that never fell 5% has no episodes",
        executor="book.drawdown_episodes", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "span": {"type": ["string", "null"], "enum": ["3m", "6m", "1y", "3y", None], "description": "default 1y"}},
            "additionalProperties": False},
        yields=("portfolio.drawdown_episodes.deepest_depth", "portfolio.drawdown_episodes.episode_depths"),
    ),
    Method(
        name="book.explain_episode", subject_kind="portfolio", family="risk",
        describes="what one drawdown episode was made of: the book's return over the window and each holding's contribution to it",
        procedure="window return of the book and of each position between the peak and trough dates",
        authority="arithmetic over the price series the book holds",
        fails_when="no prices on the peak or trough date",
        executor="book.explain_episode", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "peak": {"type": "string", "description": "YYYY-MM-DD"},
            "trough": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["peak", "trough"], "additionalProperties": False},
    ),
    Method(
        name="book.sell", subject_kind="run", family="scenario",
        describes="the book after selling all or part of some names: weights renormalised over what remains, sector weights, market value, and every concentration and exposure limit check re-run; the proceeds leave the book. The subject is a run (run_…) or another scenario's calc_ row, so trades chain",
        procedure="remove the sold market value; weight_i = mv_i ÷ Σ mv remaining; check_limits over the result with the portfolio's own thresholds",
        authority="arithmetic over the run's positions; thresholds from the portfolio's risk_limits (analytics/limits)",
        fails_when="a name not held, a fraction outside (0, 1], a name sold twice, a sale emptying the book, an unpriced holding; factor exposures are not re-fitted and are stated unmeasured",
        executor="book.sell", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "sales": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "properties": {
                "ticker": {"type": "string"},
                "fraction": {"type": "number", "exclusiveMinimum": 0, "maximum": 1,
                             "description": "share of the position sold; omitted means all of it"}},
                "required": ["ticker"], "additionalProperties": False}}},
            "required": ["sales"], "additionalProperties": False},
        yields=("issuer_exposures.<T>.weight", "sector_exposures.<S>.weight", "exposure_metrics.portfolio_market_value",
                "limit_checks.<check>.current_value", "count.alerts"),
    ),
    Method(
        name="book.buy", subject_kind="run", family="scenario",
        describes="the book after adding names at target weights of the new book: every existing weight scaled down, sector weights, market value, and every concentration and exposure limit check re-run; the money comes from outside the book. The subject is a run (run_…) or another scenario's calc_ row (a sale, then this purchase on its result)",
        procedure="mv_added = w × mv_old ÷ (1 − Σ w); weight_i = mv_i ÷ Σ mv; check_limits over the result",
        authority="arithmetic over the run's positions; thresholds from the portfolio's risk_limits; the new name's sector from the desk's company record",
        fails_when="a target weight outside (0, 1), targets summing to 1 or more, a name the desk cannot place in a sector, a name already held (trim or add to it through its weight instead); factor exposures are stated unmeasured",
        executor="book.buy", unit_class="ratio",
        params_schema={"type": "object", "properties": {
            "buys": {"type": "array", "minItems": 1, "maxItems": 20, "items": {"type": "object", "properties": {
                "ticker": {"type": "string"},
                "weight": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1,
                           "description": "target share of the book AFTER the purchase"}},
                "required": ["ticker", "weight"], "additionalProperties": False}}},
            "required": ["buys"], "additionalProperties": False},
        yields=("issuer_exposures.<T>.weight", "sector_exposures.<S>.weight", "exposure_metrics.portfolio_market_value",
                "limit_checks.<check>.current_value", "count.alerts"),
    ),
)


METHODS: dict[str, Method] = {
    **_issuer_methods(),
    **{m.name: m for m in _PRICE_METHODS},
    **{m.name: m for m in _BOOK_METHODS},
}


def methods_for(subject_kind: str) -> list[Method]:
    return [m for m in METHODS.values() if m.subject_kind == subject_kind]


def nearest(name: str, n: int = 5) -> list[str]:
    """The registry names closest to an unknown one — a closed lookup, so an
    `unknown_method` refusal can point at `roic` when `return_on_capital` was asked."""
    import difflib
    return difflib.get_close_matches(name, list(METHODS), n=n, cutoff=0.4)


# ── the arithmetic ops compute also takes, named once ────────────────────────

SCALAR_OPS = ("add", "subtract", "multiply", "divide")
SCALE_OP = "scale"          # one operand × a constant (params.factor); the typed calculator's scale
RANK_OP = "rank"
REGRESS_OP = "regress"


# ── readings: how a figure is read, never a threshold in a computation ───────

@dataclass(frozen=True)
class Reading:
    """What an analyst knows about reading one measure. Guidance for the
    agent's sentence, with its authority; nothing here reaches compute."""
    method: str
    compare_within: str
    reads: str
    meaningless_when: str
    authority: str

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"reading for unknown method {self.method!r}")
        if not self.authority.strip():
            raise ValueError(f"{self.method}: a reading states its authority")


READINGS: dict[str, Reading] = {r.method: r for r in (
    Reading("debt_to_ebitda", "the issuer's sector and its own prior periods",
            "gross and net conventions differ by the cash held; energy, utilities and telecoms are usually read net; the ratio says how many years of EBITDA the debt represents",
            "EBITDA is zero or negative; a financial issuer (debt is its raw material)",
            "CFA Program, Financial Analysis Techniques — solvency ratios"),
    Reading("net_debt_to_ebitda", "the issuer's sector and its own prior periods",
            "net of cash the issuer could apply to the debt; read beside the gross ratio, and say which cash line was netted",
            "EBITDA is zero or negative; a financial issuer",
            "CFA Program, Financial Analysis Techniques — solvency ratios"),
    Reading("ebit_interest_coverage", "the issuer's own prior periods and rated peers",
            "how many times operating earnings cover the interest bill; falling coverage with flat EBIT means the debt got dearer",
            "interest expense is zero or unreported (7 of 8 held issuers stopped tagging InterestExpense after 2024 — the registry names the substitute)",
            "CFA Program, Financial Analysis Techniques — coverage ratios"),
    Reading("free_cash_flow", "the issuer's own prior periods; revenue for a margin",
            "no uniform definition (SEC C&DI 102.07): say it is operating cash flow less capex; a negative FCF in a year of heavy capex is an investment, not a loss, and the capex line says which",
            "a financial issuer (cash generation runs through the loan book)",
            "SEC Non-GAAP C&DI 102.07"),
    Reading("fcf_margin", "the issuer's sector and its own prior periods",
            "free cash flow per dollar of revenue; compare with net margin to see how much of earnings turns into cash",
            "revenue is zero; a financial issuer",
            "CFA Program, Financial Analysis Techniques"),
    Reading("capex_intensity", "the issuer's sector and its own prior periods",
            "capex per dollar of revenue; rising intensity with rising revenue is expansion, rising intensity with flat revenue is a heavier business",
            "revenue is zero",
            "CFA Program, Financial Analysis Techniques — activity ratios"),
    Reading("gross_margin", "the issuer's sector and its own prior periods",
            "what is left after the cost of what was sold; the first line where a demand or mix shift shows up in the numbers",
            "cost of revenue is not reported",
            "CFA Program, Financial Reporting — profitability ratios"),
    Reading("operating_margin", "the issuer's sector and its own prior periods",
            "profit after operating costs, before interest and tax; compare with gross margin to separate cost of goods from overhead",
            "operating income is not reported",
            "CFA Program, Financial Reporting — profitability ratios"),
    Reading("net_margin", "the issuer's sector and its own prior periods",
            "profit per dollar of revenue after everything; a gap from operating margin is interest, tax and non-operating items",
            "revenue is zero",
            "CFA Program, Financial Reporting — profitability ratios"),
    Reading("roe", "the issuer's sector and its own prior periods; decompose with DuPont",
            "return on the owners' capital; high ROE on thin equity is leverage, not profitability — read the equity multiplier beside it",
            "equity is negative (a loss over negative equity prints as a positive return)",
            "Damodaran, Return on Capital, Return on Invested Capital and Return on Equity: Measurement and Implications"),
    Reading("roic", "the issuer's sector and its own prior periods; the cost of capital",
            "return on all capital employed, before financing; the measure to compare across capital structures",
            "invested capital is zero or negative; a financial issuer",
            "Damodaran, Return on Capital, Return on Invested Capital and Return on Equity"),
    Reading("asset_turnover", "the issuer's sector",
            "revenue per dollar of assets; capital-intensive businesses turn slowly by construction, so compare within sector only",
            "total assets is zero",
            "CFA Program, Financial Analysis Techniques — activity ratios"),
    Reading("current_ratio", "the issuer's sector and its own prior periods",
            "current assets over current liabilities; a ratio under one is normal for issuers that collect before they pay (retail, subscription)",
            "an issuer without a classified balance sheet (banks, insurers)",
            "CFA Program, Financial Analysis Techniques — liquidity ratios"),
    Reading("accruals_ratio", "the issuer's own prior periods and its sector",
            "the share of earnings not backed by cash; persistently high accruals precede lower future earnings",
            "average net operating assets is zero",
            "Sloan (1996), Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?"),
    Reading("price.beta", "the benchmark named; the book's other holdings",
            "sensitivity of the name's daily return to the benchmark's; against a factor ETF (TLT, HYG) it is the name's sensitivity to that risk — the per-name measure the book-level regression does not give",
            "fewer than 60 aligned sessions; a benchmark whose returns are collinear with another factor's",
            "Sharpe (1964); CFA Program, Portfolio Management"),
    Reading("price.volatility", "the name's own longer windows; the index; the book's other holdings",
            "a short window (21d) reacts, a long one (252d) is the baseline; say which, and compare the two to say whether volatility is rising",
            "fewer than 20 sessions",
            "CFA Program, Quantitative Methods"),
    Reading("book.analysis", "the portfolio's own thresholds",
            "room_to_warning below zero means the check is already in warning; room_to_breach is what remains before the hard tier; a net beta says which way the book moves if the risk materialises, with the legs that make it up",
            "a run not completed; a collinear fit (legs not quotable individually, the net is)",
            "the portfolio's risk_limits; the factor model's own regression record"),
)}


# ── procedures: what a competent analyst does for a kind of question ──────────

@dataclass(frozen=True)
class Procedure:
    """One kind of question and the steps an analyst takes. A registry row the
    agent may follow or not; `describe` lists the ones that fit the subject."""
    name: str
    question: str
    subject_kind: str
    gather: tuple[str, ...]
    compute: tuple[str, ...]
    compare: tuple[str, ...]
    close: tuple[str, ...]
    absent: str
    authority: str

    def __post_init__(self) -> None:
        if self.subject_kind not in SUBJECT_KINDS + ("desk",):
            raise ValueError(f"{self.name}: subject_kind {self.subject_kind!r}")
        if not self.authority.strip():
            raise ValueError(f"{self.name}: a procedure states its authority")


PROCEDURES: dict[str, Procedure] = {p.name: p for p in (
    Procedure(
        "cut_one_name", "which holding to cut, and what the book looks like after", "portfolio",
        gather=("the run's weights, contributions and limit checks (read_book)", "each candidate's own measures if the question is about the business (compute issuer methods)"),
        compute=("rank the holdings by weight and by contribution", "book.sell for the candidate, so the after-book is a row"),
        compare=("the largest driver of risk against the smallest position — they are different names", "the after-book's checks against the before-book's"),
        close=("name the candidate and the reason it was chosen over the runner-up", "say what gets tighter and what gets better after the sale, from the scenario's checks"),
        absent="a candidate with no run figure is not a candidate; say so",
        authority="the mandate's own limits; concentration review practice",
    ),
    Procedure(
        "trim_to_tier", "how much of one holding to sell to bring it back under a concentration tier", "portfolio",
        gather=("the run's book market value, the holding's weight and market value, and the tier level (read_book by name: exposure_metrics.portfolio_market_value, issuer_exposures.<T>.market_value, limit_checks.issuer_concentration:<T>.warning_level or .breach_level)",),
        compute=("the tier in dollars: multiply(book market value, tier level)", "the sale: subtract(the holding's market value, the tier in dollars)", "or book.sell at a fraction, and read the after-book's check"),
        compare=("the sale against the holding's market value — a sale larger than the position, or negative, means the wrong tier or the wrong base was used",),
        close=("the dollars to sell and the weight it lands at, with the tier named", "what else in the book the sale touches (the after-book's checks if book.sell was run)"),
        absent="a holding with no check row for the tier asked has no tier to trim to; say so",
        authority="the mandate's own limits; the V22 route (a weight is a share of ITS book, so the tier in dollars is book value × tier)",
    ),
    Procedure(
        "bear_case_from_filings", "the bear case in the issuer's own words, ordered by which risk is live", "issuer",
        gather=("Item 1A and the MD&A (read_filings)", "gross margin, inventory, operating cash flow and revenue over the last 4-8 windows (read_fundamentals / compute)"),
        compute=("gross_margin, capex_intensity, days_inventory where filed", "the position's weight if the name is held (read_book)"),
        compare=("each named risk against the line where it would first appear: demand → gross margin and inventory; supply → capex and commitments; concentration → the customer note", "the trend of that line over the windows read"),
        close=("order the risks by which one the numbers already show, not by the filing's order", "say what to watch, by line item, and the position's weight so the reader knows what is at stake"),
        absent="a risk the filing names without a line the desk holds (e.g. backlog, customer share) is quoted from the filing, not estimated",
        authority="SEC Regulation S-K Item 105 (risk factors) and Item 303 (MD&A); Sloan (1996) on accruals as the first signal",
    ),
    Procedure(
        "diligence_sweep", "an open-ended review of one issuer: what stands out", "issuer",
        gather=("describe the issuer; the panel of measures (issuer.panel)", "the latest 10-K Items 1A and 7", "the price's momentum, volatility and drawdown (price methods)"),
        compute=("issuer.panel", "price.momentum_12_1, price.volatility, price.drawdown"),
        compare=("each measure against the issuer's own prior periods (read the series) and, where a peer is held, against it"),
        close=("three things that stand out, each with the figure and what would change the reading", "if held, the weight and the check it is nearest to"),
        absent="a measure the panel refused is listed with its reason, never replaced by a neighbour",
        authority="CFA Program, Financial Analysis Techniques (the analysis framework)",
    ),
    Procedure(
        "rates_scenario", "what a move in rates does to this book, name by name", "portfolio",
        gather=("the run's factor exposures and net betas (book.analysis)", "each holding's beta to TLT (price.beta with benchmark TLT) — the per-name sensitivity the book-level fit does not give", "the filings' own rate-sensitivity disclosure (Item 7A) for banks and issuers with floating debt"),
        compute=("book.analysis for the netted rates leg", "price.beta(benchmark=TLT) for each holding"),
        compare=("the explicit duration (TLT, HYG) against the equities' measured TLT betas", "the sign and size of each name's beta"),
        close=("where the shock bites, by name, in the order of measured sensitivity", "what is unmeasured (stress withheld; a collinear fit) and say so"),
        absent="a day's P&L contribution is NOT a rate sensitivity; if no beta can be fitted the name is unmeasured, not zero",
        authority="the factor model's regression record; Regulation S-K Item 305 (quantitative market-risk disclosure)",
    ),
    Procedure(
        "capital_allocation", "where the issuer's cash is going", "issuer",
        gather=("operating cash flow, capex, buybacks, dividends, debt repayment over the last 4 windows (read_fundamentals)", "revenue over the same windows"),
        compute=("each use as a share of operating cash flow (compute divide)", "free_cash_flow", "capex growth against revenue growth (series ops yoy, then subtract)"),
        compare=("the ordering of the uses", "the spread of capex growth over revenue growth", "the issuer's own prior year"),
        close=("which use dominates, whether it is accelerating, what it does to FCF", "if held, the position's weight"),
        absent="any of the five uses not filed: say which; do not substitute a neighbouring line",
        authority="SEC Non-GAAP C&DI 102.07 (FCF); CFA Program, Financial Analysis Techniques (cash-flow analysis)",
    ),
    Procedure(
        "name_outside_the_book", "can a name be analysed, and how does it compare with what is held", "issuer",
        gather=("describe the name (admissibility, what is prepared)", "the same measures for the name and for the held peers (compute over a list of subjects)", "the book's checks (read_book)"),
        compute=("the measure asked for, on the name and on the held names in one call", "rank across them", "book.buy at the proposed weight"),
        compare=("the name's place in the ranking of the held names", "the after-book's checks against the current ones"),
        close=("more or less levered (or whichever measure) than the median held name, with the place", "which check the addition would tighten"),
        absent="a name not prepared is started (start readiness) and said to be in preparation; nothing is estimated for it",
        authority="the mandate's own limits; peer-comparison practice",
    ),
    Procedure(
        "wrong_premise", "the user asserts a figure that is not what the desk holds", "portfolio",
        gather=("the run's figure the premise is about (read_book)",),
        compute=("rank if the premise is a superlative",),
        compare=("the asserted figure against the desk's figure, naming both",),
        close=("correct the premise first, with the figure; then answer the question as asked with the corrected figure",),
        absent="if the desk holds no figure for the premise, say so rather than agreeing or disagreeing",
        authority="the run's own rows",
    ),
    Procedure(
        "revenue_concentration", "how concentrated the issuer's revenue is", "issuer",
        gather=("the 10-K's product / segment / customer concentration passages (read_filings, Item 1 and Item 7; the customer note)", "total revenue (read_fundamentals)"),
        compute=("nothing: segment and product figures are not held as facts on this desk (not_held); the shares are the filing's own statements",),
        compare=("the filing's stated shares across years, if both years' filings are indexed",),
        close=("quote the filing's own sentence for the share, cited; say what the concentration is in (a franchise, a customer, a geography)", "if held, the weight"),
        absent="the share cannot be computed here; it is quoted or it is absent — never derived from parts",
        authority="ASC 280 (segment reporting); Regulation S-K Item 101(c) (major customers)",
    ),
    Procedure(
        "news_to_position", "what happened recently and whether it touches something held", "portfolio",
        gather=("search_web per held name, restricted to the period asked", "the run's weights and market values (read_book)", "the price over the period (price.window_return) to see whether the news is already in the price"),
        compute=("price.window_return over the period for the names touched",),
        compare=("each item against the name's weight: what is at stake", "the price move against the market's over the same days"),
        close=("which items touch a held name, the size of that position, and whether the price has already moved", "items that touch nothing held are said to touch nothing"),
        absent="a search that returns nothing specific is reported as nothing found, not as 'headline-level news'",
        authority="event-study practice (price reaction over the event window)",
    ),
    Procedure(
        "trigger_levels", "what would have to happen for the mandate's answer to flip", "portfolio",
        gather=("the checks with their tiers and the current values (read_book / book.analysis)", "the book's market value"),
        compute=("room to each tier (book.analysis)", "the dollars of room or excess: room × market value (compute multiply)", "the price move that closes the room for a single-name check: room ÷ weight"),
        compare=("the nearest check first (smallest room)",),
        close=("the level, in weight points, in dollars, and as a price move, for each check nearest its tier",),
        absent="a check that did not run (its input withheld) is listed as not run, not as clear",
        authority="the portfolio's risk_limits; limit-monitoring practice",
    ),
    Procedure(
        "thesis_check", "is what is held still the business it was bought as", "issuer",
        gather=("Item 1 (the business description) then and now (read_filings)", "the measures that define the business: capex_intensity, asset_turnover, gross_margin over the years held (compute)", "segment statements from the filing (not_held as figures)"),
        compute=("the defining measures over the years held (series ops)",),
        compare=("each measure's direction over the period against the thesis's claim",),
        close=("what changed and what did not, each with its figure; what the filing itself says the business is now",),
        absent="the segment mix is quoted from the filing; it is not held as a figure and is not derived",
        authority="ASC 280; the issuer's own Item 1",
    ),
    Procedure(
        "volatility_attribution", "has the book got jumpier, and is it the market or something held", "portfolio",
        gather=("the book's 30d and 60d volatility on the run and on earlier runs (read_book across runs)", "each holding's volatility over the short and long windows (price.volatility on the list of holdings)", "the index's volatility over the same windows"),
        compute=("price.volatility(21) and (252) for each holding and for SPY",),
        compare=("short against long window per name: whose volatility rose", "the book's rise against the index's"),
        close=("market-wide or specific, and which names, each with the two windows' figures",),
        absent="a name with too short a history is unmeasured, not quiet",
        authority="CFA Program, Quantitative Methods (volatility estimation)",
    ),
    Procedure(
        "peer_comparison", "how one issuer compares with another on one front", "issuer",
        gather=("the same measure for both, over the same windows (compute over a list of subjects)",),
        compute=("the measure per issuer per window", "the spread or the ratio between them (compute subtract / divide)", "rank if more than two"),
        compare=("level and slope: who is higher, and whose is moving faster",),
        close=("a sentence for the level, a sentence for the slope, and what that implies for the question asked — never a table with no sentence after it",),
        absent="an issuer whose input is not filed is listed as unmeasured on that line, not dropped",
        authority="CFA Program, Financial Analysis Techniques (cross-sectional analysis)",
    ),
)}


def procedures_for(subject_kind: str) -> list[Procedure]:
    return [p for p in PROCEDURES.values() if p.subject_kind == subject_kind]
