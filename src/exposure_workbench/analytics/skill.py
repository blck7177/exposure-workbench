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

from dataclasses import dataclass, field, replace

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
    "last_n": {"type": ["integer", "null"], "minimum": 2, "maximum": 16,
               "description": "the measure over its last N periods (months each) as ONE series, for yoy/cagr/trend; omitted = one value"},
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
        describes="annualised volatility of the last N daily returns; a short window reacts, a long one is the baseline",
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
        describes="a name's sensitivity to a benchmark: OLS beta, alpha and R² of its daily returns on the benchmark's (default SPY; TLT for rates, HYG for credit — the per-name sensitivity)",
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
        describes="average daily volume over the last N sessions, in shares a session and in dollars a session — the liquidity a position is measured against: a position's market value divided by dollar ADV is its days to liquidate",
        procedure="mean of daily volume, and of close × volume, over the window; sessions without volume dropped and counted",
        authority="average daily volume as the standard market-depth measure; days to liquidate = position ÷ (participation rate × dollar ADV), the days-to-cash framing of SEC Rule 22e-4",
        fails_when="fewer than 20 sessions (ADV_MIN_OBS) or no recorded volume",
        executor="price.adv", unit_class="count_per_day",
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
        describes="one run's factor exposures netted per risk (net beta), positions ordered by weight, and the room from every limit check to its warning and breach tiers",
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


# ── readings: what this DESK knows about reading a measure ───────────────────
#
# V25. Seventeen readings used to live here and fourteen were the textbook —
# "high ROE on thin equity is leverage, not profitability" — which the model
# already holds and never asked for (1 call in 23 across the 2026-09-06
# battery). A reading now states only what the desk knows and the textbook
# does not: a tag the held issuers stopped filing, a measure the book-level
# fit cannot give, a quantity this desk invented. Refusal conditions that were
# written here as prose ("EBITDA is zero or negative") are Formula data now
# (denominator_must_be_positive), where the evaluator applies them.

@dataclass(frozen=True)
class Reading:
    """What this desk knows about reading one measure that a textbook does not.
    Guidance for the agent's sentence, with its authority; nothing here reaches compute."""
    method: str
    reads: str
    meaningless_when: str
    authority: str

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(f"reading for unknown method {self.method!r}")
        if not self.authority.strip():
            raise ValueError(f"{self.method}: a reading states its authority")


READINGS: dict[str, Reading] = {r.method: r for r in (
    Reading("ebit_interest_coverage",
            "7 of the 8 held issuers stopped tagging InterestExpense after 2024; the registry substitutes "
            "the non-operating interest line and the result's definition names the substitution — say which "
            "line was used when the coverage is quoted",
            "interest expense is zero or unreported under both tags",
            "the desk's own corpus measurement (V9_FORMULA_BASIS); CFA Program, coverage ratios"),
    Reading("price.beta",
            "against a factor ETF (TLT for rates, HYG for credit) this is the name's own sensitivity to that "
            "risk — the per-name figure the book-level factor regression does not give; the book-level fit "
            "is over the BOOK's return and says nothing per name",
            "fewer than 60 aligned sessions; a benchmark whose returns are collinear with another factor's",
            "the factor model's regression record; Sharpe (1964)"),
    Reading("book.analysis",
            "room_to_warning below zero means the check is already in warning; room_to_breach is what remains "
            "before the hard tier; a net beta is this desk's netting of the legs, and TLT and HYG enter with "
            "the sign opposite to the risk they proxy",
            "a run not completed; a collinear fit (the legs are not quotable individually, the net is)",
            "the portfolio's risk_limits; the factor model's own regression record"),
)}


# ── the desk's rules: its own facts and policies, which a textbook does not carry ─
#
# The reference layer (V25). Every skill below leans on these; they are written
# once and rendered with describe, scoped to the subject's kind. A rule is a
# fact about THIS desk — how it defines a measure, what it holds, what it will
# not do — never an explanation of finance.

@dataclass(frozen=True)
class Rule:
    scope: str          # all | issuer | book
    rule: str
    authority: str

    def __post_init__(self) -> None:
        if self.scope not in ("all", "issuer", "book"):
            raise ValueError(f"rule scope {self.scope!r}")
        if not self.authority.strip():
            raise ValueError("a rule states its authority")


DESK_RULES: tuple[Rule, ...] = (
    # policies
    Rule("all", "Every figure stated is a fact a tool returned. A figure the desk does not hold is an "
                "absence, said as such with its reason — never a nearby figure under the asked-for name, "
                "never an estimate.", "the desk's evidence discipline (services/gate)"),
    Rule("all", "The desk does not forecast. Asked for next year's figure, it says so and gives what the "
                "issuer's own filings say would move the figure either way.", "the desk's mandate"),
    Rule("all", "No measure carries a threshold. A number is laid out with what it is compared against "
                "and the reading belongs to the reader.", "decision of 2026-08-24 (test_no_formula_carries_a_threshold)"),
    Rule("all", "A premise the user asserts is checked against the desk's figure first and corrected with "
                "it before the question is answered; a premise the desk holds no figure for is neither "
                "agreed with nor denied.", "the desk's evidence discipline"),
    Rule("all", "A comparison is one measure over the same windows: level first, then slope, then what it "
                "means for the question — never a table with no sentence after it.",
         "CFA Program, Financial Analysis Techniques (cross-sectional analysis)"),
    # issuer facts: how this desk defines and holds things
    Rule("issuer", "EBIT and EBITDA start from NET INCOME, adding back interest and tax — not from operating "
                   "income. Where an issuer carries large non-operating income the two differ, and a "
                   "correct EBIT is then mostly non-operating.", "SEC C&DI 103.01, 103.02"),
    Rule("issuer", "Free cash flow is operating cash flow less capital expenditures, and the definition is "
                   "stated beside the number because it has no uniform one.", "SEC C&DI 102.07"),
    Rule("issuer", "Credit measures built on interest (coverage, leverage) are refused for a financial issuer: "
                   "interest is a bank's operating cost and deposits its raw material. ROE, ROA and the "
                   "accruals ratio do apply to banks.", "the formula registry's not_for_financials"),
    Rule("issuer", "Segment, product, geographic and customer-concentration figures are not held as facts; "
                   "they are quoted from the filing's own sentences, cited, never derived from parts.",
         "ASC 280; Regulation S-K Item 101(c)"),
    Rule("issuer", "A name the desk has not prepared is started (readiness) and said to be in preparation; "
                   "nothing is estimated for it meanwhile.", "the desk's readiness pipeline"),
    # book facts: how this desk defines and holds things
    Rule("book", "A weight is a share of ITS book's market value and of nothing else: a tier in dollars is "
                 "the book's market value × the tier, and two books' weights are compared by difference, "
                 "never summed.", "the book algebra (V22)"),
    Rule("book", "TLT and HYG are the desk's explicit rates and credit instruments; they carry duration and "
                 "spread directly, and in the netted factor exposure they enter with the sign opposite to "
                 "the risk they proxy. Equities carry only a measured sensitivity.",
         "the factor model's regression record"),
    Rule("book", "A day's P&L contribution is not a sensitivity. A name's rate or credit sensitivity is its "
                 "beta to TLT or HYG; a name whose beta cannot be fitted is unmeasured, never zero.",
         "the factor model's regression record"),
    Rule("book", "A scenario (a hypothetical sale or purchase) re-runs the concentration and exposure checks "
                 "on the after-book; it does not re-fit betas, volatility or P&L, which are stated unmeasured.",
         "scenario_service"),
    Rule("book", "Value at risk, expected shortfall and the stress results are computed by the run and "
                 "withheld from every surface pending validation; say so if asked, do not rebuild them "
                 "from other figures.", "analytics/withheld"),
    Rule("book", "Liquidity is read as days to liquidate: a position's market value over the dollars a day "
                 "the name trades, at a participation rate the reading states. The desk fixes no rate; the "
                 "user's, or none, and the answer says which.",
         "SEC Rule 22e-4 (liquidity expressed as days to convert to cash); average daily volume as the market-depth measure"),
)


def rules_for(scope: str) -> list[Rule]:
    return [r for r in DESK_RULES if r.scope in ("all", scope)]


# ── the analyst's domains: one skill per domain, in the analyst's words ───────
#
# V25. The fourteen procedures that were here described CALL CHAINS — "read_book
# by name: exposure_metrics.portfolio_market_value", "series ops yoy, then
# subtract" — and the 2026-09-06 battery opened none of them in twenty turns:
# knowledge written as a script for one tool surface is knowledge bound to the
# LLM loop. A domain skill is written the way an analyst holds it: the words a
# user uses for the question, the evidence the question turns on (named as the
# method cards name it), what THIS desk knows about that domain that a
# textbook does not, what to compare, how to close, and what is absent here.
# No tool is named. The set is the analyst's working surface — an issuer read
# in S&P's order (financial risk, business risk, modifiers) plus its price;
# a book read in the risk-management order (composition, limits, trades,
# market risk, drawdown and attribution, liquidity, events) — so a question
# never asked still lands in a domain.

@dataclass(frozen=True)
class Procedure:
    """One domain of the analyst's work, as knowledge: what the question sounds
    like, what evidence it turns on, what this desk knows about it, how it is
    compared and closed, and what is absent here. Read by the agent; never executed."""
    name: str
    question: str
    subject_kind: str
    triggers: tuple[str, ...]
    evidence: tuple[str, ...]
    desk: tuple[str, ...]
    compare: tuple[str, ...]
    close: tuple[str, ...]
    absent: str
    authority: str
    # V27: the domain's leaves BY NAME — the methods it turns on (registry names,
    # checked here) and what it reads (run figure groups, filed lines, filing
    # items, sections; checked against services/name_table by test, since this
    # module imports no service). The 2026-09-07 battery opened a domain card
    # 3 times in 140 turns and matched its evidence sentences to method names
    # by meaning; a domain that names its leaves can be opened as one node with
    # every leaf carrying its call.
    methods: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    # V30 Phase C: the domain's knowledge in the form the model reuses — short
    # programs in the desk's language (docs/PROGRAM_LANGUAGE.md), each a
    # (title, program-JSON) pair with <port> / <T> / <T1>,<T2> placeholders.
    # Knowledge written as an example is copied; knowledge written as prose was
    # opened 3 times in 140 turns (V26 P14b). Every snippet parses at import and
    # executes on the fixture (test_v30_skill_programs).
    programs: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.subject_kind not in SUBJECT_KINDS + ("desk",):
            raise ValueError(f"{self.name}: subject_kind {self.subject_kind!r}")
        unknown = [m for m in self.methods if m not in METHODS]
        if unknown:
            raise ValueError(f"{self.name}: methods not in the registry: {unknown}")
        if not isinstance(self.reads, tuple) or not isinstance(self.methods, tuple):
            raise ValueError(f"{self.name}: methods and reads are tuples of names")
        for seg in ("triggers", "evidence", "compare", "close"):
            if not isinstance(getattr(self, seg), tuple) or not getattr(self, seg):
                raise ValueError(f"{self.name}: {seg} is a non-empty tuple of sentences")
        if not isinstance(self.desk, tuple):
            raise ValueError(f"{self.name}: desk is a tuple of sentences (may be empty)")
        if not self.authority.strip():
            raise ValueError(f"{self.name}: a procedure states its authority")


PROCEDURES: dict[str, Procedure] = {p.name: p for p in (
    # ── issuer: financial risk, in the order the desk reads a company ────────
    Procedure(
        "issuer_earnings_quality", "are the profits real: is cash showing up behind earnings, and is working capital telling a different story", "issuer",
        triggers=("is the cash actually showing up behind the earnings", "are the profits real",
                  "are receivables and inventory growing faster than the top line", "put that in days",
                  "is that one odd quarter or has it been building"),
        evidence=("operating cash flow beside net income over the same windows, and their ratio (cash conversion)",
                  "the accruals ratio and its own history",
                  "receivables, inventory and revenue growth over the same windows; days sales outstanding, days inventory, days payable and the cash conversion cycle",
                  "capex and stock-based compensation where the gap between cash and earnings needs a reason"),
        desk=("days measures are built on ending balances, not averages, and the result says so",
              "a measure over its last N periods is one series, so a trend is read from the series, not from two figures"),
        compare=("cash conversion and the accruals ratio against the issuer's own prior periods: the evidence is about persistence, not one period",
                 "receivable and inventory growth against revenue growth over the same windows",
                 "days against the same days a year earlier"),
        close=("say whether cash confirms earnings, and if not which line explains the gap and whether it is building",
               "give the days as days, dated, beside the prior reading"),
        absent="a quarter the issuer did not file at the window asked is unreachable and stays in place in the series, never closed over",
        authority="Sloan (1996), Do Stock Prices Fully Reflect Information in Accruals and Cash Flows; Lev & Thiagarajan (1993), Fundamental Information Analysis (inventory and receivables relative to sales); CFA Program, Financial Analysis Techniques (activity ratios)",
    ),
    Procedure(
        "issuer_profitability", "how profitable the issuer is, at which line, against whom, and whether it is mix, pricing or cost", "issuer",
        triggers=("how profitable is X next to Y", "whose gross margin is holding up better", "is that mix or pricing",
                  "which is the best business by that measure", "does the ranking hold on return on capital"),
        evidence=("gross, operating and net margin over the same windows for every name compared",
                  "ROE, ROA, ROIC and the DuPont legs (net margin, asset turnover, equity multiplier) when the question is about returns",
                  "the same measure on the same windows for each name, then the ordering"),
        desk=("the margins name which revenue line they divided by; issuers that report revenue under two tags are read on the one the registry chose",
              "an ordering is a computation with a row: a superlative in the answer rests on the ranking, not on reading the figures by eye"),
        compare=("level and slope for each name over the same windows: who is higher, whose is moving",
                 "gross against operating margin to separate cost of goods from overhead; net against operating to isolate interest, tax and non-operating items",
                 "a ranking on one measure against the same ranking on another, when the question asks whether it holds"),
        close=("a sentence for the level, a sentence for the slope, and what that implies for the question asked",
               "name the runner-up and the gap when a name is called the best"),
        absent="an issuer whose input is not filed on a line is unmeasured on that line and stays in the comparison as such, never dropped",
        authority="CFA Program, Financial Reporting (profitability ratios); Damodaran, Return on Capital, Return on Invested Capital and Return on Equity",
    ),
    Procedure(
        "issuer_credit_and_balance_sheet", "how much debt the issuer carries against what it earns, how well it covers it, and how much room the balance sheet has", "issuer",
        triggers=("is it more or less levered than what we own", "how strong is the balance sheet",
                  "which of the two has more room to keep spending", "can it cover its interest",
                  "how liquid is the company itself"),
        evidence=("total debt, net debt, debt to EBITDA and to operating cash flow, FCF to debt",
                  "EBIT interest coverage",
                  "the current and quick ratios for the near-term",
                  "the same measures on the held peers when the question is relative"),
        desk=("total debt is the widest non-overlapping set of reported debt components, and the result lists what was left out at the date",
              "interest coverage may rest on a substituted interest line; the definition names it",
              "coverage and leverage are refused for a financial issuer, and the refusal says why"),
        compare=("against the issuer's own prior periods first, then against the median of the held names on the same measure",
                 "gross and net leverage side by side, with the cash line that was netted",
                 "coverage against the trend of EBIT: falling coverage with flat EBIT means the debt got dearer"),
        close=("more or less levered than the comparison named, with the place and the figures",
               "what would have to change in earnings or debt for the reading to flip"),
        absent="debt maturities, covenants and undrawn facilities are not held as figures; where the filing states them they are quoted",
        authority="S&P Global Ratings corporate methodology (financial risk profile: cash flow/leverage); CFA Program, solvency and coverage ratios",
    ),
    Procedure(
        "issuer_capital_allocation", "where the issuer's cash goes and whether the spending is outrunning what supports it", "issuer",
        triggers=("where is the cash actually going", "is capex growing faster than revenue", "is it over-investing relative to what it depreciates",
                  "buybacks, dividends, paying down debt: the shape of it", "can it keep doing this"),
        evidence=("operating cash flow and each use of it — capex, buybacks, dividends, debt repayment — over the same windows, each as a share of operating cash flow",
                  "free cash flow and FCF margin",
                  "capex intensity, and capex against depreciation and amortisation",
                  "capex growth against revenue growth over the same windows"),
        desk=("a use of cash the issuer did not file is said to be missing; a neighbouring line is never substituted for it",
              "free cash flow is operating cash flow less capex by definition, so a negative figure with capex above operating cash flow is the capex line, and the result names it"),
        compare=("the ordering of the uses and whether it changed from the prior year",
                 "the spread of capex growth over revenue growth, and capex over depreciation, over several windows",
                 "the same shape on the peer when two issuers are compared"),
        close=("which use dominates, whether it is accelerating, and what it does to free cash flow",
               "if held, the position's weight, so the reader knows what is at stake"),
        absent="the return on the capex is not measurable from the filings; the desk says what the spending is doing to cash and margins, not what it will earn",
        authority="SEC C&DI 102.07 (free cash flow); CFA Program, Financial Analysis Techniques (cash-flow analysis); S&P financial policy modifier",
    ),
    # ── issuer: business risk, in the issuer's own words ────────────────────
    Procedure(
        "issuer_business_risk_from_filings", "what the issuer itself says can go wrong, how concentrated the business is, and whether it is still the business it was", "issuer",
        triggers=("make me the bear case from their own filings", "which risk would show up in the numbers first",
                  "how concentrated is the revenue", "is what we own still the same business", "how would I see that in the numbers"),
        evidence=("Item 1A and the MD&A: the named risks, in the issuer's words",
                  "Item 1 then and now, when the question is whether the business changed",
                  "the segment, product, customer and geographic passages for concentration",
                  "for each named risk, the line where it would first appear and that line's trend: demand in gross margin and inventory, supply in capex and commitments, concentration in the customer note"),
        desk=("concentration figures are quoted from the filing and cited, never computed from parts",
              "the defining measures of a business — capex intensity, asset turnover, gross margin — are read over the years held as series"),
        compare=("each named risk against the trend of the line where it shows, so the risks are ordered by what the numbers already show, not by the filing's order",
                 "the filing's stated shares across years where both years are indexed",
                 "each defining measure's direction against the thesis's claim"),
        close=("the risks in the order the numbers rank them, each with the line to watch",
               "what changed and what did not, with the filing's own sentence for what the business is now",
               "if held, the position's weight"),
        absent="a risk the filing names without a line the desk holds (backlog, customer share, supplier terms) is quoted, not estimated",
        authority="Regulation S-K Items 101, 105 and 303; ASC 280; S&P Global Ratings corporate methodology (business risk profile); Lev & Thiagarajan (1993) for the lines a risk shows in first (gross margin, inventory, receivables, capex)",
    ),
    # ── issuer: the price, and the boundary of what the desk will say ───────
    Procedure(
        "issuer_price_context", "where the price sits against its own history and the market, and what that says about what is already in it", "issuer",
        triggers=("where is it trading against its last twelve months", "near the high or the low", "its momentum with the last month left out",
                  "has it been jumpier", "how has it done against the market"),
        evidence=("distance from the 52-week high, with the date the high was set",
                  "12-1 momentum, the last month skipped",
                  "volatility over a short and a long window",
                  "the window return and the return relative to a benchmark",
                  "the deepest drawdown over the window and whether it was regained"),
        desk=("every price measure is over the adjusted close; the dollar volume is over the as-traded close",
              "each price measure states its observation floor and is refused, never shortened, below it"),
        compare=("the short window against the long: a short window reacts, a long one is the baseline",
                 "the name's return against the benchmark's over the same window",
                 "the name against the book's other holdings on the same measure"),
        close=("what the price has already moved on, dated, and what would be new information",
               "never a view on where the price goes"),
        absent="valuation multiples (P/E, EV/EBITDA, FCF yield) are not yet measures on this desk; say so rather than deriving one in prose",
        authority="Jegadeesh & Titman (1993); George & Hwang (2004); CFA Program, Quantitative Methods",
    ),
    Procedure(
        "issuer_outlook_boundary", "what the desk will and will not say about the future, and what the issuer's own filings say would move it", "issuer",
        triggers=("what is your estimate for next year", "what would move revenue either way", "if you could ask management one question",
                  "what are the catalysts", "is the guidance consistent"),
        evidence=("the filings' own forward-looking passages: guidance, stated drivers, the outlook section of the MD&A",
                  "the measures whose recent trend contradicts or confirms the narrative",
                  "what happened recently, from the web, for anything after the last filing"),
        desk=("the desk does not forecast; asked for a number about the future it says so and gives what the filings say would move the figure",
              "the one question for management is built from the line the numbers show moving, not from the narrative"),
        compare=("management's stated drivers against the lines that have actually moved",
                 "the same statement across filings for consistency"),
        close=("the drivers, each with the line it shows in and that line's recent direction",
               "one question, phrased so the answer would be a number the filings do not yet hold"),
        absent="a projected figure is absent by policy, not by data; say the policy",
        authority="the desk's mandate; buy-side practice on reading management statements against the numbers",
    ),
    # ── the book: composition, limits, trades ───────────────────────────────
    Procedure(
        "book_composition", "what the book is made of, how concentrated it is, and how that has drifted", "portfolio",
        triggers=("what is my largest exposure", "what share do the top five carry", "has the sector shape drifted",
                  "are we quietly all in one trade", "tighter or looser than the run before"),
        evidence=("every position's weight and market value on the latest run, ordered",
                  "the sum of the top N weights",
                  "sector weights on the run",
                  "the same figures on the prior run, for the change"),
        desk=("a figure on one run and the same figure on another are compared by difference; they are never summed",
              "the book's own market value is a figure of the run and the base every weight is a share of"),
        compare=("the top-N share against the prior run's",
                 "each sector's weight against its prior weight, so drift is the change, not the level",
                 "the largest name against the runner-up"),
        close=("the shape in three figures: the largest, the top-N share, the largest sector, each with its change since the prior run",
               "which single move would change the shape most, from the weights"),
        absent="ownership as a share of the issuer's float and crowding are not held; say so",
        authority="the run's own rows; concentration review practice",
    ),
    Procedure(
        "book_limits_and_triggers", "where the book stands against its mandate, and what would have to happen for a check to trip", "portfolio",
        triggers=("are we ok on concentration", "which limits am I closest to", "how much room is left",
                  "what would have to happen for that to flip", "give me the levels"),
        evidence=("every limit check on the run with its current value, warning and breach tiers, and the room to each",
                  "the book's market value, for room in dollars",
                  "the position's weight, for the price move that closes the room on a single-name check"),
        desk=("room below zero is a check already in warning; the hard tier is the breach level",
              "a check that did not run because its input is withheld is listed as not run, never as clear",
              "the tier in dollars is the book's market value × the tier; the price move that closes a single-name check's room is the room over the name's weight"),
        compare=("the nearest check first, by smallest room",
                 "the same check on the prior run, for direction"),
        close=("the level for each check nearest its tier, in weight points, in dollars and as a price move",
               "which check trips first and on what"),
        absent="a limit the mandate does not define has no check and no room; say the mandate has none",
        authority="the portfolio's risk_limits; limit-monitoring practice",
    ),
    Procedure(
        "book_hypothetical_trades", "what the book looks like after a sale or a purchase, and what gets tighter or better", "portfolio",
        triggers=("which one goes", "say I sell that one, where does that leave concentration", "if we put 5% into it does anything get tight",
                  "how much do I sell to get back under the tier", "how do I take that down without selling the biggest position"),
        evidence=("the before-book: weights, contributions and every check",
                  "the after-book as a scenario row: renormalised weights, sector weights, market value and every check re-run",
                  "the candidates' own measures when the choice is about the business, not the risk",
                  "the sale that lands a name at a tier: the holding's market value less the tier in dollars"),
        desk=("a scenario chains: a sale, then a purchase on its result, each a row read like a run",
              "a scenario re-runs the checks and does not re-fit betas, volatility or P&L; those are stated unmeasured",
              "a sale larger than the position, or negative, means the wrong tier or the wrong base was used",
              "a name already held is trimmed or added to through its weight, never bought again"),
        compare=("the after-book's checks against the before-book's: what tightens, what loosens",
                 "the largest driver of risk against the smallest position — they are different names",
                 "the candidate against the runner-up on the measure the choice rests on"),
        close=("the name and the reason it was chosen over the runner-up",
               "the dollars to sell and the weight it lands at, with the tier named",
               "what else the trade touches, from the after-book's checks"),
        absent="a candidate with no run figure is not a candidate; a name the desk cannot place in a sector cannot be bought in a scenario",
        authority="the mandate's own limits; the book algebra (V22)",
    ),
    # ── the book: market risk, drawdown and attribution, liquidity, events ──
    Procedure(
        "book_market_risk", "what the book is exposed to, name by name, and whether it has got riskier", "portfolio",
        triggers=("rates back up 100bp, where does it bite", "is that us owning TLT or the equities being long duration in disguise",
                  "has our volatility gone up", "is it the market or something we are holding", "what are we exposed to"),
        evidence=("the run's factor exposures and the netted beta per risk",
                  "each holding's own sensitivity to the rates and credit instruments, and to the market",
                  "each holding's volatility over a short and a long window, and the index's over the same",
                  "the book's own volatility on this run and earlier runs",
                  "the filings' own rate-sensitivity disclosure (Item 7A) for banks and floating-rate borrowers"),
        desk=("TLT and HYG carry explicit duration and spread; equities carry only a measured sensitivity, per name",
              "a day's P&L contribution is not a sensitivity; an unfittable beta is unmeasured, never zero",
              "the netted exposure enters TLT and HYG with the sign opposite to the risk they proxy",
              "stress results are withheld pending validation and are not rebuilt from betas"),
        compare=("the explicit duration against the equities' measured sensitivities: which side of the exposure is which",
                 "each name's short-window volatility against its long: whose rose",
                 "the book's rise against the index's over the same windows: market-wide or specific"),
        close=("where the shock bites, name by name, in the order of measured sensitivity, with what is unmeasured",
               "market-wide or specific, and which names, each with the two windows' figures"),
        absent="correlations between holdings and hidden common bets are not measures on this desk; a collinear fit is stated as such",
        authority="the factor model's regression record; Regulation S-K Item 305; CFA Program, Quantitative Methods",
    ),
    Procedure(
        "book_drawdown_and_attribution", "how the book fell and recovered, and how much of what it did was the market against what was held", "portfolio",
        triggers=("walk me through the worst drawdown", "how deep, how fast, did we get it back", "what was driving it",
                  "how much is just the market moving and how much is us", "why did the book move on the last run"),
        evidence=("every drawdown episode of the book over the span, deepest first, with trough and recovery dates",
                  "the book's return and each holding's contribution between a peak and a trough",
                  "one day's move reconciled: position contributions against the day's return, factor-explained share against the residual",
                  "the book's return against the market's over the same window"),
        desk=("episodes are found on today's holdings replayed over the span, and the answer says so",
              "a reconciliation whose position identity does not hold within tolerance reports no share of the move at all"),
        compare=("the episode's depth and length against the market's over the same dates",
                 "the factor-explained share against the residual: the market against us",
                 "each holding's contribution against its weight: who hurt more than their size"),
        close=("depth, dates and recovery in one sentence, then the names that made it, then market against specific",
               "what the share not explained by factors is made of, by name"),
        absent="a period with fewer sessions than the span needs has no episodes; a day without a completed run has no reconciliation",
        authority="the standard drawdown definition (Magdon-Ismail et al., 2004); Brinson-style position attribution; the factor model's decomposition",
    ),
    Procedure(
        "book_liquidity", "how fast the book can be sold down, and which names would hurt", "portfolio",
        triggers=("if I had to get out in a hurry which positions hurt", "liquidity not price", "how many days at a quarter of daily volume",
                  "how long to sell that down", "which names are hard to exit"),
        evidence=("each position's market value on the run",
                  "each name's dollars a day traded over the window, and shares a day",
                  "days to liquidate: the position over the dollars a day at the participation rate"),
        desk=("the participation rate is the user's or is stated with the figure; the desk fixes none, and the window (20, 30 or 60 sessions) is stated",
              "days come from the algebra — a position over a daily flow is a count of days — and a position over anything else is not days"),
        compare=("names ordered by days to liquidate, largest first",
                 "the same name at a lower participation rate, when the question is a hurry",
                 "days against the position's weight: a large weight with few days is size, not liquidity"),
        close=("the names that would hurt, each with its days at the stated rate, and the total the book could clear in a day",
               "whether the problem is one name or the book"),
        absent="a name with fewer sessions of recorded volume than the window is unmeasured, not liquid; the ETFs' underlying liquidity is not looked through",
        authority="SEC Rule 22e-4 (liquidity as days to convert to cash); average daily volume as the market-depth measure",
    ),
    Procedure(
        "book_events", "what happened recently, whether it touches something held, and whether the price already moved on it", "portfolio",
        triggers=("anything happen in the last week that matters for what we hold", "which of those touches a position",
                  "how big is that position", "is that already in the price", "what is coming up"),
        evidence=("recent items about each held name, restricted to the period asked",
                  "the run's weights and market values for what is at stake",
                  "the name's return over the period against the market's, to see whether the news is in the price"),
        desk=("an item is tied to a position by the name it touches and the weight of that position; an item that touches nothing held is said to touch nothing",
              "a search that returns nothing specific is reported as nothing found, not as headline-level news"),
        compare=("each item against the position's weight: what is at stake",
                 "the price move over the event window against the market's"),
        close=("which items touch a held name, the size of that position, and whether the price has already moved",
               "what would change the reading: an item that would touch the largest position"),
        absent="an earnings calendar is not held; dates are quoted from the filing or the web, not inferred",
        authority="event-study practice (price reaction over the event window)",
    ),
)}


# The leaves of each domain, by name. One table beside the declarations so a
# reviewer sees every link at once; a domain missing here is a construction
# error, not a silently leafless card.
_LINKS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "issuer_earnings_quality": (
        ("accruals_ratio", "accruals", "days_sales_outstanding", "days_inventory", "days_payable", "cash_conversion_cycle"),
        ("operating_cash_flow", "net_income", "accounts_receivable", "inventory", "revenue", "capex", "sbc")),
    "issuer_profitability": (
        ("gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic", "asset_turnover", "equity_multiplier",
         "tax_burden", "issuer.panel"),
        ("revenue", "gross_profit", "operating_income", "net_income")),
    "issuer_credit_and_balance_sheet": (
        ("total_debt", "net_debt", "debt_to_ebitda", "net_debt_to_ebitda", "debt_to_operating_cash_flow", "fcf_to_debt",
         "ebit_interest_coverage", "current_ratio", "quick_ratio"),
        ("long_term_debt_total", "cash_and_equivalents", "interest_expense", "current_assets", "current_liabilities")),
    "issuer_capital_allocation": (
        ("free_cash_flow", "fcf_margin", "capex_intensity"),
        ("operating_cash_flow", "capex", "buybacks", "dividends_paid", "depreciation_amortization", "revenue")),
    "issuer_business_risk_from_filings": (
        ("capex_intensity", "asset_turnover", "gross_margin"),
        ("1A", "7", "1", "gross_profit", "inventory", "accounts_receivable", "capex")),
    "issuer_price_context": (
        ("price.distance_from_52w_high", "price.momentum_12_1", "price.volatility", "price.window_return", "price.drawdown"),
        ()),
    "issuer_outlook_boundary": ((), ("7",)),
    "book_composition": ((), ("concentration", "whole_book")),
    "book_limits_and_triggers": ((), ("mandate", "whole_book", "concentration")),
    "book_hypothetical_trades": (("book.sell", "book.buy"), ("concentration", "mandate", "attribution")),
    "book_market_risk": (("price.beta", "price.volatility", "book.analysis"), ("factor_exposure", "risk", "7A")),
    "book_drawdown_and_attribution": (
        ("book.drawdown_episodes", "book.explain_episode", "book.reconcile", "price.window_return"),
        ("attribution", "risk")),
    "book_liquidity": (("price.adv",), ("concentration",)),
    "book_events": (("price.window_return",), ("concentration",)),
}
_PROGRAMS: dict[str, tuple[tuple[str, str], ...]] = {'issuer_earnings_quality': (('cash behind earnings: the trailing twelve months, then the last five fiscal years', '{"let":[["accr_now",{"fn":"method","name":"accruals_ratio","subject":"<T>"}],["ocf_now",{"fn":"fundamentals","ticker":"<T>","metric":"operating_cash_flow","months":12}],["ni_now",{"fn":"fundamentals","ticker":"<T>","metric":"net_income","months":12}],["conversion_now",{"fn":"div","a":"$ocf_now","b":"$ni_now"}],["ocf",{"fn":"fundamentals","ticker":"<T>","metric":"operating_cash_flow","months":12,"last_n":5}],["ni",{"fn":"fundamentals","ticker":"<T>","metric":"net_income","months":12,"last_n":5}],["conversion",{"fn":"div","a":"$ocf","b":"$ni"}],["accr",{"fn":"method","name":"accruals_ratio","subject":"<T>","params":{"last_n":8}}],["accruals_trend",{"fn":"yoy","of":"$accr"}]]}'), ('working capital in days: the trailing twelve months, then the fiscal-year history', '{"let":[["dso_now",{"fn":"method","name":"days_sales_outstanding","subject":"<T>"}],["dinv_now",{"fn":"method","name":"days_inventory","subject":"<T>"}],["ccc_now",{"fn":"method","name":"cash_conversion_cycle","subject":"<T>"}],["dso",{"fn":"method","name":"days_sales_outstanding","subject":"<T>","params":{"last_n":5}}],["dinv",{"fn":"method","name":"days_inventory","subject":"<T>","params":{"last_n":5}}],["dinv_change",{"fn":"yoy","of":"$dinv"}]]}')), 'issuer_profitability': (('margins across names, then the ordering', '{"let":[["gm",{"fn":"method","name":"gross_margin","subject":["<T1>","<T2>"]}],["om",{"fn":"method","name":"operating_margin","subject":["<T1>","<T2>"]}],["nm",{"fn":"method","name":"net_margin","subject":["<T1>","<T2>"]}],["best_gm",{"fn":"rank","of":"$gm","direction":"highest"}],["ret_capital",{"fn":"method","name":"roic","subject":["<T1>","<T2>"]}],["best_roic",{"fn":"rank","of":"$ret_capital","direction":"highest"}]]}'), ('a margin over its own history', '{"let":[["gm",{"fn":"method","name":"gross_margin","subject":"<T>","params":{"last_n":8}}],["gm_change",{"fn":"yoy","of":"$gm"}]]}'), ('DuPont', '{"let":[["ret_equity",{"fn":"method","name":"roe","subject":"<T>"}],["nm",{"fn":"method","name":"net_margin","subject":"<T>"}],["turn",{"fn":"method","name":"asset_turnover","subject":"<T>"}],["lev",{"fn":"method","name":"equity_multiplier","subject":"<T>"}]]}')), 'issuer_credit_and_balance_sheet': (('leverage and coverage across names', '{"let":[["td",{"fn":"method","name":"total_debt","subject":["<T1>","<T2>"]}],["nd",{"fn":"method","name":"net_debt","subject":["<T1>","<T2>"]}],["lev",{"fn":"method","name":"net_debt_to_ebitda","subject":["<T1>","<T2>"]}],["cov",{"fn":"method","name":"ebit_interest_coverage","subject":["<T1>","<T2>"]}],["cr",{"fn":"method","name":"current_ratio","subject":["<T1>","<T2>"]}],["most_levered",{"fn":"rank","of":"$lev","direction":"highest"}]]}'), ("leverage against the issuer's own history", '{"let":[["lev",{"fn":"method","name":"debt_to_ebitda","subject":"<T>","params":{"last_n":5}}],["lev_change",{"fn":"yoy","of":"$lev"}]]}')), 'issuer_capital_allocation': (('where the cash goes, each use as a share of operating cash flow', '{"let":[["ocf",{"fn":"fundamentals","ticker":"<T>","metric":"operating_cash_flow","months":12}],["capex",{"fn":"fundamentals","ticker":"<T>","metric":"capex","months":12}],["buybacks",{"fn":"fundamentals","ticker":"<T>","metric":"buybacks","months":12}],["dividends",{"fn":"fundamentals","ticker":"<T>","metric":"dividends_paid","months":12}],["capex_share",{"fn":"div","a":"$capex","b":"$ocf"}],["buyback_share",{"fn":"div","a":"$buybacks","b":"$ocf"}],["dividend_share",{"fn":"div","a":"$dividends","b":"$ocf"}],["fcf",{"fn":"method","name":"free_cash_flow","subject":"<T>"}]]}'), ('is capex outrunning revenue', '{"let":[["capex",{"fn":"fundamentals","ticker":"<T>","metric":"capex","months":12,"last_n":5}],["rev",{"fn":"fundamentals","ticker":"<T>","metric":"revenue","months":12,"last_n":5}],["capex_g",{"fn":"yoy","of":"$capex"}],["rev_g",{"fn":"yoy","of":"$rev"}],["intensity",{"fn":"method","name":"capex_intensity","subject":"<T>","params":{"last_n":5}}]]}')), 'issuer_business_risk_from_filings': (('the lines a named risk shows in first, over the years', '{"let":[["gm",{"fn":"method","name":"gross_margin","subject":"<T>","params":{"last_n":8}}],["intensity",{"fn":"method","name":"capex_intensity","subject":"<T>","params":{"last_n":8}}],["turn",{"fn":"method","name":"asset_turnover","subject":"<T>","params":{"last_n":8}}],["inv",{"fn":"fundamentals","ticker":"<T>","metric":"inventory","last_n":8}]]}'),), 'issuer_price_context': (('where the price sits', '{"let":[["from_high",{"fn":"method","name":"price.distance_from_52w_high","subject":"<T>"}],["mom",{"fn":"method","name":"price.momentum_12_1","subject":"<T>"}],["vol_short",{"fn":"method","name":"price.volatility","subject":"<T>","params":{"window_days":30}}],["vol_long",{"fn":"method","name":"price.volatility","subject":"<T>","params":{"window_days":252}}],["ret_1y",{"fn":"method","name":"price.window_return","subject":"<T>","params":{"window":"1y","benchmark":"SPY"}}],["dd",{"fn":"method","name":"price.drawdown","subject":"<T>","params":{"window":"1y"}}]]}'),), 'issuer_outlook_boundary': (('the recent direction of the lines the narrative names', '{"let":[["rev",{"fn":"fundamentals","ticker":"<T>","metric":"revenue","months":12,"last_n":5}],["rev_g",{"fn":"yoy","of":"$rev"}]]}'),), 'book_composition': (('the shape, and its change since the prior run', '{"let":[["w",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"issuer_exposures","col":"weight"}],["ranked",{"fn":"rank","of":"$w","direction":"highest"}],["top5",{"fn":"sum","of":{"fn":"top","of":"$w","n":5}}],["top5_prev",{"fn":"sum","of":{"fn":"top","of":{"fn":"column","run":{"fn":"run","portfolio":"<port>","which":"prev"},"table":"issuer_exposures","col":"weight"},"n":5}}],["drift",{"fn":"sub","a":"$top5","b":"$top5_prev"}],["sectors",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"sector_exposures","col":"weight"}]]}'),), 'book_limits_and_triggers': (('every check against its tiers, and the room in weight and dollars', '{"let":[["current",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"limit_checks","col":"current_value"}],["warning",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"limit_checks","col":"warning_level"}],["breach",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"limit_checks","col":"breach_level"}],["room_to_warning",{"fn":"sub","a":"$warning","b":"$current"}],["room_to_breach",{"fn":"sub","a":"$breach","b":"$current"}],["nearest",{"fn":"rank","of":"$room_to_breach","direction":"lowest"}],["mv",{"fn":"pick","of":{"fn":"run","portfolio":"<port>"},"key":"exposure_metrics.portfolio_market_value"}],["room_dollars",{"fn":"mul","a":"$room_to_breach","b":"$mv"}]]}'),), 'book_hypothetical_trades': (('the after-book of a sale, its checks re-run', '{"let":[["after",{"fn":"sell","run":{"fn":"run","portfolio":"<port>"},"sales":[{"ticker":"<T>","fraction":0.5}]}],["w_after",{"fn":"column","run":"$after","table":"issuer_exposures","col":"weight"}],["checks_after",{"fn":"column","run":"$after","table":"limit_checks","col":"current_value"}],["w_before",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"issuer_exposures","col":"weight"}],["mv_after",{"fn":"pick","of":"$after","key":"exposure_metrics.portfolio_market_value"}]]}'), ('how much to sell to land at a tier', '{"let":[["w",{"fn":"pick","of":{"fn":"run","portfolio":"<port>"},"key":"issuer_exposures.<T>.weight"}],["tier",{"fn":"pick","of":{"fn":"run","portfolio":"<port>"},"key":"limit_checks.issuer_concentration:<T>.warning_level"}],["mv",{"fn":"pick","of":{"fn":"run","portfolio":"<port>"},"key":"exposure_metrics.portfolio_market_value"}],["excess",{"fn":"sub","a":"$w","b":"$tier"}],["dollars_to_sell",{"fn":"mul","a":"$excess","b":"$mv"}]]}'), ('adding a name at a target weight', '{"let":[["after",{"fn":"buy","run":{"fn":"run","portfolio":"<port>"},"buys":[{"ticker":"<N>","weight":0.05}]}],["w_after",{"fn":"column","run":"$after","table":"issuer_exposures","col":"weight"}],["checks_after",{"fn":"column","run":"$after","table":"limit_checks","col":"current_value"}]]}')), 'book_market_risk': (("each name's own rate, credit and market sensitivity", '{"let":[["beta_rates",{"fn":"method","name":"price.beta","subject":["<T1>","<T2>"],"params":{"benchmark":"TLT"},"key":"beta"}],["beta_credit",{"fn":"method","name":"price.beta","subject":["<T1>","<T2>"],"params":{"benchmark":"HYG"},"key":"beta"}],["beta_mkt",{"fn":"method","name":"price.beta","subject":["<T1>","<T2>"],"params":{"benchmark":"SPY"},"key":"beta"}],["most_rate_sensitive",{"fn":"rank","of":"$beta_rates","direction":"highest"}],["book_betas",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"factor_attributions","col":"beta"}]]}'), ('has volatility risen: short window against long, name by name and the index', '{"let":[["vol_30",{"fn":"method","name":"price.volatility","subject":["<T1>","<T2>","SPY"],"params":{"window_days":30}}],["vol_252",{"fn":"method","name":"price.volatility","subject":["<T1>","<T2>","SPY"],"params":{"window_days":252}}],["ratio",{"fn":"div","a":"$vol_30","b":"$vol_252"}],["jumpiest",{"fn":"rank","of":"$ratio","direction":"highest"}]]}')), 'book_drawdown_and_attribution': (('the worst episode, and what made it', '{"let":[["episodes",{"fn":"method","name":"book.drawdown_episodes","subject":"<port>","params":{"span":"1y"}}],["depth",{"fn":"pick","of":"$episodes","key":"portfolio.drawdown_episodes.deepest_depth"}],["peak",{"fn":"pick","of":"$episodes","key":"episodes[0].peak_date"}],["trough",{"fn":"pick","of":"$episodes","key":"episodes[0].trough_date"}],["explain",{"fn":"method","name":"book.explain_episode","subject":"<port>","params":{"peak":"$peak","trough":"$trough"}}],["by_name",{"fn":"column","run":"$explain","table":"holdings","col":"window_return"}],["worst_names",{"fn":"rank","of":"$by_name","direction":"lowest"}],["book_return",{"fn":"pick","of":"$explain","key":"portfolio.window_return"}]]}'), ("one day's move, market against us", '{"let":[["recon",{"fn":"method","name":"book.reconcile","subject":"<run>"}],["contrib",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"issuer_exposures","col":"contribution"}],["biggest_move",{"fn":"rank","of":"$contrib","direction":"lowest"}]]}')), 'book_liquidity': (('days to liquidate at a participation rate, worst first', '{"let":[["mv",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"issuer_exposures","col":"market_value"}],["adv",{"fn":"method","name":"price.adv","subject":["<T1>","<T2>"],"params":{"window_days":20},"key":"dollars"}],["days",{"fn":"div","a":"$mv","b":{"fn":"scale","of":"$adv","factor":0.25}}],["worst",{"fn":"rank","of":"$days","direction":"highest"}]]}'),), 'book_events': (('is it already in the price: the name against the market over the window', '{"let":[["ret",{"fn":"method","name":"price.window_return","subject":["<T1>","<T2>"],"params":{"window":"1m","benchmark":"SPY"}}],["w",{"fn":"column","run":{"fn":"run","portfolio":"<port>"},"table":"issuer_exposures","col":"weight"}]]}'),)}
_missing_programs = set(PROCEDURES) - set(_PROGRAMS)
if _missing_programs:
    raise RuntimeError(f"domain programs: missing {sorted(_missing_programs)}")
_missing = set(PROCEDURES) - set(_LINKS)
_extra = set(_LINKS) - set(PROCEDURES)
if _missing or _extra:
    raise RuntimeError(f"domain links: missing {sorted(_missing)}, unknown {sorted(_extra)}")
PROCEDURES = {name: replace(p, methods=_LINKS[name][0], reads=_LINKS[name][1], programs=_PROGRAMS[name])
              for name, p in PROCEDURES.items()}


# ── delivery: which domains a question is about (V30 Phase C, lexical) ────────

_WORD = None


def match_domains(text: str, n: int = 2) -> list[Procedure]:
    """The domains whose trigger phrases and question share the most words
    with the user's message — a deterministic lexical match, no model. Used by
    the loop to PUSH a domain's programs and desk lines into the turn; the
    2026-09-07 battery measured that knowledge behind an expand is knowledge
    the model does not have (3/140 cards opened)."""
    import re
    words = set(re.findall(r"[a-z]{3,}", (text or "").lower()))
    stop = {"the", "and", "that", "this", "what", "which", "with", "for", "are", "how", "does", "our", "its",
            "against", "from", "have", "has", "not", "you", "your", "about", "than", "one", "just", "into"}
    words -= stop
    if not words:
        return []
    scored = []
    for p in PROCEDURES.values():
        bag = " ".join(p.triggers) + " " + p.question
        pw = set(re.findall(r"[a-z]{3,}", bag.lower())) - stop
        hit = len(words & pw)
        if hit:
            scored.append((hit / (len(pw) ** 0.5), p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:n]]


def push_text(procedures: list[Procedure]) -> str:
    """What the loop hands the model for the matched domains: the question,
    what this desk knows, how to compare and close, and the programs."""
    parts = []
    for p in procedures:
        parts.append(f"DOMAIN {p.name} — {p.question}\nthis desk: " + " ".join(p.desk)
                     + "\ncompare: " + " ".join(p.compare) + "\nclose: " + " ".join(p.close)
                     + f"\nabsent here: {p.absent}"
                     + "".join(f"\nprogram — {title}:\n{prog}" for title, prog in p.programs))
    return "\n\n".join(parts)


def procedures_for(subject_kind: str) -> list[Procedure]:
    return [p for p in PROCEDURES.values() if p.subject_kind == subject_kind]
