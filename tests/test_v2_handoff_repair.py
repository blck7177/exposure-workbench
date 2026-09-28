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


@pytest.mark.asyncio
async def test_resubmitting_only_the_named_entry_keeps_the_passing_line(monkeypatch):
    tools = _Tools()
    ctx, seen, steps, stored = _ctx(monkeypatch, [("", _read()), ("", _submit(SETTLED, WRONG2)), ("", _submit(FIXED2))], tools)
    result = await sa.run_sub_analyst(TASK2, ctx)
    assert [s["status"] for s in steps if s["type"] == "brief"] == ["rejected", "completed"]
    assert sorted(e["n"] for e in result.lines) == [1, 2], "line 1 was not resent and is still in the brief"
    assert result.coverage == {"asked": 2, "settled": 1, "unsettled": 1, "refused": 0}
    assert result.status == "partial"
    told = json.loads([m for m in seen[2]["messages"] if m.get("role") == "tool"][-1]["content"])
    assert "only the entries named above" in told["refusal"], "the words and the code say the same thing"
    assert stored[0]["status"] == "verified" and [f["want"] for f in stored[0]["brief"]["findings"]] == [1]


@pytest.mark.asyncio
async def test_a_named_entry_is_replaced_and_an_unnamed_one_is_untouched(monkeypatch):
    tools = _Tools()
    better1 = {**SETTLED, "finding": "MSFT weighs 16.0% [f_w1a2b3c4d5e6] of the book, the largest name."}
    ctx, _seen, steps, _stored = _ctx(monkeypatch, [("", _read()), ("", _submit(SETTLED, WRONG2)),
                                                    ("", _submit(better1, FIXED2))], tools)
    result = await sa.run_sub_analyst(TASK2, ctx)
    line1 = next(e for e in result.lines if e["n"] == 1)
    # "largest" with no ordering behind it: the resent line 1 is checked again, and refused again
    assert [s["status"] for s in steps if s["type"] == "brief"] == ["rejected", "rejected"]
    assert line1["finding"].endswith("the largest name.")
    assert [x["n"] for x in result.refused] == [1]
    assert next(e for e in result.lines if e["n"] == 2) == FIXED2


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
