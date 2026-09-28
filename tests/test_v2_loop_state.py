"""V2 P3 (design v0.4 §06, acceptance A3): the lead's loop runs on the analysis
state — requirements declared on the first ask, the STATE block refreshed before
every completion, a reply that leaves a requirement unaddressed refused once and
then delivered as partial with the reader told what stayed open, a bounded
requirement counted as completed_with_boundaries. Offline, on the gate harness:
the check, the protocol, the ledger and the state are real; the provider and the
tool face are scripted.
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
    full = [{"analyst": "risk", "subjects": ["port_001"], "lines": ["how big MSFT is in the book"], **t} for t in tasks]
    args = {"tasks": full, **({"requirements": requirements} if requirements else {})}
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
async def test_a_reply_that_leaves_a_requirement_is_refused_once_and_then_goes_out_partial(monkeypatch):
    _no_db_state(monkeypatch)
    chat, lead, _sub = _script(
        [("", _ask(REQS, {"for": ["R1"]})), (ROW, None), (ROW, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)

    out = await meta_agent.handle_message(_factory([]), "sess_1", Q)

    assert out["meta"]["completion"] == "partial"
    assert [(r["id"], r["status"]) for r in out["meta"]["requirements"]] == [("R1", "covered"), ("R2", "unresolved")]
    assert out["text"].startswith("MSFT weighs 16.0%") and "Still open: “what will its weight be next year”" in out["text"]
    assert out["meta"]["blocks"][-1] == {"type": "paragraph", "runs": [out["text"].split("\n\n")[-1]]}
    assert out["meta"]["gate_refusals"] if "gate_refusals" in out["meta"] else True
    # the first reply was refused for coverage, not for its sentences: the lead was told in words and asked again
    told = lead[2][-1]["content"]
    assert "[R2] what will its weight be next year" in told and "partial answer" in told
    # the STATE block was in every completion and said what stood: R1 covered with its row, R2 unresolved
    before, after = _state_of(lead[0]), _state_of(lead[1])
    assert before["requirements"] == [] and before["findings"] == []
    assert [(r["id"], r["status"]) for r in after["requirements"]] == [("R1", "covered"), ("R2", "unresolved")]
    assert after["findings"][0]["rows"][0].startswith("[f_wmsft0001] issuer exposures: weight, MSFT")
    assert after["tasks"][0]["status"] == "settled"


@pytest.mark.asyncio
async def test_a_requirement_the_desk_cannot_settle_is_a_boundary_and_the_turn_completes_with_boundaries(monkeypatch):
    _no_db_state(monkeypatch)
    reply = ROW + " The desk does not forecast next year's weight [f_policy_no_forecast]."
    chat, lead, _sub = _script(
        [("", _ask(REQS, {"for": [["R1"], ["R2"]], "lines": ["how big MSFT is in the book", "MSFT's weight next year"]})),
         (reply, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]},
                                     {"n": 2, "settled": False, "why": "the desk does not forecast",
                                      "boundary": "f_policy_no_forecast"}]))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)

    out = await meta_agent.handle_message(_factory([]), "sess_1", Q)

    assert out["meta"]["completion"] == "completed_with_boundaries"
    assert [(r["id"], r["status"]) for r in out["meta"]["requirements"]] == [("R1", "covered"), ("R2", "boundary")]
    assert "Still open" not in out["text"]
    state = _state_of(lead[1])
    assert state["gaps"][0]["type"] == "policy_boundary" and state["gaps"][0]["for"] == ["R2"]
    assert state["gaps"][0]["boundary"].startswith("[f_policy_no_forecast] absent:")


@pytest.mark.asyncio
async def test_what_the_handoff_refused_never_reaches_the_state_block(monkeypatch):
    """A3 on the real write-and-project path: the analyst's refused line — an
    invented forecast — is on the record as refused and appears in no STATE block."""
    _no_db_state(monkeypatch)
    invented = {"n": 2, "settled": True, "finding": "MSFT will weigh 20.0% of the book next year.", "facts": ["f_wmsft0001"]}
    chat, lead, _sub = _script(
        [("", _ask(REQS, {"for": [["R1"], ["R2"]], "lines": ["how big MSFT is in the book", "MSFT's weight next year"]})),
         (ROW, None), (ROW, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}, invented])),
         ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}, invented]))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)

    out = await meta_agent.handle_message(_factory([]), "sess_1", Q)

    state = _state_of(lead[1])
    assert "20.0%" not in json.dumps(state) and state["findings"][0]["text"] == ROW
    assert out["meta"]["delegations"][0]["status"] == "partial", "the brief half passed"
    assert out["meta"]["completion"] == "partial", "R2 has neither a finding nor a boundary"


@pytest.mark.asyncio
async def test_a_bad_declaration_is_answered_not_ended(monkeypatch):
    _no_db_state(monkeypatch)
    bad = [{"id": "R1", "anchor": "MSFT's forecast weight"}]
    chat, lead, _sub = _script(
        [("", _ask(bad, {"for": ["R1"]})), ("", _ask(REQS, {"for": ["R1"]})), (ROW, None), (ROW, None)],
        [("", _run()), ("", _submit([{"n": 1, "settled": True, "finding": ROW, "facts": ["f_wmsft0001"]}]))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)

    out = await meta_agent.handle_message(_factory([]), "sess_1", Q)
    told = json.loads(lead[1][-1]["content"])
    assert told["error"] == "invalid_ask" and "not a span of the user's words" in told["detail"]
    assert out["text"].startswith("MSFT weighs 16.0%")
