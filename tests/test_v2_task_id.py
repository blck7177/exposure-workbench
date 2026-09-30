"""V2 P2: which TASK a step belongs to travels beside the actor (design v0.4 G4/G7).

The bearer says whose turn, the call's metadata says which agent made it (V37)
and now which task it served; the trace writes both, and two tasks of one
analyst can be told apart on the steps — which log_from_steps needed before
parallel_analysts could ever be switched on. Offline.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from exposure_workbench.agents import delegation as dl, sub_analyst as sa
from exposure_workbench.agents.tool_session import ToolSession
from exposure_workbench.tools import primitives as P, registry as R
from tests.mcp_mount import RecordingDb, connected, mounted, use_secret
from tests.test_mcp_identity_binding import FACE, FACE_TOOLS, _registry
from tests.test_v1_analyst import SETTLED, _Tools, _ctx, _read, _submit, TASK


async def test_invoke_writes_the_task_on_every_step_it_records(monkeypatch):
    steps: list[dict] = []

    async def _record(db, session_id, **kw):
        steps.append(kw)
        return f"step_{len(steps)}"

    async def _reserve(db, session_id, is_external_search=False, message_id=None):
        pass

    monkeypatch.setattr(R.trace_service, "record_step", _record)
    monkeypatch.setattr(R.sess, "reserve", _reserve)
    reg = P.build_analyst_registry("risk")
    # arguments that do not fit: a rejected step AND a boundary step, both tagged
    await R.invoke(reg, SimpleNamespace(add=lambda *_: None, flush=_noop, rollback=_noop), "sess", "book_read",
                   {"book": "port_001", "table": "not_a_table", "why": "w"}, message_id="msg_1",
                   actor="sub:risk", task_id="tsk_a")
    assert [s["step_type"] for s in steps] == ["tool_call", "boundary"]
    assert {s["task_id"] for s in steps} == {"tsk_a"} and {s["actor"] for s in steps} == {"sub:risk"}


async def _noop(*_a, **_k):
    return None


async def test_the_client_carries_the_task_beside_the_actor():
    seen: list = []

    class _Client:
        async def call_tool(self, name, args, meta=None):
            seen.append(meta)
            return SimpleNamespace(content=[SimpleNamespace(text='{"ok": true}')])

    session = ToolSession(_Client(), [])
    await session.call("list", {"what": "metrics"}, actor="sub:issuer", task_id="tsk_1")
    await session.call("list", {"what": "metrics"})
    assert seen == [{"actor": "sub:issuer", "task_id": "tsk_1"}, None]


async def test_the_task_reaches_the_trace_through_the_real_mount(monkeypatch):
    use_secret(monkeypatch)
    db = RecordingDb()
    async with mounted(_registry(), FACE_TOOLS, face_name=FACE, db_factory=lambda: db) as door:
        async with connected(door, face_name=FACE, user_id="user_a", session_id="sess_a", message_id="msg_a") as client:
            await client.call_tool("whoami", {}, meta={"actor": "sub:issuer", "task_id": "tsk_mount"})
    [step] = db.added
    assert (step.actor, step.task_id, step.session_id, step.message_id) == ("sub:issuer", "tsk_mount", "sess_a", "msg_a")


@pytest.mark.asyncio
async def test_the_analyst_names_its_task_on_its_calls_and_its_own_steps(monkeypatch):
    class _TaggedTools(_Tools):
        def __init__(self):
            super().__init__()
            self.task_ids: list = []

        async def call(self, name, args, *, actor=None, task_id=None):
            self.task_ids.append(task_id)
            return await super().call(name, args, actor=actor, task_id=task_id)

    tools = _TaggedTools()
    ctx, _seen, steps, stored = _ctx(monkeypatch, [("", _read()), ("", _submit(SETTLED))], tools)
    result = await sa.run_sub_analyst(TASK, ctx)
    assert result.status == "returned"
    assert tools.task_ids == [TASK.task_id]
    # _record is faked in this harness without a task_id column; the report carries TaskState
    [accepted] = stored[0]["accepted_lines"]
    assert accepted["text"] == SETTLED["finding"] and accepted["refs"] == SETTLED["facts"]
    assert accepted["kind"] == "note" and accepted["validation"]
    assert accepted["validation"]["version"] == sa.AS.BOUNDARY_VERSION
    assert set(accepted["validation"]["facts"]) == set(SETTLED["facts"])
    assert stored[0]["attempts"] == 1
    assert stored[0]["input_version"]["ledger_rows"] == 1 and stored[0]["receipts"] == []


def test_two_tasks_of_one_analyst_are_told_apart_by_their_tag():
    """With parallel_analysts the two would interleave under one actor; with the tag
    each log holds its own calls, and the report boundary still ends a stretch."""
    def call(task, verb, i):
        return {"step_type": "tool_call", "tool_name": verb, "actor": "sub:risk", "task_id": task, "status": "completed",
                "args": {"why": f"{task} line 1", "book": "port_001"}, "result_summary": f"r_{i:06d} {verb}(book=\"port_001\") → 1 row"}

    steps = [call("tsk_a", "list", 1), call("tsk_b", "book_read", 2), call("tsk_a", "metric", 3),
             {"step_type": "report", "tool_name": "report", "actor": "sub:risk", "task_id": "tsk_a",
              "args": {"task_id": "tsk_a"}, "status": "completed", "result_summary": "verified"},
             call("tsk_b", "calc", 4)]
    a = dl.Task("tsk_a", "risk", ("port_001",), ("x",))
    b = dl.Task("tsk_b", "risk", ("port_001",), ("y",))
    assert [ln.split(". ", 1)[1].split("(")[0] for ln in dl.log_from_steps(a, steps, "settled").splitlines()[1:-1]] == ["list", "metric"]
    assert [ln.split(". ", 1)[1].split("(")[0] for ln in dl.log_from_steps(b, steps, "settled").splitlines()[1:-1]] == ["book_read", "calc"]
