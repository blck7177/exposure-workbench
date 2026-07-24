"""Reusable workflow step context — writes workflow_events around a step.

Mirrors the pattern ExposureWorkflow uses, factored out so the new readiness /
research workflows share one implementation without touching the existing
(working) exposure workflow. run_id is a free string (workflow_events lost its
FK in P0), so exposure and research runs share this same timeline machinery.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import workflow_event_service

logger = logging.getLogger(__name__)


class step:
    """async context manager: logs 'running' on enter, 'completed'/'failed' on exit.

        async with step(db, run_id, "ingest_filings", "Fetching filings"):
            ...
    """

    def __init__(self, db: AsyncSession, run_id: str, step_name: str, message: str):
        self.db = db
        self.run_id = run_id
        self.step_name = step_name
        self.message = message
        self._start_ms = 0

    async def __aenter__(self):
        self._start_ms = int(time.monotonic() * 1000)
        await workflow_event_service.log_event(
            db=self.db, run_id=self.run_id, step_name=self.step_name,
            status="running", message=self.message,
        )
        await self.db.commit()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int(time.monotonic() * 1000) - self._start_ms
        if exc_type is None:
            status, msg = "completed", self.message
        else:
            status, msg = "failed", f"{self.message} — ERROR: {exc_val}"
        await workflow_event_service.log_event(
            db=self.db, run_id=self.run_id, step_name=self.step_name,
            status=status, message=msg, duration_ms=duration_ms,
        )
        await self.db.commit()
        return False   # never suppress — fail loud


async def mark_skipped(db: AsyncSession, run_id: str, step_name: str, reason: str) -> None:
    """Record a step explicitly skipped by request (distinct from failed)."""
    await workflow_event_service.log_event(
        db=db, run_id=run_id, step_name=step_name, status="skipped", message=reason,
    )
    await db.commit()
