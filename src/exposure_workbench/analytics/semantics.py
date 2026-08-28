"""What the metrics mean, and what a question of each kind costs. Data, not code.

Everything here was already written down — in `concept_mapping`'s comments and in
`Formula.note` — and none of it reached the model. `describe_issuer` handed over
a name, a period count and a date, so a model choosing between
`cash_and_equivalents` and `cash_and_restricted_cash` was choosing between two
strings. The knowledge that one of them includes restricted cash, and is
therefore not the cash a net-debt calculation may net against debt, sat in a
Python comment.

Three rules govern what may go in here, and each came out of a measured failure:

  * **Attach it to the thing it constrains.** A rule filed under a general
    heading is a rule the model has to remember to look up. DABstep put the
    manual on disk and told the agent twice to read it; the agent read it at
    step 1 and missed the applicable rule at step 6.

  * **State the consequence, not just the fact.** "Includes restricted cash" is
    a fact; "so it is NOT the cash available to repay debt" is the rule. The
    same study found agents follow explicitly stated rules and fail on rules
    that are implied by what is stated.

  * **Do not make the model compose two facts.** The containment graph says
    `long_term_debt_total` contains `current_portion_long_term_debt`; the
    conclusion "therefore they may not be added" is emitted beside it rather
    than left to be derived. Composite rules linked together implicitly are the
    class agents miss most often.

And one rule about what may NOT go in: no figures. A note is a rule, not a
measurement. `evaluate_formula` has been shipping notes on every call, and the
two that carried other issuers' figures were refused when relayed, because
nothing the caller cited holds them — a refusal that reads as the model's fault
and is not. The measurements are in docs/spikes/V9_FORMULA_BASIS.md, where the
people who read code will find them.

Nothing here carries a threshold, and nothing here is a procedure. Which tools
to call in which order is the model's to decide; `WORKED_EXAMPLES` shows a few
paths that are known to work and says why, which is a different thing from a
checklist. A skill document raised task pass rates by 27-36 points in a
controlled study; prescribing the steps of an analysis is what FinAgent measured
at minus twenty percent on the assets its rules did not fit.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricSemantics:
    """What a caller has to know about one metric before choosing it."""

    note: str = ""
    # Metrics this one is confusable with but is NOT interchangeable with, where
    # the containment graph has nothing to say — it records nesting, and these
    # pairs are simply different quantities.
    do_not_combine_with: tuple[str, ...] = field(default_factory=tuple)
    # The single tool call that produces the composed measure this metric is a
    # component of. Named here because "which producer is authoritative" was the
    # battery's largest measured failure: a component read off the balance sheet
    # was reported as the total in twelve runs out of twenty-two.
    for_a_total_call: str = ""


METRICS: dict[str, MetricSemantics] = {
    # ── cash: two quantities, one of them not spendable on debt ───────────────
    "cash_and_equivalents": MetricSemantics(
        note="Unrestricted cash — the cash a net-debt calculation may net against "
             "debt. Some issuers tag only the cash-flow total, so an issuer with no "
             "line here is NOT an issuer with no cash.",
        do_not_combine_with=("cash_and_restricted_cash",),
    ),
    "cash_and_restricted_cash": MetricSemantics(
        note="The cash-flow-statement total, which includes restricted cash and so "
             "is NOT the cash available to repay debt. Use cash_and_equivalents "
             "for that, and say which one a figure came from.",
        do_not_combine_with=("cash_and_equivalents",),
    ),

    # ── earnings: three lines that are not each other ─────────────────────────
    "pretax_income": MetricSemantics(
        note="Income before tax, including non-operating items such as interest and "
             "other income. It is NOT operating income and the two can be far "
             "apart, so name which one a figure is.",
        do_not_combine_with=("operating_income",),
    ),
    "operating_income": MetricSemantics(
        note="Operating income as the issuer tagged it. EBIT is NOT built from this "
             "— it starts from net income, per SEC C&DI 103.02 — so an operating "
             "income quoted as EBIT is the mislabel the regulator names.",
        do_not_combine_with=("pretax_income",),
    ),
    "net_income": MetricSemantics(
        note="Attributable to the parent, which is what net income means on the face "
             "of the income statement, so this is where EBIT and EBITDA start — per "
             "SEC C&DI 103.01, NOT from operating income.",
        do_not_combine_with=("net_income_including_noncontrolling",),
    ),
    "net_income_including_noncontrolling": MetricSemantics(
        note="Including noncontrolling interests — a different number whenever there "
             "are any, and for some issuers very different. NOT interchangeable "
             "with net_income, so say which one.",
        do_not_combine_with=("net_income",),
    ),
    "cost_of_revenue": MetricSemantics(
        note="The issuer's own cost line. It is NOT gross profit, but gross profit "
             "is revenue minus this, which is how the margin is computed for the "
             "many issuers that never tag GrossProfit.",
    ),

    # ── the top line: two quantities, and issuers move between them ───────────
    "revenue": MetricSemantics(
        note="Revenue from contracts with customers. Issuers report the whole top "
             "line under total_revenues instead, and some moved between the two, so "
             "check which one reaches the present.",
        do_not_combine_with=("total_revenues",),
    ),
    "total_revenues": MetricSemantics(
        note="The whole top line, including revenue that did not arise from "
             "contracts with customers — a superset of revenue rather than a "
             "synonym, so a margin says which one it divided by.",
        do_not_combine_with=("revenue",),
    ),

    # ── debt: five concepts, five quantities, and they nest ───────────────────
    "long_term_debt_total": MetricSemantics(
        note="All term debt, current maturities INCLUDED — a component of what the "
             "issuer owes, NOT the total. Which components an issuer files varies, "
             "so a total is composed rather than read off a line.",
        for_a_total_call="evaluate_formula(name='total_debt')",
    ),
    "long_term_debt_noncurrent": MetricSemantics(
        note="Term debt due beyond twelve months, excluding the current maturities. "
             "A component, so a total that adds it to a line already containing it "
             "counts the same debt twice.",
        for_a_total_call="evaluate_formula(name='total_debt')",
    ),
    "current_portion_long_term_debt": MetricSemantics(
        note="The current maturities of long-term debt on their own. Already inside "
             "long_term_debt_total, so adding the two is a double count rather than "
             "a total.",
        for_a_total_call="evaluate_formula(name='total_debt')",
    ),
    "debt_current_total": MetricSemantics(
        note="Every debt the issuer classifies as current, whatever its origin — a "
             "wider line than the current maturities of term debt, so the two are "
             "not interchangeable.",
        for_a_total_call="evaluate_formula(name='total_debt')",
    ),
    "short_term_borrowings": MetricSemantics(
        note="Short-dated borrowings such as commercial paper and revolver draws. A "
             "component of debt_current_total rather than a synonym for it: an "
             "issuer filing both files two different numbers.",
        for_a_total_call="evaluate_formula(name='total_debt')",
    ),
    "commercial_paper": MetricSemantics(
        note="Short-dated debt outside the term structure — a component, NOT a "
             "synonym for the current debt total. A filed zero is a reported value "
             "rather than an absence.",
        for_a_total_call="evaluate_formula(name='total_debt')",
    ),

    # ── interest: an accrual, a cash payment, and a bank's revenue ────────────
    "interest_expense": MetricSemantics(
        note="The accrued interest charge. NOT a bank's net interest income, which "
             "is revenue rather than an expense, and NOT the cash actually paid — "
             "so coverage built on it is an accrual measure.",
        do_not_combine_with=("interest_paid",),
    ),
    "interest_expense_nonoperating": MetricSemantics(
        note="Interest expense classified as non-operating — its own metric, never "
             "folded into interest_expense, because merging them would produce a "
             "series that changes basis partway through.",
    ),
    "interest_paid": MetricSemantics(
        note="Cash interest actually paid, which is NOT the accrued charge. Say "
             "which of the two a coverage figure used.",
        do_not_combine_with=("interest_expense",),
    ),

    # ── depreciation: a combined charge, and two parts that do not make it ────
    "depreciation_amortization": MetricSemantics(
        note="The combined depreciation and amortisation charge EBITDA adds back. "
             "Issuers filing only the two parts have no line here, so their EBITDA "
             "is unavailable rather than assembled.",
    ),
    "depreciation": MetricSemantics(
        note="Depreciation alone. It is NOT summed with intangible amortisation to "
             "make D&A here, because that sum is not guaranteed to equal the charge "
             "the issuer reports under that name.",
        do_not_combine_with=("amortization_of_intangibles",),
    ),
    "amortization_of_intangibles": MetricSemantics(
        note="Intangible amortisation alone. NOT summed with depreciation to stand "
             "in for D&A: a number carrying that name has to be the number the "
             "issuer reported.",
        do_not_combine_with=("depreciation",),
    ),
}


@dataclass(frozen=True)
class WorkedExample:
    """A path that is known to work, and the reason it is the right one.

    `why` is the load-bearing field. A list of calls is a procedure and ages
    badly; the reason generalises to the next question of the same shape.
    """

    question: str
    calls: tuple[str, ...]
    why: str


WORKED_EXAMPLES: dict[str, tuple[WorkedExample, ...]] = {
    "issuer": (
        WorkedExample(
            question="What is this issuer's total debt / net debt / leverage?",
            calls=("evaluate_formula(name='total_debt')",),
            why="One producer per named measure. A balance-sheet line is a component "
                "whatever its name ends in, and a total added to a component it "
                "contains double-counts.",
        ),
        WorkedExample(
            question="How has revenue (or any flow) grown over the last four quarters?",
            calls=("get_flow(metric=..., months=3, last_n=4)",
                   "series_stat(series_id=..., op='yoy')"),
            why="Pick the metric whose latest_period_end reaches the present — one "
                "carrying superseded_by returns a short series, not an error.",
        ),
        WorkedExample(
            question="Why is a measure defined the way it is?",
            calls=("evaluate_formula(name=...)",),
            why="The result carries an authority you may name: cite_as is the section "
                "to say, url is where to read it. Name it rather than 'the registry'.",
        ),
    ),
    "portfolio": (
        WorkedExample(
            question="Why are there large drawdowns?",
            calls=("get_drawdown_episodes()", "explain_episode(peak=..., trough=...)"),
            why="A drawdown is a peak-to-trough episode over many sessions; "
                "reconcile_move explains ONE session. Measure the episodes before "
                "explaining them.",
        ),
        WorkedExample(
            question="Was the loss market-driven or company-specific?",
            calls=("reconcile_move(run_id=...)",),
            why="factor_share and unexplained_share come back with it and the larger "
                "one is the answer. Positions and factors are two decompositions of "
                "the same number, so the position table cannot argue a move was "
                "idiosyncratic.",
        ),
        WorkedExample(
            question="Which factor hurt the most?",
            calls=("get_attribution(run_id=...)",),
            why="Each row carries quotable_individually: under collinearity no single "
                "beta is determined, so name the sum — a lone coefficient is refused.",
        ),
    ),
}


def for_metric(metric: str) -> MetricSemantics | None:
    return METRICS.get(metric)


def examples(face: str) -> tuple[WorkedExample, ...]:
    return WORKED_EXAMPLES.get(face, ())
