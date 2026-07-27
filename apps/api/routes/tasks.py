"""Task routes — admin view of the task queue."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import require_user
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.models import Task
from exposure_workbench.db.session import get_db

router = APIRouter()


class TaskOut(BaseModel):
    id: str
    type: str
    status: str
    payload: dict[str, Any]
    worker_id: str | None
    claimed_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    retry_count: int   # V2-E1: the reaper is its first writer, so non-zero values start here
    lease_until: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    status: str | None = None,
    limit: int = 50,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    # tasks is a shared system queue (no RLS — the worker must see all); scope this
    # user-facing view to the caller's own tasks by owner (semantic filter).
    q = select(Task).where(Task.owner_user_id == user.user_id).order_by(Task.created_at.desc()).limit(limit)
    if status:
        q = q.where(Task.status == status)
    return list((await db.execute(q)).scalars().all())
