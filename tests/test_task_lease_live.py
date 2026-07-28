"""E1 — the reaper's three branches, against a real database (live).

Run with:  pytest -m live -k task_lease_live

The decision is one SQL statement, so it cannot be exercised offline; what
test_task_lease.py guards is the classification around it. Here we plant tasks
with already-expired leases and check what the reaper does with each:

  requeueable, under the cap  -> pending, retry_count + 1, error cleared
  requeueable, at the cap     -> failed
  not replayable              -> failed regardless of retry_count
  a live (unexpired) lease    -> untouched

and, separately, that phase 2 marks the associated run failed under the task's
own tenant — the part that has to be its own transaction.

Setup and teardown connect as the table owner because app_rls holds no DELETE
grant. The reap itself runs as app_rls with NO tenant set, which is exactly how
the worker calls it: tasks carries no RLS, so one batch statement settles every
user's expired work.
"""

from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from apps.worker import worker
from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.services import task_service

pytestmark = pytest.mark.live

OWNER_URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)
APP_URL = os.getenv(
    "DATABASE_URL_LOCAL_APP",
    "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench",
)

TAG = f"lease_{uuid.uuid4().hex[:8]}"       # namespaces every row this run creates
DEMO_PORTFOLIO = "port_001"
DEMO_USER = "user_demo_system"


@pytest.fixture
async def owner():
    engine = create_async_engine(OWNER_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield mk
    finally:
        async with mk() as db, db.begin():
            await db.execute(text("DELETE FROM tasks WHERE id LIKE :p"), {"p": f"task_{TAG}%"})
            await db.execute(text("DELETE FROM exposure_runs WHERE id LIKE :p"), {"p": f"run_{TAG}%"})
        await engine.dispose()


@pytest.fixture
async def app_rls(monkeypatch):
    """The worker's own factory, pointed at the app role."""
    engine = create_async_engine(APP_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(worker, "get_session_factory", lambda: mk)
    try:
        yield mk
    finally:
        await engine.dispose()


async def _plant(owner_mk, suffix, task_type, *, retry_count=0, expired=True, payload=None,
                 owner_user_id=DEMO_USER):
    """Insert a 'running' task whose lease is already in the past (or not)."""
    task_id = f"task_{TAG}_{suffix}"
    async with owner_mk() as db, db.begin():
        await db.execute(
            text("""
                INSERT INTO tasks (id, type, status, payload, worker_id, claimed_at,
                                   lease_until, retry_count, owner_user_id)
                VALUES (:id, :type, 'running', CAST(:payload AS jsonb), 'dead-worker', now(),
                        now() + make_interval(secs => :offset), :retry, :owner)
            """),
            {
                "id": task_id, "type": task_type,
                "payload": __import__("json").dumps(payload or {}),
                "offset": -60 if expired else 3600,
                "retry": retry_count, "owner": owner_user_id,
            },
        )
    return task_id


async def _row(owner_mk, task_id):
    async with owner_mk() as db:
        r = await db.execute(
            text("SELECT status, retry_count, error_message, lease_until, worker_id "
                 "FROM tasks WHERE id = :id"), {"id": task_id})
        return r.mappings().one()


async def test_reaper_three_branches_and_the_untouched_case(owner, app_rls):
    requeue = await _plant(owner, "requeue", "company_readiness", retry_count=0)
    at_cap = await _plant(owner, "atcap", "market_data_sync", retry_count=3)   # == task_max_retries
    not_safe = await _plant(owner, "notsafe", "exposure_update", retry_count=0,
                            payload={"run_id": f"run_{TAG}_x", "portfolio_id": DEMO_PORTFOLIO})
    alive = await _plant(owner, "alive", "company_readiness", expired=False)

    # A running worker reaps on its own poll interval, so it may well settle
    # these before this call does. The outcome is what is under test, not which
    # reaper produced it — asserting "my call returned these ids" made this test
    # flaky against a live stack, which is the environment it is meant to model.
    async with app_rls() as db, db.begin():
        await task_service.reclaim_expired_leases(db)

    r = await _row(owner, requeue)
    assert r["status"] == "pending", "replay-safe type under the cap goes back on the queue"
    assert r["retry_count"] == 1
    assert r["error_message"] is None
    assert r["lease_until"] is None and r["worker_id"] is None, "requeued work must look unclaimed"

    r = await _row(owner, at_cap)
    assert r["status"] == "failed", "retry cap reached — stop replaying"
    assert r["retry_count"] == 3, "the cap is not exceeded by the failing pass"
    assert "lease expired" in r["error_message"]

    r = await _row(owner, not_safe)
    assert r["status"] == "failed", "exposure_update must never be replayed"
    assert r["retry_count"] == 0, "types that are never replayed do not accrue retries"
    assert "lease expired" in r["error_message"]
    assert r["worker_id"] == "dead-worker", "failed tasks keep who held them, for forensics"

    r = await _row(owner, alive)
    assert r["status"] == "running" and r["retry_count"] == 0, (
        "a lease that has not expired must never be reaped, by any reaper"
    )


async def test_phase_two_marks_the_run_failed_under_the_tasks_own_tenant(owner, app_rls):
    run_id = f"run_{TAG}_p2"
    async with owner() as db, db.begin():
        await db.execute(
            text("""INSERT INTO exposure_runs (id, portfolio_id, status, as_of_date)
                    VALUES (:id, :p, 'running', CURRENT_DATE)"""),
            {"id": run_id, "p": DEMO_PORTFOLIO},
        )
    task_id = await _plant(owner, "p2", "exposure_update",
                           payload={"run_id": run_id, "portfolio_id": DEMO_PORTFOLIO})

    async with app_rls() as db, db.begin():
        reaped = await task_service.reclaim_expired_leases(db)

    # A live worker's reaper may have taken this row first; rebuild the same dict
    # from the settled task so the phase-2 call under test still runs either way.
    row = next((r for r in reaped if r["id"] == task_id), None)
    if row is None:
        async with owner() as db:
            row = dict((await db.execute(
                text("SELECT id, type, payload, owner_user_id, retry_count, status "
                     "FROM tasks WHERE id = :id"), {"id": task_id})).mappings().one())
        assert row["status"] == "failed", "exposure_update must never be requeued"

    current_user_ctx.set(None)   # the reaper's phase 1 runs tenant-less; phase 2 must set its own
    await worker._fail_run_for(row)

    async with owner() as db:
        r = (await db.execute(
            text("SELECT status, error_message, completed_at FROM exposure_runs WHERE id = :id"),
            {"id": run_id})).mappings().one()
    assert r["status"] == "failed", "a reaped run left in 'running' is the stuck-run bug E1 removes"
    assert "lease expired" in r["error_message"]
    assert r["completed_at"] is not None


async def test_types_without_a_run_row_are_reaped_without_phase_two(owner, app_rls):
    """company_readiness logs under its own task id and market_data_sync has no run
    at all — phase 2 must be a no-op for them, not an error."""
    readiness = await _plant(owner, "noRun", "company_readiness", retry_count=3)
    async with app_rls() as db, db.begin():
        await task_service.reclaim_expired_leases(db)
    settled = await _row(owner, readiness)
    assert settled["status"] == "failed"
    async with owner() as db:
        row = dict((await db.execute(
            text("SELECT id, type, payload, owner_user_id, retry_count, status "
                 "FROM tasks WHERE id = :id"), {"id": readiness})).mappings().one())
    await worker._fail_run_for(row)     # must not raise
