"""
Exposure update handler — executes the full exposure workflow for a given run.

Phase 2: calls ExposureWorkflow.run() with real analytics.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.errors import speaks_for_itself
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.services import exposure_run_service, market_data_service
from exposure_workbench.workflow.contracts import WorkflowInput
from exposure_workbench.workflow.exposure_workflow import ExposureWorkflow

logger = logging.getLogger(__name__)


async def handle(db: AsyncSession, task: Any) -> None:
    """Main entry point called by the worker polling loop."""
    payload = task.payload or {}
    run_id = payload.get("run_id")
    portfolio_id = payload.get("portfolio_id")
    as_of_date_str = payload.get("as_of_date")

    if not run_id:
        raise ValueError(f"Task {task.id} missing run_id in payload")
    if not portfolio_id:
        raise ValueError(f"Task {task.id} missing portfolio_id in payload")

    logger.info("[exposure_update] Starting run %s for portfolio %s", run_id, portfolio_id)

    # Mark run as running
    await exposure_run_service.update_run_status(db, run_id, "running")
    await db.commit()

    settings = get_settings()

    from datetime import date
    if as_of_date_str:
        as_of_date = date.fromisoformat(as_of_date_str)
    else:
        # Every producer now pins the date at creation, so this is a belt-and-
        # braces path. Fall back to the last completed session rather than the
        # wall clock, which would compare the newest bar against itself.
        as_of_date = await market_data_service.latest_session_date(db)
        if as_of_date is None:
            raise ValueError(f"Task {task.id} has no as_of_date and no prices are loaded")

    workflow = ExposureWorkflow(configs_dir=str(settings.configs_dir))
    workflow_input = WorkflowInput(
        run_id=run_id,
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        configs_dir=str(settings.configs_dir),
    )

    result = await workflow.run(db, workflow_input)

    final_status = result.status  # "completed" or "failed"

    # The terminal status goes on a FRESH session, not the one the workflow just
    # ran on. A step that failed while writing its own event leaves that session
    # aborted, and this write would then raise instead of landing — the task goes
    # terminal (with lease_until cleared, so the reaper never looks at it again)
    # while the run sits at 'running' for ever, which is precisely the stuck-run
    # class the lease was introduced to remove. Reproduced by injecting a fault
    # into the event write.
    from exposure_workbench.db.session import get_session_factory
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001 — the session may be unusable; we are done with it
        logger.warning("could not roll back the workflow session for run %s", run_id, exc_info=True)

    async with get_session_factory()() as status_db, status_db.begin():
        await exposure_run_service.update_run_status(
            status_db,
            run_id,
            final_status,
            # result.error is the workflow's own prose and result.error_code the
            # class it belongs to. The prose is stored as the reader's sentence
            # only when it was written for them — RunRefused, which for this
            # workflow is the common case ("Cannot value this portfolio as of …
            # newest price older than 10 days for: AAPL (30d old)"). Otherwise it
            # is an operator's detail and stays out of the reader's way (V13-S2).
            error_message=(result.error
                           if speaks_for_itself(result.error_code or "") else None),
            error_code=result.error_code,
            error_detail=result.error,
        )

    if final_status == "failed":
        raise RuntimeError(f"Workflow failed: {result.error}")

    logger.info(
        "[exposure_update] Run %s completed. Steps: %s",
        run_id,
        result.steps_completed,
    )
