"""V13-S3 — the gate keeps what it found, and finding it changes nothing (offline).

The gate has always known, for every figure in an answer, which cited row
supports it. It threw that away the moment it decided not to refuse, so the
product could say its numbers are checked and could not show a reader what any
one of them was checked against.

The risk in keeping it is the only thing these tests are about: that the second
return value quietly becomes a second judgement. It must not be possible for
`verify` and `verify_with_matches` to disagree about whether an answer may be
shown — they are one pass, and `verify` is a call to it — and a match must never
be produced for a figure the same pass refused.
"""

from __future__ import annotations

import pytest

from exposure_workbench.services import numeric_verification as nv
from exposure_workbench.services.numeric_verification import (
    EvidenceValue, extract_numbers, verify, verify_with_matches,
)

# The unit classes as the extractor names them — uppercase, and the reason
# this file briefly failed: lowercase strings match no candidate at all, so
# every figure came back "not in cited evidence" for the wrong reason.
MONEY, RATIO, COUNT = "MONEY", "RATIO", "COUNT"


def _val(value, unit_class=RATIO, label="weight", source_id="alert_1", not_alone=None):
    return EvidenceValue(value=value, unit_class=unit_class, label=label,
                         source_id=source_id, not_alone=not_alone)


def test_verify_is_the_same_pass_and_not_a_second_one():
    """Not a comparison of two implementations — an assertion that there is one.

    Read out of the source, because agreement on a handful of cases is exactly
    what a drifting copy looks like on the day it is written.
    """
    import inspect

    body = inspect.getsource(verify)
    assert "return verify_with_matches(" in body, (
        "verify has grown a second implementation. Two copies of the judgement "
        "would eventually disagree about whether an answer may be shown, which "
        "is the one disagreement this system cannot survive."
    )


def test_a_supported_figure_is_matched_to_the_row_that_supports_it():
    numbers = extract_numbers("LLY is 13.8% of the book")
    problems, matches = verify_with_matches(
        numbers, [_val(0.13768965, RATIO, "weight", "alert_6745156ea4c4")])
    assert problems == []
    assert len(matches) == 1
    m = matches[0]
    assert m["surface"] == "13.8%"
    assert m["source_id"] == "alert_6745156ea4c4"
    assert m["label"] == "weight"
    assert m["how"] == "value"


def test_a_match_carries_where_in_the_text_it_is():
    """A span, not a substring search.

    The UI attaches the basis to the figure the reader hovers. Searching the
    text for "1.39" would attach it to the "1.39" inside "21.39" the first time
    an answer contained both, and the wrong basis on a right-looking number is
    worse than no basis at all.
    """
    text = "VaR is 1.39% against a book beta of 21.39"
    numbers = extract_numbers(text)
    _, matches = verify_with_matches(numbers, [_val(0.0139, RATIO), _val(21.39, COUNT, "beta", "run_1")])
    spans = {m["surface"]: tuple(m["span"]) for m in matches}
    assert "1.39%" in spans
    start, end = spans["1.39%"]
    assert text[start:end] == "1.39%"


def test_a_refused_figure_produces_no_match():
    """The property that makes the count trustworthy.

    "7 figures checked" has to mean seven figures were checked and passed. A
    match emitted beside a problem would inflate the count with exactly the
    figures the gate refused.
    """
    numbers = extract_numbers("net debt of $39.1B")
    problems, matches = verify_with_matches(numbers, [_val(84_697_000_000.0, MONEY)])
    assert problems, "the figure is not in the evidence and must be refused"
    assert matches == []


def test_a_figure_quoted_from_a_passage_is_matched_without_naming_a_value():
    """A verbatim number inside a cited passage is supported BY the passage.

    There is no single evidence value behind it, and inventing one to fill the
    field would be the record claiming more than the check established.
    """
    numbers = extract_numbers("R&D was $11,419 million in the quarter")
    # The quoted set is keyed by KIND, not by digits alone: "$:11419" is a money
    # claim seen in a passage, and a bare "11419" would not vouch for it. That
    # shape is the gate's, and a fixture that ignored it would be testing a
    # laxer checker than the one that runs.
    _, matches = verify_with_matches(numbers, [], quoted={f"$:{n.key}" for n in numbers})
    assert [m["how"] for m in matches] == ["quoted"]
    assert "source_id" not in matches[0]


def test_an_indeterminate_row_is_never_the_one_shown():
    """V11-F: under collinearity a single coefficient is not determined.

    A figure supported by BOTH a determinate and an indeterminate row is
    quotable — and explaining it with the row the gate would have refused would
    hand the reader the wrong reason for a right answer.
    """
    numbers = extract_numbers("a contribution of 0.99%")
    determinate = _val(0.0099, RATIO, "factor total", "run_1")
    indeterminate = _val(0.0099, RATIO, "market beta", "run_1",
                         not_alone="quote the factor total instead")
    problems, matches = verify_with_matches(numbers, [indeterminate, determinate])
    assert problems == []
    assert matches[0]["label"] == "factor total"


def test_an_answer_that_states_no_numbers_verified_nothing_and_says_so():
    problems, matches = verify_with_matches(extract_numbers("Nothing changed this week."), [])
    assert problems == [] and matches == []


@pytest.mark.parametrize("fn", [verify, verify_with_matches])
def test_neither_entry_point_mutates_the_evidence_it_was_given(fn):
    values = [_val(0.13768965)]
    before = list(values)
    fn(extract_numbers("13.8% of the book"), values)
    assert values == before


def test_the_respond_gate_returns_what_the_resolver_accepted():
    """Read off the tool, because this is the seam the UI depends on.

    V15-S4: the gate no longer reads figures out of a sentence and matches them.
    The verified matches come from the one resolver — `_respond_blocks` hands
    the blocks to `resolver.resolve` and returns `resolver.accepted(...)`, whose
    `verified` carries a count and a match per slot on every accepted path,
    including an answer with no slots at all (zero, not an absent field, so the
    badge can say "0 figures checked" rather than disappearing).
    """
    import inspect

    from exposure_workbench.services import resolver
    from exposure_workbench.tools import meta_tools

    body = inspect.getsource(meta_tools._respond_blocks)
    assert "resolver.resolve(" in body
    assert "return {\"responded\": True, \"format\": \"blocks\", **resolver.accepted(blocks, verdict)}" in body
    assert "verify_with_matches" not in inspect.getsource(meta_tools), (
        "the exit must not run the prose checker: a second judgement beside the "
        "resolver's is free to disagree with it"
    )
    # The shape the UI reads, pinned on the resolver rather than on the tool.
    accepted = resolver.accepted([{"type": "paragraph", "runs": ["Nothing changed."]}],
                                 resolver.Verdict())
    assert accepted["verified"] == {"figures": 0, "sources": 0, "matches": []}
    assert accepted["citations"] == []


def test_the_agent_records_what_the_gate_found_rather_than_re_deriving_it():
    import inspect

    from exposure_workbench.agents import meta_agent

    body = inspect.getsource(meta_agent)
    assert 'meta["verified"] = reply_verified' in body
    assert "nv.verify" not in body and "numeric_verification" not in body, (
        "the agent must not run the checker itself: a second judgement of a "
        "stored answer is free to disagree with the one that let it through"
    )
