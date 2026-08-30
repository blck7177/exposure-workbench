"""A run's failure that cannot be recorded is said, not returned (offline).

rrun_5b247ec1db21 (NVDA) sat at `pending` from 2026-08-03. Its task died on an
RLS denial — the run's owner_id is NULL, which predates tenancy, and under the
task's tenant the readiness_precheck insert into workflow_events was refused.
The handler's except-branch then asked update_status to mark the run failed;
update_status could not see the run under that same tenant, took None for
"no such run", and returned. The task was marked failed. The run never was,
and nothing recorded that its record had been lost.

Two changes. update_status raises RunNotVisible instead of returning on an
invisible run — under RLS an invisible row and a nonexistent one are the same
SELECT result, and neither is a reason to say nothing. The handler catches that
second failure, logs it as what it is, and raises the ORIGINAL exception, which
is what the task's error should carry.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from exposure_workbench.services import research_run_service as rrs


async def test_update_status_refuses_to_say_nothing_about_a_run_it_cannot_see(monkeypatch):
    async def invisible(_db, _run_id):
        return None

    monkeypatch.setattr(rrs, "get_run", invisible)
    with pytest.raises(rrs.RunNotVisible) as exc:
        await rrs.update_status(None, "rrun_5b247ec1db21", "failed", error_code="run_failed")
    assert "rrun_5b247ec1db21" in str(exc.value) and "failed" in str(exc.value)


async def test_the_handler_raises_the_workflow_failure_not_the_recording_failure(monkeypatch, caplog):
    from apps.worker.handlers import issuer_research as handler

    workflow_error = RuntimeError('new row violates row-level security policy for table "workflow_events"')

    async def dies(*_a, **_k):
        raise workflow_error

    async def cannot_record(*_a, **_k):
        raise rrs.RunNotVisible("research run 'rrun_x' is not visible to this session")

    @asynccontextmanager
    async def fake_session():
        yield SimpleNamespace()

    monkeypatch.setattr(handler, "run_issuer_research", dies)
    monkeypatch.setattr(handler.research_run_service, "update_status", cannot_record)
    monkeypatch.setattr(handler, "get_session_factory", lambda: fake_session)

    task = SimpleNamespace(id="task_x", payload={"run_id": "rrun_x", "ticker": "NVDA"})
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError) as exc:
            await handler.handle(None, task)

    assert exc.value is workflow_error, "the task's error is the workflow's, not the bookkeeping's"
    said = [r.getMessage() for r in caplog.records]
    assert any("could not be recorded" in m and "rrun_x" in m for m in said), said


async def test_the_handler_still_records_a_failure_it_can_see(monkeypatch):
    from apps.worker.handlers import issuer_research as handler

    async def dies(*_a, **_k):
        raise RuntimeError("EDGAR could not resolve ticker")

    recorded: list[dict] = []

    async def record(_db, run_id, status, **kw):
        recorded.append({"run_id": run_id, "status": status, **kw})

    @asynccontextmanager
    async def fake_session():
        async def commit():
            pass
        yield SimpleNamespace(commit=commit)

    monkeypatch.setattr(handler, "run_issuer_research", dies)
    monkeypatch.setattr(handler.research_run_service, "update_status", record)
    monkeypatch.setattr(handler, "get_session_factory", lambda: fake_session)

    task = SimpleNamespace(id="task_y", payload={"run_id": "rrun_y", "ticker": "NVDA"})
    with pytest.raises(RuntimeError):
        await handler.handle(None, task)
    assert recorded and recorded[0]["run_id"] == "rrun_y" and recorded[0]["status"] == "failed"
    assert recorded[0]["error_code"] == "run_failed"
    assert recorded[0]["error_message"] is None, "a bare RuntimeError's words are not for a reader"
