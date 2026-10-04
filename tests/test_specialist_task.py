"""A specialist's task inside the lead's turn, offline: bound scope, its analysis,
its prose read by the observer, the record, and what the lead reads next."""

from __future__ import annotations

import json

from exposure_workbench.agents import lead
from exposure_workbench.app_state.settings import get_settings
from tests.agent_fakes import FakeTools, ScriptedProvider, Store, install, text_turn, tool, tool_turn, view_fixture
from tests.test_observer_views import CORRECT, Q

ASK = ("ask", {"tasks": [{"analyst": "issuer", "scope": {"subjects": ["AAPL", "MSFT", "NVDA"], "expected_count": 5},
                          "lines": ["cash conversion, latest twelve months against the comparable twelve months before, ranked"]}]})
NOTE = ("On the latest twelve months MSFT converts best at 135.9%, AAPL at 114.4% and NVDA weakest at 69.7%; "
        "against the comparable twelve months a year earlier NVDA fell 19.3 percentage points while AAPL rose 1.79 percentage points.")


def _setup(monkeypatch, turns):
    view = view_fixture()
    facts = view.pop("_facts")
    store = Store()
    provider = ScriptedProvider(turns)
    lead_face = FakeTools([tool("list"), tool("analyze")], {"analyze": lambda a: dict(view)})
    issuer_face = FakeTools([tool("list"), tool("analyze"), tool("filings_search")], {"analyze": lambda a: dict(view)})
    db_factory = install(monkeypatch, provider=provider, faces={"lead": lead_face, "issuer": issuer_face}, store=store,
                         ledger_records=facts)
    return store, provider, lead_face, issuer_face, db_factory


async def test_the_specialist_analyses_writes_prose_and_the_lead_reads_it_in_the_work_view(monkeypatch):
    store, provider, lead_face, issuer_face, db_factory = _setup(
        monkeypatch, [tool_turn(ASK), tool_turn(("analyze", {"requests": [{"measure": "cash_conversion", "compare": "previous_ttm", "rank": True}]})),
                      text_turn(NOTE), text_turn(CORRECT)])
    out = await lead.handle_message(db_factory, "sess", Q, message_id="msg_1")

    # the specialist's analyze carried the task's scope, bound by the runtime
    assert issuer_face.calls[0][0] == "analyze" and issuer_face.calls[0][1]["scope"]["subjects"] == ["AAPL", "MSFT", "NVDA"]
    assert issuer_face.calls[0][2] == {"actor": "sub:issuer", "task_id": store.reports[0]["task_id"]}
    # its record: returned, its prose, the observer's reading, no form
    rep = store.reports[0]
    assert rep["status"] == "returned" and rep["text"] == NOTE and rep["verified"]["supported"] == 5
    assert rep["brief"]["stop_reason"] == "finished" and rep["brief"]["analyses"] and "submission" not in json.dumps(rep)
    # the lead's ask returned a receipt; the next request's tail carried the note and the whole view, once
    receipt = json.loads(next(i["output"] for i in provider.requests[3]["input_items"] if i.get("type") == "function_call_output"))
    assert receipt["returns"][0]["status"] == "returned" and receipt["returns"][0]["verification"]["supported"] == 5
    tail = provider.requests[3]["input_items"][-1]["content"][0]["text"]
    state = json.loads(tail.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert state["notes"][0]["text"] == NOTE and state["notes"][0]["report"] == "rep_1"
    assert state["analyses"] and state["analyses"][0]["by"] == "sub:issuer" and state["analyses_seen"] == []
    # the specialist's own requests: task first, then the budget tail, never a pointer rule
    first = provider.requests[1]
    assert "<task " in first["input_items"][0]["content"][0]["text"] and first["input_items"][-1]["role"] == "developer"
    assert "[f_" not in first["instructions"] and "repair_answer" not in first["instructions"]
    assert out["meta"]["delivery"] == "answered"
    assert out["meta"]["reports"] == [{"domain": "issuer", "task_id": rep["task_id"], "report_id": "rep_1",
                                       "status": "returned", "title": "the issuer analyst"}]
    assert out["meta"]["tasks"][0]["stop_reason"] == "finished"


async def test_a_specialist_out_of_budget_keeps_only_open_and_is_told_to_write(monkeypatch):
    monkeypatch.setattr(get_settings(), "specialist_evidence_calls", 1)
    one = ("analyze", {"requests": [{"measure": "cash_conversion"}]})
    store, provider, lead_face, issuer_face, db_factory = _setup(
        monkeypatch, [tool_turn(ASK), tool_turn(one), tool_turn(one), text_turn(NOTE), text_turn(CORRECT)])
    await lead.handle_message(db_factory, "sess", Q, message_id="msg_2")
    # the second analyze was refused by the runtime, not sent to the face, and the next request offered `open` alone
    assert len(issuer_face.calls) == 1
    refused = [json.loads(i["output"]) for i in provider.requests[3]["input_items"] if i.get("type") == "function_call_output"]
    assert any(o.get("error") == "budget_exhausted" for o in refused)
    assert [t["name"] for t in provider.requests[3]["tools"]] == ["open"]
    assert "none left" in provider.requests[3]["input_items"][-1]["content"][0]["text"]
    assert store.reports[0]["brief"]["pending"]


async def test_a_specialist_that_never_writes_is_recorded_as_stopped_and_the_lead_goes_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "specialist_max_turns", 2)
    one = ("analyze", {"requests": [{"measure": "cash_conversion"}]})
    store, provider, lead_face, issuer_face, db_factory = _setup(
        monkeypatch, [tool_turn(ASK), tool_turn(one), tool_turn(one), text_turn(CORRECT)])
    out = await lead.handle_message(db_factory, "sess", Q, message_id="msg_3")
    rep = store.reports[0]
    assert rep["status"] == "stopped" and rep["brief"]["stop_reason"] == "turn_limit" and rep["text"] is None
    receipt = json.loads(next(i["output"] for i in provider.requests[3]["input_items"] if i.get("type") == "function_call_output"))
    assert receipt["returns"][0]["status"] == "stopped" and "verification" not in receipt["returns"][0]
    assert out["meta"]["delivery"] == "answered" and out["meta"]["reports"] == []
