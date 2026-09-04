"""V21-S5 — the critic outside the gate reads the words beside a figure (offline).

The gate proves provenance and shows the table's value; "market cap at
$919.77" beside `LLY.close` passed it. No lexical rule and no model goes into
the gate (the 9/1 contract), so the judgement about words is a second model's,
outside, over the rendered blocks. These tests hold the seat still: what it
reads (paragraph slots, marked), what it asks (the desk name beside each
marker), how it reads an answer (JSON or nothing), and that no exit imports it.
"""

from __future__ import annotations

import inspect
import json

import pytest

from exposure_workbench.services import prose_critic as pc


def _slot(ref, label, value, unit="MONEY_PER_SHARE"):
    """Rendered slots carry the unit class as the ledger spells it (upper case),
    which is what display_conventions reads."""
    return {"slot": {"ref": ref, "label": label, "value": value, "unit_class": unit}}


RENDERED = [
    {"type": "paragraph", "runs": [
        "LLY's market cap stood at ", _slot("calc_1", "LLY.close", 919.77),
        " on the last session, while its net margin reached ",
        _slot("calc_2", "net_margin@2026-Q1", 0.223, "RATIO"), "."]},
    {"type": "metric_table", "rows": [[_slot("calc_3", "NVDA.adj_close@2026-06-05", 205.1)]]},
    {"type": "paragraph", "runs": ["No figures here, just words."]},
    {"type": "trend", "text": "Rising.", "series_ref": "calc_9"},
]


def test_only_paragraphs_with_slots_are_read_and_each_slot_becomes_a_marker():
    ps = pc.paragraphs(RENDERED)
    assert [p.block_index for p in ps] == [0], "the table, the empty paragraph and the trend are not read"
    p = ps[0]
    assert [s.k for s in p.slots] == [1, 2]
    assert [s.name for s in p.slots] == ["LLY.close", "net_margin@2026-Q1"]
    assert "⟦1⟧" in p.marked and "⟦2⟧" in p.marked
    assert "919.77" not in p.marked.replace("⟦1⟧($919.77)", ""), "the value rides inside the marker only"
    assert p.slots[1].shown == "22.3%", "the figure is shown as the page shows it"


def test_the_question_names_the_desk_name_beside_every_marker():
    p = pc.paragraphs(RENDERED)[0]
    msgs = pc.messages_for(p)
    assert msgs[0]["role"] == "system" and "LABELS, not numbers" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "⟦1⟧ shows $919.77; desk name: `LLY.close`" in user
    assert "⟦2⟧ shows 22.3%; desk name: `net_margin@2026-Q1`" in user
    assert "A share PRICE is not a market cap" in user, "the name grammar travels with the question"


def test_the_sentence_around_a_marker_is_the_one_reported():
    p = pc.paragraphs([{"type": "paragraph", "runs": [
        "First sentence. Revenue rose to ", _slot("c", "revenue@FY2025", 5e9, "MONEY"),
        " in the year. Last sentence."]}])[0]
    assert pc.sentence_around(p.marked, 1) == "Revenue rose to ⟦1⟧($5.00B) in the year."


def test_verdicts_are_read_from_json_with_or_without_a_fence_and_padded_when_short():
    text = '```json\n{"verdicts": [{"k": 1, "prose_says": "market cap", "verdict": "disagrees", "reason": "a closing price"}]}\n```'
    out = pc.parse_verdicts(text, expected=2)
    assert out[0] == {"k": 1, "prose_says": "market cap", "verdict": "disagrees", "reason": "a closing price"}
    assert out[1]["verdict"] == "unclear", "a marker the critic did not answer is unclear, not agreed"


def test_an_unreadable_answer_is_unclear_for_every_marker_never_a_disagreement():
    out = pc.parse_verdicts("I think the first one is wrong.", expected=2)
    assert [v["verdict"] for v in out] == ["unclear", "unclear"]
    out = pc.parse_verdicts('{"verdicts": [{"k": 1, "verdict": "WRONG"}]}', expected=1)
    assert out[0]["verdict"] == "unclear", "a verdict outside the three is not a verdict"


@pytest.mark.asyncio
async def test_critique_returns_one_finding_per_slot_in_prose_from_the_stand_in_model():
    asked: list[list[dict]] = []

    async def _chat(messages, model=None, temperature=0.0, max_tokens=0):
        asked.append(messages)
        return (json.dumps({"verdicts": [
            {"k": 1, "prose_says": "market cap", "verdict": "disagrees", "reason": "LLY.close is a share price"},
            {"k": 2, "prose_says": "net margin", "verdict": "agrees", "reason": ""}]}), "stand-in", 0, 0)

    findings = await pc.critique(RENDERED, chat=_chat)
    assert len(asked) == 1, "one completion per paragraph with slots"
    assert [(f.name, f.verdict) for f in findings] == [("LLY.close", "disagrees"), ("net_margin@2026-Q1", "agrees")]
    assert findings[0].prose_says == "market cap" and findings[0].shown == "$919.77"
    assert "market cap stood at ⟦1⟧" in findings[0].sentence
    s = pc.summary(findings)
    assert (s["slots_in_prose"], s["disagrees"], s["agrees"], s["unclear"]) == (2, 1, 1, 0)
    assert s["disagreements"][0]["name"] == "LLY.close"


@pytest.mark.asyncio
async def test_blocks_without_a_slot_in_prose_cost_no_completion():
    async def _chat(*_a, **_k):
        raise AssertionError("no paragraph carries a slot; nothing to ask")
    assert await pc.critique(RENDERED[1:], chat=_chat) == []


def test_no_exit_and_no_gate_imports_the_critic():
    """The 9/1 contract: the gate is five closed lookups and the critic is a
    judgement. It sits outside, and the modules that decide an answer's fate
    do not know it exists."""
    from exposure_workbench.agents import meta_agent, research_session
    from exposure_workbench.services import resolver, answer_blocks, table
    from exposure_workbench.tools import meta_tools, research_tools, registry
    for mod in (meta_agent, research_session, resolver, answer_blocks, table, meta_tools, research_tools, registry):
        assert "prose_critic" not in inspect.getsource(mod), f"{mod.__name__} reaches for the critic"


def test_the_critic_imports_no_model_client_itself():
    """Whoever runs the critic pays for it: the chat callable is passed in."""
    src = inspect.getsource(pc)
    assert "from exposure_workbench.llm" not in src and "import openai" not in src
