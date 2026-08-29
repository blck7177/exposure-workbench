"""Research run service (M8) — mirrors exposure_run_service for issuer_research."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import ResearchRun
from exposure_workbench.utils.ids import new_research_run_id


class ActiveRunExists(Exception):
    def __init__(self, run_id: str):
        super().__init__(f"An active research run already exists: {run_id}")
        self.run_id = run_id


async def get_active_run(db: AsyncSession, company_id: str) -> ResearchRun | None:
    return (
        await db.execute(
            select(ResearchRun).where(
                ResearchRun.company_id == company_id,
                ResearchRun.status.in_(["pending", "running"]),
            ).order_by(ResearchRun.created_at.desc())
        )
    ).scalars().first()


async def create_run(
    db: AsyncSession, company_id: str, portfolio_id: str | None, triggered_by: str, task_id: str | None,
    owner_id: str | None = None,
) -> ResearchRun:
    existing = await get_active_run(db, company_id)
    if existing is not None:
        raise ActiveRunExists(existing.id)
    run = ResearchRun(
        id=new_research_run_id(), company_id=company_id, portfolio_id=portfolio_id,
        owner_id=owner_id,   # V2-A tenancy
        status="pending", triggered_by=triggered_by, task_id=task_id,
    )
    db.add(run)
    await db.flush()
    return run


async def get_run(db: AsyncSession, run_id: str) -> ResearchRun | None:
    return (await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))).scalar_one_or_none()


async def update_status(
    db: AsyncSession, run_id: str, status: str, error_message: str | None = None,
    agent_session_id: str | None = None,
    error_code: str | None = None, error_detail: str | None = None,
) -> None:
    """Move a run along, and — when it stopped — record why in three parts.

    `error_message` is the sentence a person is shown and is written ONLY when
    the failure's own words were meant for them (V13-S2); `error_code` says which
    kind of failure it was and is what the UI keys its wording on; `error_detail`
    is the exception's own words, for the audit layer.

    A caller that passes a raw provider string as error_message is the defect
    this signature exists to make visible: pass the exception to classify() and
    detail_of() instead, and let the code decide what the reader is told.
    """
    run = await get_run(db, run_id)
    if run is None:
        return
    run.status = status
    if status == "running" and run.started_at is None:
        run.started_at = datetime.now(timezone.utc)
    if status in ("completed", "failed"):
        run.completed_at = datetime.now(timezone.utc)
    if error_message is not None:
        run.error_message = error_message
    if error_code is not None:
        run.error_code = error_code
    if error_detail is not None:
        run.error_detail = error_detail
    if agent_session_id is not None:
        run.agent_session_id = agent_session_id
    await db.flush()
