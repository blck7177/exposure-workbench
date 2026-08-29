"""
Exposure Workbench Worker — async polling loop.

Polls the tasks table every WORKER_POLL_INTERVAL seconds,
claims pending tasks, and dispatches them to the appropriate handler.

Usage:
    python -m apps.worker.worker
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Bootstrap path and env before any internal imports
ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.auth import internal_token
from exposure_workbench.db.session import get_session_factory
from exposure_workbench.services import exposure_run_service, research_run_service, task_service
from exposure_workbench.services.task_service import claim_next_task, complete_task, fail_task

# The worker is a system process; each task runs under the tenant of the user who
# enqueued it (owner_user_id) so RLS writes land, falling back to the demo system
# user for ownerless/system tasks.
#
# The parenthetical that used to end that sentence — "readiness touches only
# shared tables anyway" — was false and hid a bug for two phases: every workflow
# step writes workflow_events, which IS an RLS table, and its policy knew only
# the exposure-run and research-run parents. Readiness logs under
# run_id = task.id, matched nothing, and so had never once completed. Any new
# task type that runs a workflow must have a matching parent branch in that
# policy (infra/init.sql, mirrored in the migration, guarded by
# tests/test_rls_parity.py).
DEMO_SYSTEM_USER = "user_demo_system"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

# Lazy import handlers to avoid circular issues at startup
HANDLERS: dict[str, object] = {}


def _get_handler(task_type: str):
    if task_type not in HANDLERS:
        if task_type == "exposure_update":
            from apps.worker.handlers.exposure_update import handle
            HANDLERS[task_type] = handle
        elif task_type == "market_data_sync":
            from apps.worker.handlers.market_data_sync import handle
            HANDLERS[task_type] = handle
        elif task_type == "company_readiness":
            from apps.worker.handlers.company_readiness import handle
            HANDLERS[task_type] = handle
        elif task_type == "issuer_research":
            from apps.worker.handlers.issuer_research import handle
            HANDLERS[task_type] = handle
        else:
            return None
    return HANDLERS[task_type]


_running = True


def _handle_signal(sig, frame):
    global _running
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    _running = False


async def process_one() -> bool:
    """Claim and process one task. Returns True if a task was processed."""
    factory = get_session_factory()
    async with factory() as db:
        task = await claim_next_task(db)
        if task is None:
            return False

        await db.commit()
        logger.info(f"Claimed task {task.id} (type={task.type})")

    handler = _get_handler(task.task_type if hasattr(task, "task_type") else task.type)
    if handler is None:
        logger.warning(f"No handler for task type '{task.type}', skipping task {task.id}")
        async with factory() as db:
            await fail_task(db, task.id, f"No handler for task type '{task.type}'")  # fenced; see task_service
            await db.commit()
        return True

    # Run the handler under the enqueuing user's tenant (set BEFORE the session's
    # first query so the RLS listener applies it to the whole transaction).
    tenant = getattr(task, "owner_user_id", None) or DEMO_SYSTEM_USER
    ctx_token = current_user_ctx.set(tenant)
    try:
        async with factory() as db:
            # Re-fetch task in new session
            from sqlalchemy import select
            from exposure_workbench.db.models import Task
            result = await db.execute(select(Task).where(Task.id == task.id))
            fresh_task = result.scalar_one()
            await handler(db, fresh_task)
            settled = await complete_task(db, task.id)
            await db.commit()
            if settled:
                logger.info(f"Task {task.id} completed successfully")
            else:
                # Our lease expired mid-flight and the reaper handed this task on.
                # Whatever we just wrote may now be duplicated or superseded, so
                # say so loudly rather than report a success we no longer own.
                logger.warning(
                    f"Task {task.id} finished but was no longer ours — the lease expired "
                    f"and it was reclaimed. TASK_LEASE_SECONDS may be too low for this work."
                )

    except Exception as exc:
        logger.error(f"Task {task.id} failed: {exc}", exc_info=True)
        factory2 = get_session_factory()
        async with factory2() as db2:
            if not await fail_task(db2, task.id, str(exc)):
                logger.warning(f"Task {task.id} failed but had already been reclaimed; left alone")
            await db2.commit()
    finally:
        current_user_ctx.reset(ctx_token)

    return True


# How to reach a failed task's run, per task type: (lookup, mark-failed). Only
# the two non-replayable types have a run row at all — company_readiness logs
# under the task's own id and market_data_sync has no run concept — so their
# absence here is the design, not an oversight. The two services spell the
# updater differently (update_run_status vs update_status), hence the pair.
_RUN_FAILERS = {
    "exposure_update": (exposure_run_service.get_run, exposure_run_service.update_run_status),
    "issuer_research": (research_run_service.get_run, research_run_service.update_status),
}


async def _fail_run_for(task_row: dict) -> None:
    """Mark one reaped task's run failed, under that task's own tenant.

    Its own transaction, on purpose. exposure_runs' RLS policy passes reads via
    `p.is_public` but requires ownership on write, so a WITH CHECK violation here
    aborts the entire transaction it runs in — batching these would let one bad
    row take down the whole reap, every cycle, forever.
    """
    run_id = (task_row.get("payload") or {}).get("run_id")
    failer = _RUN_FAILERS.get(task_row["type"])
    if not run_id or failer is None:
        return
    get_run, mark_failed = failer

    # Must be set before the session's first query: the after_begin listener
    # reads the contextvar when the transaction opens, not when it commits.
    tenant = task_row.get("owner_user_id") or DEMO_SYSTEM_USER
    ctx_token = current_user_ctx.set(tenant)
    try:
        factory = get_session_factory()
        async with factory() as db, db.begin():
            # Both update helpers return silently when the run is not visible,
            # which under RLS is indistinguishable from success. Check first so a
            # tenant mistake shows up in the log instead of vanishing.
            run = await get_run(db, run_id)
            if run is None:
                logger.error(
                    "Reaped task %s: run %s not visible as tenant %s — run left as-is",
                    task_row["id"], run_id, tenant,
                )
                return
            if run.status not in ("pending", "running"):
                # It finished under its own steam between the lease expiring and
                # this reap; overwriting a completed run with 'failed' would
                # discard a real result.
                logger.info(
                    "Reaped task %s: run %s already %s — left alone",
                    task_row["id"], run_id, run.status,
                )
                return
            # The sentence was already written for the reader (task_service);
            # the code beside it is what lets the UI recognise this failure
            # rather than pattern-match its prose (V13-S2).
            await mark_failed(db, run_id, "failed",
                              error_message=task_service.LEASE_EXPIRED_ERROR,
                              error_code="lease_expired")
            logger.warning("Reaped task %s: marked run %s failed", task_row["id"], run_id)
    except Exception as exc:
        logger.error("Reaped task %s: could not fail run %s: %s", task_row["id"], run_id, exc)
    finally:
        current_user_ctx.reset(ctx_token)


async def reap_stale_leases() -> None:
    """Settle every task whose lease has expired. Two phases, two transactions."""
    factory = get_session_factory()
    async with factory() as db, db.begin():
        reaped = await task_service.reclaim_expired_leases(db)

    for row in reaped:
        logger.warning(
            "Reaped task %s (type=%s) -> %s (retry_count=%s)",
            row["id"], row["type"], row["status"], row["retry_count"],
        )
        if row["status"] == "failed":
            await _fail_run_for(row)


async def run_worker() -> None:
    settings = get_settings()
    # Same reasoning as the api's lifespan check (R5): a research run mints an
    # internal bearer, so no key means no run — and without this the discovery
    # happens on the first task, after its quota is spent, with the run marked
    # failed for a reason that has nothing to do with the issuer.
    internal_token.require_secret()
    poll_interval = settings.worker_poll_interval
    logger.info(f"Worker started — polling every {poll_interval}s")

    while _running:
        try:
            processed = await process_one()

            # Reaping belongs here, not in process_one: that function returns
            # early on an empty queue — exactly when stale leases most need
            # collecting — and on a busy queue it is re-entered back-to-back with
            # no delay, which would spin the reaper once per task. Its own try
            # block so a persistently failing reap degrades to noise in the log
            # instead of starving task processing.
            try:
                await reap_stale_leases()
            except Exception as exc:
                logger.error(f"Lease reaper failed: {exc}", exc_info=True)

            if not processed:
                # No tasks available — wait before next poll
                await asyncio.sleep(poll_interval)
        except Exception as exc:
            logger.error(f"Unexpected error in worker loop: {exc}", exc_info=True)
            await asyncio.sleep(poll_interval)

    logger.info("Worker stopped")


def main() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
