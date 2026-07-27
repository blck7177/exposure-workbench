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
from exposure_workbench.db.session import get_session_factory
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
            await fail_task(db, task.id, f"No handler for task type '{task.type}'")
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
            await complete_task(db, task.id)
            await db.commit()
            logger.info(f"Task {task.id} completed successfully")

    except Exception as exc:
        logger.error(f"Task {task.id} failed: {exc}", exc_info=True)
        factory2 = get_session_factory()
        async with factory2() as db2:
            await fail_task(db2, task.id, str(exc))
            await db2.commit()
    finally:
        current_user_ctx.reset(ctx_token)

    return True


async def run_worker() -> None:
    settings = get_settings()
    poll_interval = settings.worker_poll_interval
    logger.info(f"Worker started — polling every {poll_interval}s")

    while _running:
        try:
            processed = await process_one()
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
