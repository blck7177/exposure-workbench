"""S1 loop: receipt + canonical work view, fact checking without coverage gates.
Provider, tools and persistence are scripted; the protocol/check/state are real.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import delegation, meta_agent
from exposure_workbench.services import analysis_state as AS
from tests.test_meta_agent_gate import _W_MSFT, _factory, _run, _run_result, _stub_desk, _stub_llm, _stub_tools

Q = "How big is MSFT in the book, and what will its weight be next year?"
REQS = [{"id": "R1", "anchor": "How big is MSFT in the book"}, {"id": "R2", "anchor": "what will its weight be next year"}]
ROW = "MSFT weighs 16.0% [f_wmsft0001] of the book."


def _ask(requirements, *tasks):
    # Legacy test callers may still pass a requirement list; it is not sent.
    full = [{"analyst": "risk", "subjects": ["port_001"], "lines": ["how big MSFT is in the book"],
             **{k: v for k, v in t.items() if k != "for"}} for t in tasks]
    args = {"tasks": full}
    return [{"id": "c1", "function": {"name": delegation.ASK_TOOL_NAME, "arguments": json.dumps(args)}}]


def _submit(lines):
    return [{"id": "s1", "function": {"name": delegation.SUBMIT_TOOL_NAME, "arguments": json.dumps({"lines": lines})}}]


def _no_db_state(monkeypatch):
    """The state lives in memory for the test: opened fresh, never written."""
    async def _open(db_factory, session_id, message_id, question, brief):
        return AS.new_turn(session_id, message_id, question, brief if isinstance(brief, dict) else {})

    async def _save(db_factory, state):
        return None

    monkeypatch.setattr(meta_agent, "_open_state", _open)
    monkeypatch.setattr(meta_agent, "_save_state", _save)


def _script(lead_replies, sub_replies):
    lead, sub = [], []

    async def _chat(messages, tools, **_kw):
        if delegation.ASK_TOOL_NAME in [t["function"]["name"] for t in tools]:
            lead.append(list(messages))
            return lead_replies[min(len(lead), len(lead_replies)) - 1]
        sub.append(list(messages))
        return sub_replies[min(len(sub), len(sub_replies)) - 1]

    return _chat, lead, sub


def _state_of(messages) -> dict:
    block = next(m["content"] for m in messages if m["role"] == "system" and m["content"].startswith(meta_agent.STATE_TAG))
    return json.loads(block.split("\n", 1)[1].rsplit("\n</state>", 1)[0])



@pytest.mark.asyncio
async def test_checked_answer_is_delivered_without_claiming_completeness(monkeypatch):
    _no_db_state(monkeypatch)
    chat, lead, _ = _script(
        [("", _ask(None, {})), (ROW, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    tools = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, tools)
    out = await meta_agent.handle_message(_factory([]), "sess", Q)
    assert len(lead) == 2 and out["meta"]["delivery"] == "answered"
    assert out["meta"]["completion"] is None and "requirements" not in out["meta"]
    assert "Still open" not in out["text"] and "gate" not in out["meta"]
    view = _state_of(lead[1])
    assert view["question"] == Q and "requirements" not in view and "completion" not in view
    assert view["findings"][0]["text"] == ROW
    assert view["findings"][0]["rows"][0].startswith("[f_wmsft0001]")
    receipt = json.loads(lead[1][-1]["content"])
    assert receipt["returns"][0]["accepted_findings"] == 1
    assert ROW not in lead[1][-1]["content"]
    assert sum(ROW in m.get("content", "") for m in lead[1]) == 1


@pytest.mark.asyncio
async def test_policy_result_is_visible_without_becoming_a_completion_certificate(monkeypatch):
    chat, lead, _ = _script(
        [("", _ask(None, {"lines": ["MSFT weight next year"]})),
         ("The desk does not forecast [f_policy_no_forecast].", None)],
        [("", _submit([{"n": 1, "settled": False, "why": "the desk does not forecast",
                         "boundary": "f_policy_no_forecast"}]))])
    _stub_llm(monkeypatch, chat)
    tools = _stub_tools(monkeypatch, {})
    _stub_desk(monkeypatch, tools)
    out = await meta_agent.handle_message(_factory([]), "sess", Q)
    assert out["meta"]["completion"] is None
    assert _state_of(lead[1])["gaps"][0]["type"] == "tool_result"
    assert "forecast" in _state_of(lead[1])["gaps"][0]["boundary"]


@pytest.mark.asyncio
async def test_refused_analyst_text_never_enters_work_view_or_receipt(monkeypatch):
    bad = {"n": 2, "settled": True, "finding": "MSFT will weigh 20.0% of the book next year.", "facts": ["f_wmsft0001"]}
    good = {"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}
    chat, lead, _ = _script(
        [("", _ask(None, {"lines": ["weight", "forecast"]})), (ROW, None)],
        [("", _run()), ("", _submit([good, bad])), ("", _submit([bad]))])
    _stub_llm(monkeypatch, chat)
    tools = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, tools)
    out = await meta_agent.handle_message(_factory([]), "sess", Q)
    assert "20.0%" not in json.dumps(_state_of(lead[1]))
    assert "20.0%" not in lead[1][-1]["content"]
    assert _state_of(lead[1])["findings"][0]["text"] == ROW
    assert out["meta"]["delegations"][0]["status"] == "partial"


@pytest.mark.asyncio
async def test_bad_task_can_be_revised_without_declaration_transaction(monkeypatch):
    chat, lead, _ = _script(
        [("", _ask(None, {"analyst": "unknown"})), ("", _ask(None, {})), (ROW, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    tools = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, tools)
    out = await meta_agent.handle_message(_factory([]), "sess", Q)
    assert json.loads(lead[1][-1]["content"])["error"] == "invalid_ask"
    assert out["citations"] == ["f_wmsft0001"]
