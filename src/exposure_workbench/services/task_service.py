"""Task service — create, claim, complete, fail, and reap tasks."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import bindparam, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.db.models import Task
from exposure_workbench.services import usage_service
from exposure_workbench.utils.ids import new_task_id

WORKER_ID = socket.gethostname()

# Which task types survive being run twice — measured against the persistence
# code, NOT assumed. Re-delivery is a WHITELIST because the two omissions are
# actively harmful, not merely wasteful:
#
#   company_readiness  — every step is an upsert or an index short-circuit
#   market_data_sync   — ON CONFLICT DO UPDATE on (ticker, price_date)
#
#   exposure_update    — _persist_outputs is five bare INSERTs against
#                        UNIQUE(run_id...) on exposure_metrics / daily_reports /
#                        sector_exposures / issuer_exposures / factor_attributions,
#                        so a replay raises IntegrityError (and risk_alerts, which
#                        has no unique key, would silently duplicate instead)
#   issuer_research    — issuer_briefs UNIQUE(research_run_id), and submit_brief is
#                        the agent's exit gate, so the collision only fires AFTER a
#                        whole LLM session has been paid for
#
# Anything not listed here is failed on lease expiry rather than replayed. A new
# task type must state its side here explicitly; there is no default.
REQUEUEABLE_TYPES = frozenset({"company_readiness", "market_data_sync"})

LEASE_EXPIRED_ERROR = (
    "lease expired — the worker holding this task stopped reporting. "
    "This task type is not safe to replay, so it was failed rather than requeued; "
    "start it again to retry."
)


# task type -> quota pool. NO default on purpose: a new task type that nobody
# remembered to give a pool raises KeyError here instead of quietly becoming a
# free action. This single mapping covers both surfaces that enqueue work — the
# four REST routes and the three meta-agent delegation tools — which are parallel
# implementations sharing no code, so any charge point above this one would have
# to be written twice and would eventually be written once.
TASK_TYPE_QUOTA_KIND = {
    "exposure_update": "exposure_run",
    "issuer_research": "research_run",
    "company_readiness": "readiness",
    "market_data_sync": "market_sync",
}


async def create_task(
    db: AsyncSession,
    task_type: str,
    payload: dict[str, Any] | None = None,
    owner_user_id: str | None = None,
) -> Task:
    """Enqueue one task, charging the enqueuing user's daily quota.

    The charge shares the caller's transaction, so a caller that later fails and
    rolls back gives the quota back for free. Ownerless work (seeds, the worker's
    own internal calls) is not charged — there is no user to charge, and the
    worker never reaches this function.
    """
    if owner_user_id is not None:
        await usage_service.charge(db, owner_user_id, TASK_TYPE_QUOTA_KIND[task_type])

    task = Task(
        id=new_task_id(),
        type=task_type,
        status="pending",
        payload=payload or {},
        owner_user_id=owner_user_id,   # V2-A: worker restores tenant from this
    )
    db.add(task)
    await db.flush()
    return task


async def claim_next_task(
    db: AsyncSession,
    worker_id: str = WORKER_ID,
) -> Task | None:
    """Claim the oldest pending task. Returns None if no tasks available."""
    result = await db.execute(
        select(Task)
        .where(Task.status == "pending")
        .order_by(Task.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    task = result.scalar_one_or_none()
    if task is None:
        return None

    task.status = "running"
    task.worker_id = worker_id
    task.claimed_at = datetime.now(timezone.utc)
    # Lease deadline comes from the SERVER clock, not this process's. With
    # several worker replicas a skewed local clock would otherwise both steal
    # live tasks (clock ahead) and strand dead ones (clock behind).
    task.lease_until = text("now() + make_interval(secs => :lease_secs)").bindparams(
        lease_secs=get_settings().task_lease_seconds
    )
    await db.flush()
    return task


async def complete_task(db: AsyncSession, task_id: str) -> None:
    await db.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(
            status="completed",
            completed_at=datetime.now(timezone.utc),
            lease_until=None,   # settled: nothing left for the reaper to find
        )
    )


async def fail_task(db: AsyncSession, task_id: str, error: str) -> None:
    await db.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(
            status="failed",
            error_message=error,
            completed_at=datetime.now(timezone.utc),
            lease_until=None,
        )
    )


_REAP_SQL = text("""
WITH expired AS (
    SELECT id,
           (type IN :requeueable AND retry_count < :max_retries) AS requeue
      FROM tasks
     WHERE status = 'running'
       AND lease_until IS NOT NULL
       AND lease_until < now()
     FOR UPDATE SKIP LOCKED
)
UPDATE tasks t
   SET status        = CASE WHEN e.requeue THEN 'pending'          ELSE 'failed' END,
       retry_count   = CASE WHEN e.requeue THEN t.retry_count + 1  ELSE t.retry_count END,
       error_message = CASE WHEN e.requeue THEN NULL               ELSE :expired_msg END,
       completed_at  = CASE WHEN e.requeue THEN NULL               ELSE now() END,
       worker_id     = CASE WHEN e.requeue THEN NULL               ELSE t.worker_id END,
       claimed_at    = CASE WHEN e.requeue THEN NULL               ELSE t.claimed_at END,
       lease_until   = NULL
  FROM expired e
 WHERE t.id = e.id
RETURNING t.id, t.type, t.payload, t.owner_user_id, t.retry_count, t.status
""").bindparams(bindparam("requeueable", expanding=True))


async def reclaim_expired_leases(db: AsyncSession) -> list[dict[str, Any]]:
    """Reap tasks whose lease ran out. Returns one dict per reaped task.

    This is the FIRST of the reaper's two transactions and it deliberately runs
    with NO tenant set: tasks carries no RLS, so one batch statement can settle
    every user's expired work at once. Marking the associated runs failed is the
    caller's second transaction, one per task and each under its own tenant —
    they cannot be merged, because a single RLS failure on exposure_runs aborts
    the whole transaction it is in, which would turn one bad row into a reaper
    that dies every cycle.

    All timestamps and the expiry comparison use the SERVER clock, matching how
    the lease was stamped. FOR UPDATE SKIP LOCKED keeps two workers' reapers from
    both settling the same task.
    """
    settings = get_settings()
    rows = await db.execute(
        _REAP_SQL,
        {
            "requeueable": list(REQUEUEABLE_TYPES),
            "max_retries": settings.task_max_retries,
            "expired_msg": LEASE_EXPIRED_ERROR,
        },
    )
    return [dict(r) for r in rows.mappings().all()]


async def get_task(db: AsyncSession, task_id: str) -> Task | None:
    result = await db.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


async def list_tasks(
    db: AsyncSession,
    status: str | None = None,
    limit: int = 50,
) -> list[Task]:
    q = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if status:
        q = q.where(Task.status == status)
    result = await db.execute(q)
    return list(result.scalars().all())
