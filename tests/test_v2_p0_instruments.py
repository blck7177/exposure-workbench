"""V2 P0a — the instruments read a turn whole (offline: no DB, no network, no LLM).

Three holes the design (v0.4 §04 G7) named in what a round can read back:
the battery's export was narrower than the row it exported; a refused reply
draft was cut at 4,000 characters on the only step that holds it; a turn that
died in an exception had no message id, so its steps were orphaned. None of
these is behaviour a model sees — that is what lets this package be committed
alone and its hash be the baseline round E is measured on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.api.routes import agent as agent_route
from exposure_workbench.agents import meta_agent
from exposure_workbench.agents.tool_session import ToolFaceUnavailable
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.models import AgentStep
from exposure_workbench.services import agent_session_service, trace_service, usage_service
from tests.test_meta_agent_gate import _factory, _stub_desk, _stub_llm, _stub_tools

ROOT = Path(__file__).resolve().parents[1]


class _RecDb:
    """A session that remembers what was added; enough for record_step."""

    def __init__(self, rows: list):
        self.rows = rows

    async def execute(self, *_a, **_k):
        return SimpleNamespace(scalar_one=lambda: 1, first=lambda: None)

    def add(self, obj):
        self.rows.append(obj)

    async def flush(self): pass
    async def commit(self): pass
    def begin(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *_exc): return False


# ── the battery exports the row at the row's own width ───────────────────────

@pytest.mark.asyncio
async def test_the_battery_exports_full_json_and_task_provenance():
    from tests.test_v32_instrument import _script
    battery = _script("conversation_battery")
    rows = []
    draft = "x" * 10000
    await trace_service.record_step(_RecDb(rows), "sess", step_type="answer", tool_name="answer",
                                    args={"text": draft, "problems": [{"reason": "unsourced_figure"}]},
                                    result_summary="refused", evidence_refs=["f_w1a2b3c4d5e6"],
                                    task_id="tsk_1", unbounded=("text",))
    row = rows[0]
    class ExportDb:
        async def execute(self, stmt, params):
            query = str(stmt).lower()
            assert "left(" not in query and "substring(" not in query
            assert "args::text as args" in query and "task_id" in query and "evidence_refs" in query
            assert params == {"s": "sess", "m": "msg"}
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [
                {"args": json.dumps(row.args), "task_id": row.task_id, "evidence_refs": row.evidence_refs}]))
    [exported] = await battery.export_steps(ExportDb(), "sess", "msg")
    assert json.loads(exported["args"])["text"] == draft
    assert exported["task_id"] == "tsk_1" and exported["evidence_refs"] == ["f_w1a2b3c4d5e6"]


def test_the_battery_mints_the_turn_id_and_keeps_it_on_an_exception():
    src = (ROOT / "scripts" / "conversation_battery.py").read_text(encoding="utf-8")
    assert 'mid = new_id("msg_")' in src
    assert "message_id=mid" in src, "the id the battery minted is the id the loop runs under"
    assert 'res, error = {"message_id": mid}' in src, "an exception keeps the id, so the steps are read back"


# ── the refused draft is kept whole ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_answer_step_keeps_the_whole_draft_and_other_steps_keep_the_cap():
    rows: list = []
    long = "x" * 10_000
    await trace_service.record_step(_RecDb(rows), "sess_1", step_type="answer", tool_name="answer",
                                    args={"text": long, "problems": []}, result_summary="refused",
                                    evidence_refs=[], unbounded=("text",))
    await trace_service.record_step(_RecDb(rows), "sess_1", step_type="tool_call", tool_name="filings_search",
                                    args={"query": long}, result_summary="1 row", evidence_refs=[])
    answer, call = rows
    assert len(answer.args["text"]) == 10_000, "the draft is the record; it is not cut"
    assert len(call.args["query"]) == trace_service.MAX_ARG_CHARS
    assert call.args["query"].endswith("…[truncated]"), "every other argument keeps the cap"


@pytest.mark.asyncio
async def test_the_lead_records_its_refused_reply_unbounded(monkeypatch):
    seen: dict = {}

    async def _record(db, session_id, **kw):
        seen.update(kw)
        return "step_1"

    monkeypatch.setattr(meta_agent.trace_service, "record_step", _record)
    text = "y" * 9_000
    verdict = SimpleNamespace(ok=False, error="unsourced_figure", detail="one number", problems=[])
    await meta_agent._record_answer(_factory([]), "sess_1", "msg_1", text, verdict)
    assert seen["unbounded"] == ("text",)
    assert seen["args"]["text"] == text, "text[:4000] is gone: the step carries the draft the check refused"
    assert seen["status"] == "rejected"


# ── the turn's id survives the turn ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_loop_runs_under_the_id_its_caller_minted(monkeypatch):
    async def _greets(**_kw):
        return "Hello. Ask me about the book.", None

    _stub_llm(monkeypatch, _greets)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    out = await meta_agent.handle_message(_factory([]), "sess_1", "hi", message_id="msg_given")
    assert out["message_id"] == "msg_given"
    again = await meta_agent.handle_message(_factory([]), "sess_1", "hi")
    assert again["message_id"].startswith("msg_"), "None keeps the old behaviour: the loop mints one"


class _Route:
    """The route with its gate stubbed, as tests/test_tool_session drives it."""

    def __init__(self, monkeypatch, rows: list):
        async def _get_session(db, session_id):
            return SimpleNamespace(last_prompt_tokens=0)

        async def _claim_turn(db, session_id):
            return "stamp"

        async def _release_turn(session_id, claimed_at=None):
            return None

        async def _charge(db, user_id, action):
            return None

        monkeypatch.setattr(agent_route, "get_session_factory", lambda: (lambda: _RecDb(rows)))
        monkeypatch.setattr(agent_session_service, "get_session", _get_session)
        monkeypatch.setattr(agent_session_service, "claim_turn", _claim_turn)
        monkeypatch.setattr(agent_session_service, "release_turn", _release_turn)
        monkeypatch.setattr(usage_service, "charge", _charge)
        self.monkeypatch = monkeypatch

    async def failing_with(self, exc: Exception) -> HTTPException:
        async def _raise(*_a, **_k):
            raise exc

        self.monkeypatch.setattr(agent_route, "handle_message", _raise)
        with pytest.raises(HTTPException) as caught:
            await agent_route.post_message("sess_1", agent_route.MessageIn(text="what changed at NVDA"),
                                           user=UserClaims(user_id="user_1"), db=None)
        return caught.value


@pytest.mark.asyncio
async def test_a_turn_that_dies_names_its_message_and_leaves_a_turn_error_step(monkeypatch):
    rows: list = []
    route = _Route(monkeypatch, rows)
    answer = await route.failing_with(ToolFaceUnavailable("issuer", "http://exposure-mcp:8000/mcp/issuer", "connect_error"))
    assert answer.status_code == 503
    mid = answer.detail["message_id"]
    assert mid.startswith("msg_")
    step = next(r for r in rows if isinstance(r, AgentStep))
    assert step.step_type == "turn_error" and step.status == "error"
    assert step.message_id == mid, "the step hangs off the id the body carries"
    assert step.args == {"error": "tool_face_unavailable"}
    assert "exposure-mcp" not in json.dumps(answer.detail) and "exposure-mcp" not in step.result_summary, \
        "the internal hostname stays in the process log"


@pytest.mark.asyncio
async def test_the_413_and_the_500_paths_leave_the_same_step(monkeypatch):
    rows: list = []
    route = _Route(monkeypatch, rows)
    answer = await route.failing_with(RuntimeError("BadRequestError: context_length_exceeded — 200000 tokens"))
    assert answer.status_code == 413 and answer.detail["message_id"].startswith("msg_")
    assert [r.args["error"] for r in rows if isinstance(r, AgentStep)] == ["session_context_exhausted"]

    async def _raise(*_a, **_k):
        raise ValueError("a bug in the loop")

    monkeypatch.setattr(agent_route, "handle_message", _raise)
    with pytest.raises(ValueError):
        await agent_route.post_message("sess_1", agent_route.MessageIn(text="x"),
                                       user=UserClaims(user_id="user_1"), db=None)
    assert [r.args["error"] for r in rows if isinstance(r, AgentStep)][-1] == "turn_failed", \
        "a bare 500 still leaves the row; the exception itself is re-raised unchanged"
