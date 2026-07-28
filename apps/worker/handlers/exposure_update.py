"""
Exposure update handler — executes the full exposure workflow for a given run.

Phase 2: calls ExposureWorkflow.run() with real analytics.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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
    await exposure_run_service.update_run_status(
        db,
        run_id,
        final_status,
        error_message=result.error,
    )
    await db.commit()

    if final_status == "failed":
        raise RuntimeError(f"Workflow failed: {result.error}")

    logger.info(
        "[exposure_update] Run %s completed. Steps: %s",
        run_id,
        result.steps_completed,
    )
