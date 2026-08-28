"""The knowledge table is data, and these are the rules it has to obey (V12-S1).

Every one of these came out of a measured failure, so each is a ratchet rather
than a style check: a note that states a fact without its consequence, or that
carries a figure nothing can support, is the shape that has already cost this
desk a wrong answer.
"""

from __future__ import annotations

import re

from exposure_workbench.analytics import semantics as sm
from exposure_workbench.services.concept_mapping import SUPPORTED_METRICS
from exposure_workbench.tools import faces

# "so", "NOT", "rather than", "instead" — the words that turn a fact into a rule.
# DABstep measured agents following explicitly stated rules and failing on rules
# merely implied by what was stated, so a note without one of these is a fact
# the model still has to draw the conclusion from.
_CONSEQUENCE = re.compile(r"\bso\b|\bNOT\b|rather than|instead|because", re.MULTILINE)
_FIGURE = re.compile(r"\d[\d.,]*\s*(?:%|bn\b|billion|million|trillion|trn\b)", re.IGNORECASE)
# A threshold is a judgement wearing a number. formulas.py has forbidden them
# since V9 and the knowledge table inherits the rule.
_THRESHOLD = re.compile(r"\b(?:above|below|exceeds?|healthy|risky|concerning|"
                        r"acceptable|too (?:high|low)|at least|no more than)\b", re.IGNORECASE)

_MAX_NOTE = 240


def test_every_key_is_a_metric_this_desk_maps():
    """A note filed under a misspelt name is a note nobody will ever read."""
    unknown = sorted(set(sm.METRICS) - set(SUPPORTED_METRICS))
    assert not unknown, unknown


def test_every_cross_reference_points_at_a_real_metric():
    for name, s in sm.METRICS.items():
        for other in s.do_not_combine_with:
            assert other in SUPPORTED_METRICS, f"{name} -> {other}"
            assert other != name, name


def test_the_pairs_are_symmetric():
    """If A must not be combined with B, B must say so too — the model may
    arrive at either one first."""
    for name, s in sm.METRICS.items():
        for other in s.do_not_combine_with:
            back = sm.METRICS.get(other)
            assert back is not None and name in back.do_not_combine_with, \
                f"{name} names {other}, but not the other way round"


def test_every_note_states_a_consequence():
    """"Includes restricted cash" is a fact; "so it is NOT the cash available to
    repay debt" is the rule. Only the second one survives being skimmed."""
    for name, s in sm.METRICS.items():
        assert s.note, name
        assert _CONSEQUENCE.search(s.note), f"{name}: states a fact with no consequence"


def test_no_note_is_longer_than_a_glance():
    for name, s in sm.METRICS.items():
        assert len(s.note) <= _MAX_NOTE, f"{name}: {len(s.note)} chars"


def test_no_note_carries_a_figure_or_a_threshold():
    """A note is a rule. A figure in one is a number no citation can support —
    relaying it is refused, and the refusal reads as the model's fault."""
    for name, s in sm.METRICS.items():
        assert not _FIGURE.findall(s.note), f"{name}: {_FIGURE.findall(s.note)}"
        assert not _THRESHOLD.findall(s.note), f"{name}: {_THRESHOLD.findall(s.note)}"


def test_a_component_says_which_call_produces_the_total():
    """The battery's largest measured failure was reading a component off the
    balance sheet and reporting it as the total, twelve runs out of twenty-two."""
    debt = {"long_term_debt_total", "long_term_debt_noncurrent",
            "current_portion_long_term_debt", "debt_current_total",
            "short_term_borrowings", "commercial_paper"}
    for name in debt:
        s = sm.METRICS.get(name)
        assert s is not None and s.for_a_total_call, name
        assert "total_debt" in s.for_a_total_call, name


def test_every_worked_example_calls_tools_that_exist_on_the_face():
    """A face is a promise about what an agent can do; an example naming a tool
    the face does not carry is an instruction to fail."""
    on_face = set(faces.FACE_META_AGENT)
    for group, examples in sm.WORKED_EXAMPLES.items():
        assert examples, group
        for ex in examples:
            assert ex.why and ex.question, group
            for call in ex.calls:
                tool = call.split("(")[0]
                assert tool in on_face, f"{group}: {tool} is not on the meta face"


def test_no_worked_example_carries_a_figure_or_a_threshold():
    for group, examples in sm.WORKED_EXAMPLES.items():
        for ex in examples:
            assert not _FIGURE.findall(ex.why), f"{group}: {ex.why}"
            assert not _THRESHOLD.findall(ex.why), f"{group}: {ex.why}"
