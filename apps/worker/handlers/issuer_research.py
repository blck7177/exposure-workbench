"""issuer_research task handler (M8 capability C).

Uses the session factory (not the single handler db) because the research agent
loop opens a fresh session per tool call so trace/ledger rows commit as they
happen. On failure the run is marked failed and the error re-raised (fail-loud).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.errors import classify, detail_of, speaks_for_itself
from exposure_workbench.db.session import get_session_factory
from exposure_workbench.services import research_run_service
from exposure_workbench.workflow.issuer_research_workflow import run_issuer_research

logger = logging.getLogger(__name__)


async def handle(db: AsyncSession, task: Any) -> None:
    payload = task.payload or {}
    run_id = payload.get("run_id")
    ticker = payload.get("ticker")
    if not run_id or not ticker:
        raise ValueError(f"issuer_research task {task.id} missing run_id/ticker")

    factory = get_session_factory()
    logger.info("[issuer_research] %s (run %s)", ticker, run_id)
    try:
        await run_issuer_research(
            factory, run_id, ticker,
            skip_external_research=bool(payload.get("skip_external_research")),
            skip_market_refresh=bool(payload.get("skip_market_refresh")),
        )
    except Exception as exc:
        logger.error("[issuer_research] run %s failed: %s", run_id, exc, exc_info=True)
        # str(exc) used to go straight into error_message and straight onto
        # the issuer page: a provider's 429 JSON, an internal hostname, a
        # note this desk wrote to itself. Now the KIND goes in error_code,
        # the exception's own words go in error_detail for the audit layer,
        # and error_message carries a sentence only when the failure's words
        # were written for a reader in the first place (V13-S2).
        code = classify(exc)
        try:
            async with factory() as db2:
                await research_run_service.update_status(
                    db2, run_id, "failed",
                    error_message=str(exc) if speaks_for_itself(code) else None,
                    error_code=code,
                    error_detail=detail_of(exc),
                )
                await db2.commit()
        except Exception as record_exc:  # noqa: BLE001 — the ORIGINAL failure is the one to raise
            # The run's record of its own failure is what was lost here, and
            # it is lost for the same reason the run failed: this task's tenant
            # cannot see the run. rrun_5b247ec1db21 sat at `pending` for 27 days
            # behind a silent return on exactly this path. Say it where an
            # operator reads, then raise the workflow's exception — that is
            # what the task's error should carry, not this one.
            logger.error("[issuer_research] run %s failed AND its failure could not be "
                         "recorded on the run: %s", run_id, record_exc, exc_info=True)
        raise
