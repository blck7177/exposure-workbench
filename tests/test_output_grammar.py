"""V15-S3 — the exit's grammar is closed, and the schema is the thing that closes it.

Until V14 the model wrote prose with figures in it and the gate read the
figures back out; V14-C made a figure a slot but let a slot be `{ref, value}`,
and the gate then went looking for which figure the value meant — 442 bad slots
on one battery, the wrong identity blessed. V15 makes every claim type one
shape with one evidence predicate and lets the JSON Schema refuse everything
else BEFORE the gate runs, naming the field the model has to fix.

These tests say what the grammar refuses and what it accepts, offline, against
the same schema `respond` is registered with. If a shape outside §3-B ever
passes the schema, it will reach the resolver, and the resolver is deliberately
too simple to catch it.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from exposure_workbench.services import answer_blocks as ab
from exposure_workbench.services import resolver
from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.meta_tools import RESPOND_SCHEMA

SRC = Path(__file__).resolve().parents[1] / "src" / "exposure_workbench"


def _refusals(blocks) -> list[dict]:
    return validate_args(RESPOND_SCHEMA, {"blocks": blocks})


def _fields(blocks) -> list[str]:
    return [p["field"] for p in _refusals(blocks)]


# ── what the schema refuses ───────────────────────────────────────────────────

def test_a_slot_carrying_a_value_is_refused_at_the_field_that_carries_it():
    """The value form is the one channel through which a figure could arrive
    without its identity. The refusal must name the slot's `value` key, not
    the block, or the model is told "something in block 0" and rewrites prose."""
    fields = _fields([{"type": "paragraph", "runs": ["Weight is ", {"ref": "run_1", "value": 0.16}]}])
    assert "blocks.0.runs.1.value" in fields, fields
    assert "blocks.0.runs.1.name" in fields, "and it also lacks the name a slot needs"


def test_a_slot_without_a_name_is_refused_naming_the_missing_name():
    fields = _fields([{"type": "paragraph", "runs": [{"ref": "run_1"}]}])
    assert fields == ["blocks.0.runs.0.name"], fields


def test_a_block_of_unknown_type_is_refused_at_the_block():
    fields = _fields([{"type": "footnote", "text": "see above"}])
    assert fields == ["blocks.0"], fields


def test_a_trend_without_a_series_ref_is_refused_naming_series_ref():
    """A claim that something rose or fell rests on the series it was read from;
    a trend with no series is a bare assertion wearing a block type."""
    fields = _fields([{"type": "trend", "text": "revenue rose over the year"}])
    assert fields == ["blocks.0.series_ref"], fields


def test_an_action_without_a_task_ref_is_refused_naming_task_ref():
    fields = _fields([{"type": "action", "text": "started a research run"}])
    assert fields == ["blocks.0.task_ref"], fields


def test_a_chart_of_unknown_kind_is_refused_naming_kind():
    fields = _fields([{"type": "chart", "kind": "pie", "series_ref": "calc_1"}])
    assert fields == ["blocks.0.kind"], fields


@pytest.mark.parametrize("block", [
    {"type": "paragraph", "runs": ["fine"]},
    {"type": "metric_table", "columns": ["a"], "rows": [["x"]]},
    {"type": "chart", "kind": "bar", "series_ref": "calc_1"},
    {"type": "trend", "text": "rose", "series_ref": "calc_1"},
    {"type": "absence", "text": "not filed", "absence_ref": "calc_1"},
    {"type": "action", "text": "started", "task_ref": "task_1"},
], ids=ab.BLOCK_TYPES)
def test_an_unknown_key_on_any_block_is_refused_naming_the_key(block):
    """Closed on every branch: a block that carries `value`, `evidence_ids`, or
    any key the grammar does not have is a block whose extra content the
    resolver would never look at — accepted and unchecked is the worst state."""
    fields = _fields([{**block, "extra": 1}])
    assert fields == ["blocks.0.extra"], fields


# ── what the schema accepts ───────────────────────────────────────────────────

@pytest.mark.parametrize("block", [
    {"type": "paragraph", "runs": ["MSFT weighs ", {"ref": "run_1", "name": "issuer_exposures.MSFT.weight"}],
     "cites": ["chunk_1"]},
    {"type": "metric_table", "title": "Weights", "columns": ["issuer", "weight"],
     "rows": [["MSFT", {"ref": "run_1", "name": "issuer_exposures.MSFT.weight"}]], "cites": ["src_1"]},
    {"type": "chart", "kind": "line", "title": "Revenue", "series_ref": "calc_1"},
    {"type": "trend", "text": "revenue rose each quarter", "series_ref": "calc_1"},
    {"type": "absence", "text": "the issuer files no such line", "absence_ref": "calc_2"},
    {"type": "action", "text": "a research run was started", "task_ref": "rrun_1"},
], ids=ab.BLOCK_TYPES)
def test_each_of_the_six_block_types_written_correctly_is_accepted(block):
    assert _refusals([block]) == []


def test_an_empty_answer_is_refused():
    assert _fields([]) == ["blocks"]


# ── the one text rule ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["16.3%", "$94.9B", "1.29", "5,000 shares"])
def test_a_measurement_typed_as_text_is_a_figure(text):
    """Percent, money, a bare decimal, a count with its noun: each is a number
    the reader takes as a fact, and text is not where facts are checked."""
    assert ab.figures_in_text(text), text


@pytest.mark.parametrize("text", [
    "2026-03-31", "March 28, 2026",        # dates
    "in 2025",                              # a year
    "10-K", "10-Q/A",                       # form types
    "Q1", "FY2025",                         # period labels
    "Item 1A", "C&DI 103.02", "Rule 17a-4", # regulation references
    "H200", "S&P500",                       # attached product / index designators
])
def test_a_non_measurement_token_class_is_not_a_figure(text):
    """The exempt classes are closed and short. Each one here is a case the
    grammar's own comment names; a new class means a new case, not a wider regex."""
    assert ab.figures_in_text(text) == [], text


def test_a_mixed_sentence_keeps_only_the_measurements():
    text = "Revenue rose 16.3% in FY2025 per the 10-K filed 2026-03-31, up from $94.9B on March 28, 2026"
    assert ab.figures_in_text(text) == ["16.3%", "$94.9"]


# ── the shape walker ──────────────────────────────────────────────────────────

def test_validate_shape_reports_every_problem_not_the_first():
    """A model that fixes one problem per turn spends the turn budget on a form
    it could have filled in once (the same rule tools/arg_validation states)."""
    problems = ab.validate_shape([
        {"type": "paragraph", "runs": ["up 16.3%", {"ref": "run_1"}]},
        {"type": "trend", "series_ref": "calc_1"},
        {"type": "chart", "kind": "pie"},
    ])
    reasons = sorted(p["reason"] for p in problems)
    assert reasons == sorted([
        "digits_in_text", "slot_without_name", "trend_without_text",
        "unknown_chart_kind", "chart_without_series",
    ]), problems
    # The text rule reads a paragraph's prose whole (so a measure's name keeps
    # its context across slots), hence one address for the digits; a slot's
    # shape problem is still addressed per run.
    assert {p["at"] for p in problems} == {"blocks[0].runs", "blocks[0].runs[1]", "blocks[1]", "blocks[2]"}


def test_refs_in_gathers_slots_cites_and_block_refs_deduped_in_order():
    blocks = [
        {"type": "paragraph", "runs": [{"ref": "run_A", "name": "x"}, " and ", {"ref": "run_A", "name": "y"}],
         "cites": ["chunk_B", "run_A"]},
        {"type": "trend", "text": "rose", "series_ref": "calc_C"},
        {"type": "absence", "text": "none", "absence_ref": "chunk_B"},
        {"type": "action", "text": "started", "task_ref": "task_D"},
    ]
    assert ab.refs_in(blocks) == ["run_A", "chunk_B", "calc_C", "task_D"]


def test_text_of_drops_slots_and_text_by_block_keeps_prose_with_its_own_block():
    """The quote rule reads each block against ITS cites; pooling the prose
    would let a quotation in block 2 be justified by a passage cited in block 1."""
    blocks = [
        {"type": "paragraph", "runs": ["MSFT weighs ", {"ref": "run_1", "name": "w"}, " of the book."]},
        {"type": "metric_table", "title": "Weights", "columns": ["a", "b"],
         "rows": [["MSFT", {"ref": "run_1", "name": "w"}]]},
        {"type": "trend", "text": "revenue rose", "series_ref": "calc_1"},
    ]
    assert ab.text_of(blocks) == "MSFT weighs  of the book.\nWeights\nMSFT\nrevenue rose"
    assert ab.text_by_block(blocks) == [
        ("blocks[0]", "MSFT weighs  of the book."),
        ("blocks[1]", "Weights\nMSFT"),
        ("blocks[2]", "revenue rose"),
    ]


def test_rendered_fills_slots_from_the_table_and_prose_reads_at_reader_precision():
    """The model wrote names; the reader sees the table's value, rounded by the
    one display rule (analytics/display_conventions), never a float dump."""
    blocks = [
        {"type": "paragraph", "runs": ["MSFT weighs ", {"ref": "run_1", "name": "issuer_exposures.MSFT.weight"},
                                       " of a book worth ", {"ref": "run_1", "name": "exposure_metrics.portfolio_market_value"}, "."]},
    ]
    resolved = [
        ab.Resolved("run_1", "issuer_exposures.MSFT.weight", 0.1633512, "RATIO"),
        ab.Resolved("run_1", "exposure_metrics.portfolio_market_value", 10869311, "MONEY"),
    ]
    filled = ab.rendered(blocks, resolved)
    assert filled[0]["runs"][1] == {"slot": {"ref": "run_1", "label": "issuer_exposures.MSFT.weight",
                                             "value": 0.1633512, "unit_class": "RATIO"}}
    assert ab.prose_of(filled) == "MSFT weighs 16.3% of a book worth $10.87M."


# ── the two pins ──────────────────────────────────────────────────────────────

def test_slot_value_does_not_exist_as_a_form_anywhere_in_the_grammar_or_the_resolver():
    """`slot.value` was the by-value channel V15 deleted (§3-D). The renderer
    still WRITES `value` into a filled slot — that is the table's figure going
    to the reader — but no code reads a value off the model's slot."""
    for name in ("services/answer_blocks.py", "services/resolver.py"):
        src = (SRC / name).read_text()
        assert "slot.value" not in src, name
        assert 'slot["value"]' not in src.replace('slot["value"], slot.get("unit_class")', ""), (
            f"{name} reads a value off a slot other than the rendered one")
    # The shape walker takes ref and name and nothing else from a slot.
    body = inspect.getsource(ab._slot_problem)
    assert "value" not in body


def test_the_resolver_can_only_refuse_for_one_of_five_reasons():
    """Pinned from the source, not from a run: the reason set IS the contract
    the model is trained against, and a sixth reason is a sixth thing the
    prompt would have to explain."""
    src = inspect.getsource(resolver)
    emitted = set(re.findall(r'v\.error(?:, v\.problems)? = "([a-z_]+)"', src))
    assert emitted == {"malformed_answer", "not_on_table", "unknown_name",
                       "unverified_quote", "unsupported_assertion"}, emitted


def test_a_window_label_is_the_name_of_a_measure_not_a_figure():
    """"30-day rolling volatility" is what the measure is called; "the last 3
    years" is a span. The exposure report's own headings are written this way,
    and three stored block answers were refused for them before the class was
    added. "30 %" beside the label is still a figure."""
    for text in ("30-day rolling volatility", "60d vol and 1y return",
                 "over the last 3 years", "a 2-quarter lag"):
        assert ab.figures_in_text(text) == [], text
    assert ab.figures_in_text("30-day vol of 12.1%") == ["12.1%"]


def test_an_id_written_into_text_is_refused_whole_not_as_its_digits():
    """The refusal names what the model wrote. `run_d1bbfadbbb7e` used to come
    back as figures '1' and '7', which is a refusal the model cannot act on."""
    assert ab.figures_in_text("see run_d1bbfadbbb7e and chunk_44dcf44e1683") == [
        "run_d1bbfadbbb7e", "chunk_44dcf44e1683"]


def test_a_confidence_level_is_a_parameter_of_the_measure_not_a_figure():
    """"VaR (95%)" names which VaR; the first V15 battery spent eight attempts
    of one turn on it. A bare "95%" away from the measure's name is a figure."""
    for text in ("1-day VaR (95%)", "95% VaR over 55 sessions", "VaR 95 1-day", "the 95% confidence tail"):
        assert ab.figures_in_text(text) == [], text
    assert ab.figures_in_text("the book returned 95% of its cost") == ["95%"]


def test_a_refusal_for_an_id_in_text_says_where_the_id_belongs():
    [p] = ab.validate_shape([{"type": "paragraph", "runs": ["see run_1d6e9e05bee6 for 27 checks"]}])
    assert "cites" in p["detail"] and "count." in p["detail"]
