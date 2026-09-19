"""The desk's handbook (V1 step 5): three chapters, six sections, five things it
never says.

WHY THIS EXISTS. Until V1 the analyst's knowledge was fourteen DOMAINS cut by
question type (analytics/skill.PROCEDURES), and each domain's text carried four
kinds of thing that belong to someone else: how a tool is called (programs, key
paths), how a tool's output is read (sign conventions, "8% is 0.08"), what the
answer check enforces (a superlative rests on a ranking — five copies), and live
data (a corpus statistic, one run's net beta). Every fix had been one more
sentence in a domain. The boss's decisions of 2026-09-17 and 09-19 cut it the
other way: an analyst per RESOURCE FAMILY, tools that are low-level verbs, facts
that carry their own meaning — and a handbook that says only what a thing is,
what it means and what the desk has.

A CHAPTER PER ANALYST, SIX SECTIONS EACH:
    1  the questions       what a reader asks of this analyst, in financial words
    2  the measures        what each is, its unit, what it is built on, on whose authority
    3  how they read       what the desk knows about reading one that a textbook does not
    4  compare and close   what is set against what, and how a finding ends
    5  what the desk holds its data, models, checks and engines — and what is absent, and why
    6  policy              what the desk does not say
Sections 2, 3 and 6 are RENDERED from analytics/registry (the measures, READS,
INSTRUMENTS, POLICY_ABSENCES); 1, 4 and 5 are written here. A question a reader
asks ("has volatility risen?") is answered in section 4 as what to set against
what — never as a tool, and never as a call.

THE FIVE THINGS A CHAPTER NEVER SAYS (tests/test_v1_handbook.py scans for each):
    no call syntax, parameter values, key names or programs   (the tools say what they take)
    no output conventions — signs, unit conversions, field readings   (the row says what it means)
    no rule of the answer check   (the style guide's, once)
    no live data — a corpus statistic, a property of one fit, a figure of any run
    no sentence twice

THE LEAD READS THE MEANING LAYER: every chapter's section 3 and the policy, and
the roster (section 1 and what is absent) — what a reading means and who can be
asked, with no measure key, no verb and no figure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import registry

ANALYSTS = registry.FACES          # ("issuer", "market", "risk")


@dataclass(frozen=True)
class Topic:
    """One thing a reader asks of an analyst: what can be asked (section 1) and
    how it is compared and closed (section 4)."""
    name: str
    asked: tuple[str, ...]
    compare: tuple[str, ...]
    close: tuple[str, ...]
    # What the topic turns on, by registry key — never rendered. It is what makes
    # "every question can be answered with this analyst's own tools" a test and
    # not a hope: each key must be a measure on the analyst's face.
    measures: tuple[str, ...] = ()


@dataclass(frozen=True)
class Chapter:
    analyst: str
    title: str
    answers: str                                # one line: what this analyst is for
    data: str                                   # the resource family, in a sentence
    topics: tuple[Topic, ...]
    holds: tuple[str, ...]                      # section 5: what the desk has
    absent: tuple[tuple[str, str], ...]         # section 5: (what is absent, "data" | "policy" | "withheld")
    reads: tuple[str, ...] = ()                 # section 3: the registry READS keys this chapter renders, beyond its measures

    def __post_init__(self) -> None:
        if self.analyst not in ANALYSTS:
            raise ValueError(f"chapter for unknown analyst {self.analyst!r}")
        for _what, why in self.absent:
            if why not in ("data", "policy", "withheld"):
                raise ValueError(f"{self.analyst}: an absence is for want of data, by policy, or withheld — got {why!r}")
        unknown = [k for k in self.reads if k not in registry.READS]
        if unknown:
            raise ValueError(f"{self.analyst}: readings not in the registry: {unknown}")
        mine = {m.name for m in registry.metrics_for(self.analyst)}
        for t in self.topics:
            off = [k for k in t.measures if k not in mine]
            if off:
                raise ValueError(f"{self.analyst} / {t.name}: turns on measures that are not on this analyst's face: {off}")


ISSUER = Chapter(
    "issuer", "The issuer analyst",
    answers="one issuer from its own filings: whether the profits are real, how profitable it is, how much debt it "
            "carries and how well it covers it, where its cash goes, what it says can go wrong — and the same across "
            "several issuers on one measure",
    data="The issuer's filed figures, as filed; the text of its filings, Item by Item; and the web for what a filing "
         "cannot hold.",
    topics=(
        Topic("earnings quality",
              measures=("accruals_ratio", "accruals", "days_sales_outstanding", "days_inventory", "days_payable", "cash_conversion_cycle",),
              asked=("operating cash flow beside net income over a window, and whether cash confirms earnings",
                     "the accruals ratio, as a level and as a trend",
                     "whether receivables, inventory or payables are growing faster than revenue",
                     "the working-capital cycle in days, dated, against an earlier reading"),
              compare=("cash conversion and the accruals ratio against the issuer's own prior periods: the evidence is about persistence, not one period",
                       "receivable and inventory growth against revenue growth over the same windows",
                       "days against the same days a year earlier"),
              close=("say whether cash confirms earnings, and if not which line explains the gap and whether it is building",
                     "give the days as days, dated, beside the prior reading")),
        Topic("profitability",
              measures=("gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic", "asset_turnover", "equity_multiplier", "tax_burden",),
              asked=("margins at any filed line — gross, operating, net — as a level and as a slope",
                     "return on equity, on assets and on invested capital, and what a return on equity is made of",
                     "several issuers on one line at once, ordered, with the runner-up and the gap",
                     "whether a margin move is mix, pricing or cost, as far as the filed lines separate them"),
              compare=("level and slope for each name over the same windows: who is higher, whose is moving",
                       "gross against operating margin to separate cost of goods from overhead; net against operating to isolate interest, tax and non-operating items",
                       "a return on equity beside its net margin, asset turnover and equity multiplier: the three multiply to it, so the one that moved is the reason",
                       "an ordering on one measure against the same ordering on another, when the question asks whether it holds"),
              close=("a sentence for the level, a sentence for the slope, and what that implies for the question asked",
                     "name the runner-up and the gap when a name is called the best")),
        Topic("leverage and coverage",
              measures=("total_debt", "net_debt", "debt_to_ebitda", "net_debt_to_ebitda", "ebit_interest_coverage", "fcf_to_debt", "current_ratio", "quick_ratio", "ebitda",),
              asked=("debt against earnings, interest coverage, free cash flow against debt, and the liquidity ratios",
                     "the same readings a year earlier, or another issuer's",
                     "what would have to change in earnings or in debt for a reading to flip",
                     "what the filing itself says about maturities, covenants and facilities — quoted"),
              compare=("against the issuer's own prior periods first, then against the other names on the same measure",
                       "gross and net leverage side by side, with the cash that was netted",
                       "coverage against the trend of EBIT: falling coverage with flat EBIT means the debt got dearer",
                       "the flip point: the target multiple times EBITDA, less the debt, is how far the debt would have to move; the debt over the target multiple, less EBITDA, how far the earnings would"),
              close=("more or less levered than the comparison named, with the figures",
                     "what would have to change in earnings or debt for the reading to flip")),
        Topic("where the cash goes",
              measures=("free_cash_flow", "capex_intensity", "fcf_margin", "book.position",),
              asked=("capital expenditure, buybacks and dividends, each as a share of operating cash flow",
                     "capital-expenditure intensity, and whether the spending is outrunning revenue",
                     "free cash flow, and what the spending is doing to it"),
              compare=("the ordering of the uses and whether it changed from the prior year",
                       "capital-expenditure growth over revenue growth, and capital expenditure over depreciation, across several windows",
                       "the same shape on the peer when two issuers are compared"),
              close=("which use dominates, whether it is accelerating, and what it does to free cash flow",
                     "if the name is held, the position's weight, so the reader knows what is at stake")),
        Topic("business risk, from the filings",
              measures=("gross_margin", "capex_intensity", "asset_turnover",),
              asked=("what the issuer's own filings say can go wrong, quoted from a named Item or a search of the text",
                     "the lines a named risk shows in first, over the years",
                     "what changed in the business and what did not, in the filing's own words",
                     "the drivers the filings name, each with the line it shows in and that line's recent direction"),
              compare=("each named risk against the trend of the line where it shows, so the risks are ordered by what the figures already show, not by the filing's order",
                       "the filing's stated shares across years, where both years state one",
                       "management's stated drivers against the lines that have actually moved, and the same statement across filings for consistency",
                       "a percentage in a filing's prose is whatever its own sentence says it is: growth is not a share, and a share the filing does not state is not available by reading one that is"),
              close=("the risks in the order the figures rank them, each with the line to watch",
                     "what changed and what did not, with the filing's own sentence for what the business is now",
                     "one question for management, phrased so the answer would be a figure the filings do not yet hold")),
        Topic("recent events",
              measures=("book.position",),
              asked=("recent filing items and web items about the name",
                     "whether the name is held, and the size of the position an item touches"),
              compare=("each item against the position's weight: what is at stake",),
              close=("which items matter and why, each with its source and date; an item that touches nothing held is said to touch nothing",
                     "a search that returns nothing specific is reported as nothing found, never as headline-level news")),
    ),
    holds=("filed line items exactly as filed, by filing: a restatement supersedes what it restates, and a quarter the issuer did not file stays a gap in the series, never closed over",
           "the text of each filing, by Item, searchable and quotable verbatim",
           "web items about an issuer, each with its publisher and date",
           "the name's own rows in the book, when a book holds it",
           "a name the desk has not prepared is put in preparation in the background and said to be in preparation; nothing is estimated for it meanwhile"),
    absent=(("segment, product, geographic and customer-concentration figures are not held as figures: they are quoted from the filing's own sentences, never derived from parts", "data"),
            ("debt maturities, covenants and undrawn facilities are not held as figures: where the filing states them they are quoted", "data"),
            ("a return on capital expenditure is not measurable from the filings: the desk says what the spending is doing to cash and margins, not what it will earn", "data"),
            ("valuation multiples are not yet measures on this desk", "data"),
            ("an earnings calendar is not held: dates are quoted from a filing or the web, never inferred", "data"),
            ("leverage and coverage built on interest are refused for a financial issuer — interest is a bank's operating cost and deposits its raw material; returns on equity and assets and the accruals ratio do apply", "policy")),
)

MARKET = Chapter(
    "market", "The market analyst",
    answers="one name from its prices: where the price sits against its own history and the market, how sensitive it is "
            "to the market, to rates and to credit, whether it has become more volatile, whether news is already in the "
            "price, and how much of it trades in a day",
    data="Daily prices and volume for the names the desk follows and for the factor instruments.",
    topics=(
        Topic("where the price sits",
              measures=("price.distance_from_52w_high", "price.momentum_12_1", "price.drawdown", "price.window_return",),
              asked=("distance from the high of the trailing year, momentum, and the deepest drawdown with its dates",
                     "return over a window against a benchmark's"),
              compare=("the name's return against the benchmark's over the same window",
                       "the name against the book's other holdings on the same measure"),
              close=("what the price has already moved on, dated, and what would be new information",
                     "never a view on where the price goes")),
        Topic("sensitivity",
              measures=("price.beta",),
              asked=("the name's beta to the market, to the rates instrument and to the credit instrument, with how well the fit explains it",),
              compare=("the same name against each instrument: which risk it answers to most",
                       "several names against one instrument, ordered"),
              close=("which risk the name answers to, with the fit's explanatory power beside the beta",)),
        Topic("whether it has become more volatile",
              measures=("price.volatility",),
              asked=("volatility over a short window and over a long one, for a name and for the index",),
              compare=("the short window against the long: a short window reacts, a long one is the baseline, so their ratio says whether volatility has risen",
                       "the name's rise against the index's over the same windows: market-wide or specific"),
              close=("whose volatility rose, with both windows' figures, and whether the index's rose with it",)),
        Topic("whether it is already in the price",
              measures=("price.window_return",),
              asked=("the name's return over the window around an event, against the market's over the same window",),
              compare=("the move relative to the market, not the move alone",),
              close=("how much of the move was the market's and how much the name's own, dated",)),
        Topic("how much of it trades",
              measures=("price.adv",),
              asked=("average daily volume in shares and in dollars, over a stated number of sessions",),
              compare=("the same name over a longer span of sessions, when the recent one may be unusual",),
              close=("the dollars a day the name trades, with the sessions it was measured over",)),
    ),
    holds=("daily closes, adjusted closes and volume for the held names and the factor instruments",
           "every price statistic states the fewest sessions it needs and is refused below that, never shortened",
           "a price statistic is measured over its latest window: it cannot be asked as of a past date"),
    absent=(("valuation multiples need filed earnings beside the price and are not yet measures on this desk", "data"),
            ("intraday prices and an order book are not held", "data"),
            ("a view on where a price goes is not given", "policy")),
)

RISK = Chapter(
    "risk", "The portfolio risk manager",
    answers="the book: what it is made of and how that has drifted, where it stands against its mandate and what would "
            "trip a check, what it looks like after a trade, what it is exposed to, how it fell and recovered and how "
            "much of that was the market, and how fast it could be sold",
    data="The book: positions, runs and their tables, the mandate's checks, the factor model, the scenario engine, "
         "drawdown episodes and the daily reconciliation — and, by name, a holding's beta, volatility and volume.",
    topics=(
        Topic("composition and drift",
              asked=("what the book holds, by weight and by market value, and the sectors they add up to",
                     "the largest name, the share of the largest few, the largest sector — each with its change since the prior run"),
              compare=("the share of the largest few against the prior run's",
                       "each sector's weight against its prior weight, so drift is the change, not the level",
                       "the largest name against the runner-up"),
              close=("the shape in three figures — the largest name, the share of the largest few, the largest sector — each with its change since the prior run",
                     "which single move would change the shape most")),
        Topic("limits and triggers",
              measures=("book.analysis",),
              asked=("every mandate check against its warning and breach tiers, and the room left to each",
                     "the nearest check, and the price move in one name that would close its own room",
                     "who would be over a cap the mandate does not define"),
              compare=("the nearest check first, by smallest room",
                       "the same check on the prior run, for direction",
                       "room in weight points, in dollars — the book's market value times the room — and, for a single-name check, as the price move that closes it: the room over the name's weight",
                       "a cap the mandate does not define has no check: the names over it are the weights above that level"),
              close=("the level for each check nearest its tier, in weight points, in dollars and as a price move",
                     "which check trips first, and on what")),
        Topic("a hypothetical trade",
              asked=("the book after a sale or a purchase, with every check re-run",
                     "what tightens and what loosens against the book before",
                     "the dollars to sell to land a name at a tier, and the weight it lands at"),
              compare=("the after-book's checks against the before-book's",
                       "the candidate against the runner-up on the measure the choice rests on",
                       "the dollars to sell: the weight above the tier times the book's market value",
                       "a name already held is trimmed or added to through its weight, never bought again; a sale larger than the position means the wrong tier or the wrong base"),
              close=("the name and the reason it was chosen over the runner-up",
                     "the dollars to sell and the weight it lands at, with the tier named",
                     "what else the trade touches, from the after-book's checks")),
        Topic("market risk",
              measures=("book.analysis", "price.beta", "price.volatility",),
              asked=("the book's netted exposure to an equity fall, to rates rising and to credit spreads widening",
                     "each holding's own sensitivity to the market, to rates and to credit",
                     "whether risk has risen, name by name and for the index"),
              compare=("the instruments that carry duration and spread directly against the equities' measured sensitivities: which side of the exposure is which",
                       "each name's short-window volatility against its long: whose rose",
                       "the book's rise against the index's over the same windows: market-wide or specific"),
              close=("where a shock bites, name by name in the order of measured sensitivity, with what is unmeasured",
                     "market-wide or specific, and which names, each with the two windows' figures")),
        Topic("drawdown and attribution",
              measures=("book.drawdown_episodes", "book.explain_episode", "book.reconcile",),
              asked=("the book's drawdown episodes: depth, peak and trough dates, recovery",
                     "which names made an episode, by contribution over it",
                     "how much of a day's move was the market and how much was what was held"),
              compare=("an episode's depth and length against the market's over the same dates",
                       "the factor-explained share against the residual: the market against the book's own",
                       "each holding's contribution against its weight: who hurt more than their size"),
              close=("depth, dates and recovery in one sentence, then the names that made it, then market against specific",
                     "what the unexplained share is made of, by name")),
        Topic("liquidity",
              measures=("price.adv",),
              asked=("days to liquidate each name at a stated share of its daily volume, and what the book could clear in a day",
                     "whether the problem is one name or the book"),
              compare=("days to liquidate: the position's market value over the participation rate times the dollars a day the name trades — market value over the daily dollars alone is not days",
                       "names ordered by days, longest first; the same name at a lower participation rate, when the question is a hurry",
                       "days against the position's weight: a large weight with few days is size, not illiquidity"),
              close=("the names that would hurt, each with its days at the stated rate, and what the book could clear in a day",
                     "the participation rate is the reader's, or is stated beside the figure: the desk fixes none")),
    ),
    holds=("positions, and every completed run's tables: holdings, sectors, the mandate's checks with what each measured and its tiers, the factor fit, the run's own figures",
           "a factor model of seven instruments fitted on the book's return; the run records whether the fit is collinear",
           "a scenario engine that re-prices the book and re-runs every concentration and exposure check after a trade; it does not re-fit betas, volatility or profit and loss, which are stated unmeasured; scenarios chain",
           "drawdown episodes, found on today's holdings replayed over the span, and a daily reconciliation that reports no share of a move when its own identity does not hold",
           "a check that did not run because its input is withheld is listed as not run, never as clear"),
    absent=(("value at risk, expected shortfall and the stress results are computed by the run and withheld pending validation: say so if asked, and do not rebuild them from other figures", "withheld"),
            ("correlations between holdings and hidden common bets are not measures on this desk", "data"),
            ("ownership as a share of an issuer's float, and crowding, are not held", "data"),
            ("an instrument's underlying liquidity is not looked through; a name with fewer sessions of volume than the window asks for is unmeasured, not liquid", "data"),
            ("a limit the mandate does not define has no check and no room", "data"),
            ("a period with fewer sessions than a span needs has no episodes, and a day without a completed run has no reconciliation", "data")),
    reads=("issuer_exposures.weight", "issuer_exposures.contribution"),
)

CHAPTERS: dict[str, Chapter] = {c.analyst: c for c in (ISSUER, MARKET, RISK)}


# ── rendering ────────────────────────────────────────────────────────────────

_COMMON_FORMULA_FAILURE = "an input the issuer did not file at the window or instant asked"
_CODE_NAME = re.compile(r"\s*\([A-Z][A-Z_]+\)")           # "(VOL_MIN_OBS)": a constant's name is the code's, not a reader's


def _measure_line(m: registry.Method) -> str:
    built = "; ".join(registry.BASIS[b] for b in m.basis)
    fails = [part for part in _CODE_NAME.sub("", m.fails_when).split("; ")
             if part != _COMMON_FORMULA_FAILURE and not part.startswith("the issuer is a financial company")]
    formula = fm.FORMULAS.get(m.name)
    return (f"- {m.reads_as}: {m.describes}"
            + (f" — {built}" if built else "")
            + (f". Not meaningful when: {'; '.join(fails)}" if fails else "")
            + (". Not for a financial issuer" if formula is not None and formula.not_for_financials is not None else "")
            + f". ({m.authority})")


def measures_text(analyst: str) -> str:
    """Section 2, rendered: what each of this analyst's measures is."""
    lines = [_measure_line(m) for m in registry.metrics_for(analyst)]
    if analyst == "issuer":
        lines.insert(0, "Every issuer measure is refused where an input was not filed at the window or date asked; "
                        "the refusal names the input.")
    if analyst in ("market", "risk"):
        lines.append("The factor instruments: " + "; ".join(f"{t} is {what}, standing for {risk}"
                                                            for t, what, risk in registry.INSTRUMENTS) + ".")
    return "\n".join(lines)


def _read_keys(analyst: str) -> list[str]:
    own = [m.name for m in registry.metrics_for(analyst) if m.name in registry.READS]
    return [*own, *[k for k in CHAPTERS[analyst].reads if k not in own]]


def readings_text(analyst: str) -> str:
    """Section 3, rendered: what the desk knows about reading one."""
    return "\n".join(f"- {registry.reads_as(k)}: {registry.READS[k]}" for k in _read_keys(analyst))


def policy_text() -> str:
    """Section 6, rendered: what the desk does not say — the sentences the
    standing policy absences carry, so a policy is written once."""
    return "\n".join(f"- {p['text']}" for p in registry.POLICY_ABSENCES)


def chapter_text(analyst: str) -> str:
    """One analyst's standing knowledge: its chapter, six sections."""
    c = CHAPTERS[analyst]
    why = {"data": "the desk does not hold it", "policy": "by policy", "withheld": "withheld"}
    return "\n\n".join((
        f"{c.title.upper()}\n{c.data}",
        # each question names the measures that answer it, in the words section 2 lists them under.
        # The topics always declared them (Topic.measures) and the chapter never said so: asked for
        # "the room left to each tier", the risk analyst subtracted fourteen pairs of figures one
        # call at a time and ran out of calls, with the measure that IS the room two sections down.
        "1. THE QUESTIONS\n" + "\n".join(
            f"{t.name}: " + "; ".join(t.asked)
            + (". Measured by: " + "; ".join(registry.METHODS[m].reads_as for m in t.measures if m in registry.METHODS)
               if any(m in registry.METHODS for m in t.measures) else "")
            for t in c.topics),
        "2. THE MEASURES\n" + measures_text(analyst),
        "3. HOW THEY READ\n" + readings_text(analyst),
        "4. COMPARE AND CLOSE\n" + "\n".join(f"{t.name} — compare: " + "; ".join(t.compare) + ". Close: " + "; ".join(t.close) + "."
                                             for t in c.topics),
        "5. WHAT THE DESK HOLDS\n" + "\n".join(f"- {h}" for h in c.holds)
        + "\nAbsent here:\n" + "\n".join(f"- {what} ({why[w]})" for what, w in c.absent),
        "6. POLICY\n" + policy_text(),
    ))


def roster() -> list[dict]:
    """WHO THE LEAD CAN ASK: three analysts, each with what it answers, what it
    can be asked for and what is absent there — no measure key, no verb, no figure."""
    return [{"analyst": c.analyst, "answers": c.answers,
             "can_be_asked": [a for t in c.topics for a in t.asked],
             "absent": [{"what": what, "why": why} for what, why in c.absent]}
            for c in CHAPTERS.values()]


def meaning_layer() -> str:
    """What the lead is given to write implications with: how every reading reads,
    across the three chapters, and the policy. The finance, without the system."""
    seen: list[str] = []
    for analyst in ANALYSTS:
        seen += [k for k in _read_keys(analyst) if k not in seen]
    return ("HOW THE DESK'S READINGS READ\n" + "\n".join(f"- {registry.reads_as(k)}: {registry.READS[k]}" for k in seen)
            + "\nThe factor instruments: " + "; ".join(f"{t} is {what}, standing for {risk}"
                                                        for t, what, risk in registry.INSTRUMENTS) + "."
            + "\n\nPOLICY\n" + policy_text())
