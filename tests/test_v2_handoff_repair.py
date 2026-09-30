"""V2 P1.2 (design v0.4 G2): the patch contract. The refusal says every entry not
named is kept; the code now keeps it. An analyst that resubmits only the entries
named gets its passing lines back in the brief, not a second refusal for the
lines it did as told and left alone. Offline, on the analyst-loop harness.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import delegation as dl, sub_analyst as sa
from tests.test_v1_analyst import SETTLED, _Tools, _ctx, _read, _submit

TASK2 = dl.Task("tsk_2", "risk", ("port_001",), ("how big MSFT is in the book", "where MSFT's weight will be next year"))
WRONG2 = {"n": 2, "settled": True, "finding": "MSFT will weigh 20.0% of the book next year.", "facts": ["f_w1a2b3c4d5e6"]}
FIXED2 = {"n": 2, "settled": False, "why": "the desk does not forecast", "boundary": "f_policy_no_forecast"}


async def run_repair(monkeypatch, replace_good=False):
    tools = _Tools()
    ctx, _, steps, stored = _ctx(monkeypatch, [], tools)
    from tests.test_v1_analyst import _call
    reads = []
    async def chat(messages, **kwargs):
        reads.append(messages)
        if len(reads) == 1:
            return "", _read()
        if len(reads) == 2:
            return "", _call("submit", evidence=SETTLED["facts"], notes=[
                {"text": SETTLED["finding"], "refs": SETTLED["facts"]},
                {"text": WRONG2["finding"], "refs": WRONG2["facts"]}])
        reply = json.loads(messages[-1]["content"])
        good_id, bad_id = [n["id"] for n in reply["note_ids"]]
        notes = [{"id": bad_id, "text": FIXED2["why"], "refs": [FIXED2["boundary"]]}]
        if replace_good:
            notes.append({"id": good_id, "text": SETTLED["finding"].rstrip(".") + ", the largest name.",
                          "refs": SETTLED["facts"]})
        return "", _call("submit", evidence=[], notes=notes)
    ctx.llm.chat = chat
    return await sa.run_sub_analyst(TASK2, ctx), steps, stored


@pytest.mark.asyncio
async def test_resubmitting_only_the_named_entry_keeps_the_passing_line(monkeypatch):
    result, steps, stored = await run_repair(monkeypatch)
    assert [s["status"] for s in steps if s["type"] == "brief"] == ["rejected", "completed"]
    assert len(result.notes) == 2 and result.notes[0]["text"] == SETTLED["finding"]
    assert result.notes[1]["text"] == FIXED2["why"]
    assert result.coverage == {} and result.status == "returned"
    assert stored[0]["status"] == "returned" and len(stored[0]["accepted_lines"]) == 2


@pytest.mark.asyncio
async def test_a_bad_revision_does_not_remove_the_previous_accepted_note(monkeypatch):
    result, steps, _ = await run_repair(monkeypatch, replace_good=True)
    assert [s["status"] for s in steps if s["type"] == "brief"] == ["rejected", "rejected"]
    assert result.notes[0]["text"] == SETTLED["finding"]
    assert result.notes[1]["text"] == FIXED2["why"]
    assert result.status == "stopped"
    assert "superlative_without_rank" in result.diagnostics[0]["reasons"]


def test_merge_brief_keeps_passing_caveats_and_takes_new_follow_ups():
    kept = {"lines": [{"n": 1, "settled": True, "finding": "a", "facts": ["f_x"]}],
            "caveats": [{"line": 1, "text": "as of the latest run"}], "follow_ups": ["old question"]}
    new = {"lines": [{"n": 2, "settled": False, "why": "no data", "boundary": "f_b"}],
           "caveats": [{"line": 1, "text": "as of the latest run"}, {"line": 2, "text": "the desk holds one run"}],
           "follow_ups": ["new question"]}
    merged = dl.merge_brief(kept, new)
    assert [e["n"] for e in merged["lines"]] == [1, 2]
    assert merged["caveats"] == [{"line": 1, "text": "as of the latest run"}, {"line": 2, "text": "the desk holds one run"}]
    assert merged["follow_ups"] == ["new question"]
    assert dl.merge_brief(None, new) == new
