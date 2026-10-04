"""One user turn through the lead loop, offline: the analysis the model asks for,
the draft the observer reads, the feedback it gets, the record it leaves."""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import lead
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.db.models import AgentMessage
from tests.agent_fakes import FakeTools, ScriptedProvider, Store, install, text_turn, tool, tool_turn, view_fixture
from tests.test_observer_views import CORRECT, Q, WRONG_UNITS

ANALYZE = ("analyze", {"requests": [{"measure": "cash_conversion", "compare": "previous_ttm", "rank": True},
                                    {"measure": "book.weight", "compare": "previous_run", "rank": True}],
                       "scope": {"book": "port_001", "sector": "Technology", "expected_count": 5}})


def _setup(monkeypatch, turns, *, faces=None):
    view = view_fixture()
    facts = view.pop("_facts")
    store = Store()
    provider = ScriptedProvider(turns)
    lead_face = FakeTools([tool("list"), tool("analyze")], {"analyze": lambda args: dict(view), "list": {"names": []}})
    db_factory = install(monkeypatch, provider=provider, faces={"lead": lead_face, **(faces or {})}, store=store,
                         ledger_records=facts)
    return store, provider, lead_face, db_factory


async def test_the_q07_turn_analyses_once_is_corrected_once_and_delivers_a_verified_answer(monkeypatch):
    store, provider, face, db_factory = _setup(monkeypatch, [tool_turn(ANALYZE), text_turn(WRONG_UNITS), text_turn(CORRECT)])
    out = await lead.handle_message(db_factory, "sess", Q, message_id="msg_1")

    # the model ran the analysis once, with the scope it chose, and wrote twice
    assert [c[0] for c in face.calls] == ["analyze"] and face.calls[0][1]["scope"]["expected_count"] == 5
    assert len(provider.requests) == 3
    # the work view travels as the LAST input item of every request, and the feedback came as business text
    for req in provider.requests:
        assert req["input_items"][-1]["role"] == "developer" and "<state " in req["input_items"][-1]["content"][0]["text"]
    fed = [i for i in provider.requests[2]["input_items"] if i.get("role") == "developer"]
    assert any("do not hold as written" in i["content"][0]["text"] for i in fed)
    assert not any("f_" in i["content"][0]["text"] and "repair" in i["content"][0]["text"] for i in fed)
    # the analysis arrived as a tool output and the ledger holds its cells
    outputs = [i for i in provider.requests[1]["input_items"] if i.get("type") == "function_call_output"]
    assert outputs and json.loads(outputs[0]["output"])["view"].startswith("calc_")

    meta = out["meta"]
    assert out["text"] == CORRECT and meta["delivery"] == "answered"
    assert meta["verified"]["figures"] == 8 == meta["verified"]["supported"]
    assert meta["completion"]["status"] == "full" and meta["feedback_rounds"] == 1
    assert meta["analyses"][0]["by"] == "lead" and meta["analyses"][0]["scope_status"] == "mismatch"
    assert len(out["citations"]) == 8
    kinds = [b["type"] for b in meta["blocks"]]
    assert kinds.count("paragraph") == 3 and kinds[-1] == "table"
    chips = [r for b in meta["blocks"] if b["type"] == "paragraph" for r in b["runs"] if isinstance(r, dict)]
    assert any(r["fact"]["display"] == "-19.3 pp" for r in chips)

    # the record: three completions, two drafts (one refused, one accepted), the assistant message, the work view
    assert [s["step_type"] for s in store.steps].count("llm_call") == 3
    answers = [s for s in store.steps if s["step_type"] == "answer"]
    assert [a["status"] for a in answers] == ["rejected", "completed"]
    assert answers[0]["args"]["problems"] and answers[0]["args"]["text"] == WRONG_UNITS
    saved = [r for r in store.rows if isinstance(r, AgentMessage) and r.role == "assistant"]
    assert saved and saved[0].meta["delivery"] == "answered" and saved[0].content == CORRECT
    assert store.work_views and store.work_views[-1]["views"][0]["view"].startswith("calc_")


async def test_a_draft_that_still_fails_after_the_feedback_rounds_is_delivered_marked(monkeypatch):
    monkeypatch.setattr(get_settings(), "observer_feedback_rounds", 1)
    store, provider, face, db_factory = _setup(monkeypatch, [tool_turn(ANALYZE), text_turn(WRONG_UNITS), text_turn(WRONG_UNITS)])
    out = await lead.handle_message(db_factory, "sess", Q, message_id="msg_2")
    assert out["meta"]["delivery"] == "answered_with_problems"
    assert out["meta"]["verified"]["contradicted"] >= 4 and out["text"] == WRONG_UNITS
    assert out["meta"]["validation"]["propositions"]        # the problems travel with the answer, as data


async def test_an_analysis_without_a_scope_is_refused_and_the_budget_bounds_analyses(monkeypatch):
    monkeypatch.setattr(get_settings(), "lead_evidence_calls", 1)
    no_scope = ("analyze", {"requests": [{"measure": "cash_conversion"}]})
    store, provider, face, db_factory = _setup(
        monkeypatch, [tool_turn(no_scope), tool_turn(ANALYZE), tool_turn(ANALYZE), text_turn(CORRECT)])
    out = await lead.handle_message(db_factory, "sess", Q, message_id="msg_3")
    outputs = [json.loads(i["output"]) for req in provider.requests for i in req["input_items"] if i.get("type") == "function_call_output"]
    errors = [o.get("error") for o in outputs if o.get("error")]
    assert "scope_required" in errors and "budget_exhausted" in errors
    assert len(face.calls) == 1                               # one analysis reached the face
    assert out["meta"]["delivery"] == "answered"


async def test_a_turn_with_no_text_at_all_is_delivered_as_not_answered(monkeypatch):
    store, provider, face, db_factory = _setup(monkeypatch, [tool_turn(ANALYZE), text_turn(""), text_turn("")])
    out = await lead.handle_message(db_factory, "sess", Q, message_id="msg_4")
    assert out["meta"]["delivery"] == "not_answered" and out["text"] == ""
    assert out["meta"]["completion"]["status"] == "unknown"
