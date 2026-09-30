"""The desk's style guide (V1 step 6): how a figure is cited and how a statement
stands. Eight rules, written ONCE, and owned by validation.

WHY THIS EXISTS. The rules the answer check and the handoff check enforce were
told to the model wherever somebody thought of them: "a figure is followed by
its id" in both role texts and a tool schema, "never an estimate, never a nearby
figure" in three role texts and again in the policy every chapter renders,
"a superlative rests on an ordering" in five places before V1 and "the caveat
sits beside its figure" in three after it. A rule with two copies drifts — the
9/17 review counted seven copies of one sentence — and a rule told in a
handbook or a tool description is validation's work done by somebody else.

So: the text of a rule lives HERE and nowhere else. The two role texts
(agents/meta_agent, agents/sub_analyst) include `text()` once each; the handbook,
the tool descriptions, the rows and the returns do not restate it; a refusal
names the rule it enforces by NUMBER (`rule_of`) and says the way out, which is
about the sentence in front of it and not about the rule.

What is NOT here: what the desk does not say (no forecast, no threshold, no
estimate, no nearby figure under the asked-for name) is POLICY — three standing
absence rows (analytics/registry.POLICY_ABSENCES) that the handbook renders as
its section 6 — so rule 8 points at it and adds only what is about writing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    n: int
    name: str                 # what the rule is about, for a counter or a log; never shown to a model
    key: str                  # a phrase of `text` that appears ONCE in everything a reader is sent (tests scan for it)
    text: str


RULES: tuple[Rule, ...] = (
    Rule(1, "a figure points at its row", "written exactly as the row shows it",
         "Every number you write is one a row showed you this turn, written exactly as the row shows it. In the final "
         "answer, follow it with the row's id in brackets: 16.0% [f_2592baab170e]. In a submitted note, refs may supply "
         "that pointer only when the reading is unambiguous; otherwise use an explicit pointer. A figure without "
         "a matching source is refused, as is one worked out in your head."),
    Rule(2, "a superlative stands on an ordering", "rests on an ordering the desk computed",
         "A superlative — largest, smallest, nearest — rests on an ordering the desk computed: the row it points at "
         "carries its place."),
    Rule(3, "a change and a comparison", "one measure of one subject at two dates",
         "A change is one measure of one subject at two dates; a comparison is one measure over one window for two "
         "subjects."),
    Rule(4, "the period written is the period held", "the period the row HAS",
         "Say the period the row HAS, not the one that was asked for."),
    Rule(5, "quotation marks", "Quotation marks are for text that came to you under an id",
         "Quotation marks are for text that came to you under an id — a passage's words, or the desk's own words on "
         "an absence row — cited with that id. An analyst's sentence, or your own, takes none: say it in your words."),
    Rule(6, "the words a row carries", "yours to repeat, never to contradict",
         "What a row says a reading means — that the book loses, that a check is in warning, a place in an ordering, "
         "which line stood in for which — is the desk's reading: yours to repeat, never to contradict."),
    Rule(7, "a caveat stays with its figure", "stated without its caveat",
         "A caveat stays with the figure it qualifies: a finding stated without its caveat is not what was found."),
    Rule(8, "what the desk does not hold", "carried from one company or date to another",
         "What the desk could not do or does not hold is said as such, with what was given instead. The desk's policy "
         "says what is never written in its place, and a figure is never carried from one company or date to another."),
)

HEAD = ("THE DESK'S STYLE GUIDE\nHow a figure is cited and how a statement stands. The desk's checks read what you "
        "write against these eight rules, and a refusal names the rule by its number.")


def text() -> str:
    """The guide as a role text includes it — once."""
    return HEAD + "\n" + "\n".join(f"{r.n}. {r.text}" for r in RULES)


# WHICH RULE A REFUSAL ENFORCES, by the reason code the checks already speak
# (services/answer_check, agents/delegation). A reason that is not here is about
# the SHAPE of what was filed — a line with no entry, an id in the wrong slot —
# and carries no rule.
_RULE_OF: dict[str, int] = {
    **{r: 1 for r in ("not_on_ledger", "unknown_node", "id_in_prose", "mark_mismatch", "unsourced_figure",
                      "unpointed_figure", "ambiguous_point", "ambiguous_reference", "passage_requires_pointer")},
    "superlative_without_rank": 2,
    "change_conflict": 3, "direction_conflict": 3,
    "period_mismatch": 4, "date_expected": 4,
    "unverified_quote": 5,
    "sense_conflict": 6, "status_conflict": 6, "tier_mismatch": 6,
    "caveat_without_a_line": 7,
    "subject_mismatch": 8, "measure_mismatch": 8, "benchmark_mismatch": 8,
}


def rule_of(reason: str | None) -> int | None:
    return _RULE_OF.get(reason or "")


def ruled(problem: dict) -> dict:
    """The problem with the number of the rule it enforces, where it enforces one."""
    n = rule_of(problem.get("reason"))
    return {**problem, "rule": n} if n is not None else problem
