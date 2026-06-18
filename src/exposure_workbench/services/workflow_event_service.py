"""Workflow event service — log step-level events for UI timeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import WorkflowEvent


async def log_event(
    db: AsyncSession,
    run_id: str,
    step_name: str,
    status: str = "running",
    message: str | None = None,
    payload_summary: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> WorkflowEvent:
    event = WorkflowEvent(
        run_id=run_id,
        step_name=step_name,
        status=status,
        message=message,
        payload_summary=payload_summary or {},
        duration_ms=duration_ms,
    )
    db.add(event)
    await db.flush()
    return event
