"""Task service — create, claim, complete, and fail tasks."""

from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Task
from exposure_workbench.utils.ids import new_task_id

WORKER_ID = socket.gethostname()


async def create_task(
    db: AsyncSession,
    task_type: str,
    payload: dict[str, Any] | None = None,
    owner_user_id: str | None = None,
) -> Task:
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
    await db.flush()
    return task


async def complete_task(db: AsyncSession, task_id: str) -> None:
    await db.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(status="completed", completed_at=datetime.now(timezone.utc))
    )


async def fail_task(db: AsyncSession, task_id: str, error: str) -> None:
    await db.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(
            status="failed",
            error_message=error,
            completed_at=datetime.now(timezone.utc),
        )
    )


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
