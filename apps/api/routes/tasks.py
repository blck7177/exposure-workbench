"""Task routes — admin view of the task queue."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.session import get_db
from exposure_workbench.services import task_service

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
    retry_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    return await task_service.list_tasks(db, status=status, limit=limit)
