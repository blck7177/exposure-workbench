"""V2 P2: the llm_call row says which ids the completion was handed (design v0.4
§07: existence on the ledger and actual receipt are recorded apart). Offline.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import delegation, delivery, meta_agent
from tests.test_meta_agent_gate import _W_MSFT, _delegate, _factory, _run, _run_result, _stub_desk, _stub_llm, _stub_tools, _submit


def test_delivered_collects_the_ids_in_what_was_appended():
    d = delivery.Delivered()
    assert d.note() is None
    d.add({"role": "tool", "content": "r_11a34f628851 filings_read(…) → 1 row\n[f_26cba3a106a8] Revenue, AAPL …"})
    d.add({"role": "user", "content": "point at f_policy_no_forecast or drop it"})
    note = d.note()
    assert note["read"] == {"chars": len("r_11a34f628851 filings_read(…) → 1 row\n[f_26cba3a106a8] Revenue, AAPL …")
                                     + len("point at f_policy_no_forecast or drop it"), "results": 1}
    assert note["delivered"]["facts"] == ["f_26cba3a106a8"]
    assert note["delivered"]["mentioned"] == ["f_26cba3a106a8", "f_policy_no_forecast"]
    assert note["delivered"]["pulls"] == ["r_11a34f628851"]
    d.reset()
    assert d.note() is None


@pytest.mark.asyncio
async def test_the_lead_completion_after_an_ask_records_the_rows_it_was_handed(monkeypatch):
    notes: list = []
    lead_turn = [0]

    async def _chat(messages, tools, note=None, **_kw):
        if delegation.ASK_TOOL_NAME in [t["function"]["name"] for t in tools]:
            notes.append(note)
            lead_turn[0] += 1
            if lead_turn[0] == 1:
                return "", _delegate()
            return "MSFT weighs 16.0% [f_wmsft0001] of the book.", None
        # the analyst: one read, then the brief
        if not any(m.get("role") == "tool" for m in messages):
            return "", _run()
        return "", _submit((["f_wmsft0001"], "MSFT weighs 16.0% [f_wmsft0001] of the book."))

    _stub_llm(monkeypatch, _chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    out = await meta_agent.handle_message(_factory([]), "sess_1", "how big is MSFT in the book?")
    assert out["text"].startswith("MSFT weighs 16.0%")
    assert notes[0]["delivered"]["prompt_chars"] > 0, "the first completion also records its context"
    assert "f_wmsft0001" in notes[1]["delivered"]["facts"], "the Return's rows were handed to the lead"
    assert notes[1]["read"]["results"] == 1
