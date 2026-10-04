"""The model session: an append-only conversation, the mutable tail, the record."""

from __future__ import annotations

import pytest

from exposure_workbench.agents.llm_session import Conversation, LlmSession, ModelPolicy
from exposure_workbench.llm import client as llm_client
from tests.agent_fakes import FakeDb, ScriptedProvider, Store, text_turn, tool_turn


@pytest.fixture
def recorded(monkeypatch):
    store = Store()
    from exposure_workbench.services import trace_service

    async def _record_step(db, session_id, **kw):
        store.steps.append(kw)
        return "step_1"
    monkeypatch.setattr(trace_service, "record_step", _record_step)
    return store


async def test_next_sends_the_conversation_plus_the_tail_and_records_what_was_appended(monkeypatch, recorded):
    provider = ScriptedProvider([tool_turn(("analyze", {"requests": []})), text_turn("done")])
    monkeypatch.setattr(llm_client, "respond", provider)
    llm = LlmSession(lambda: FakeDb(recorded), "sess", "msg", policy=ModelPolicy("m", "low", 1000))
    conv = Conversation()
    conv.say("user", "question")
    turn = await llm.next(conv, instructions="role", tools=[{"type": "function", "name": "analyze", "parameters": {"type": "object"}}],
                          tail=[llm_client.message("developer", "<state/>")])
    assert turn.tool_calls and conv.items[-1]["type"] == "function_call"
    sent = provider.requests[0]
    assert sent["input_items"][-1]["role"] == "developer"               # the tail is last …
    assert conv.items[-1]["type"] != "function_call_output" and all(i.get("role") != "developer" for i in conv.items)  # … and never kept
    rec = recorded.steps[0]
    assert rec["step_type"] == "llm_call" and rec["prompt_tokens"] == 1000
    assert [i.get("role") for i in rec["args"]["request"]["items_appended"]] == ["user"]
    assert rec["args"]["request"]["tail"][0]["role"] == "developer"
    assert rec["args"]["response"]["output"] == turn.output
    assert rec["args"]["request"]["reasoning_effort"] == "low"

    with pytest.raises(RuntimeError):                                     # a call left unanswered is never sent
        await llm.next(conv, instructions="role", tools=None)
    conv.tool_output(turn.tool_calls[0].call_id, "{}")
    await llm.next(conv, instructions="role", tools=None)
    # the model's own call was recorded as the previous step's output; what is new to this request is the answer to it
    assert [i.get("type") for i in recorded.steps[1]["args"]["request"]["items_appended"]] == ["function_call_output"]
    assert recorded.steps[0]["args"]["response"]["output"][-1]["type"] == "function_call"


def test_policy_reads_a_role_from_settings():
    lead = ModelPolicy.for_role("lead")
    assert lead.model and lead.max_output_tokens > 0
    with pytest.raises(ValueError):
        ModelPolicy.for_role("auditor")
