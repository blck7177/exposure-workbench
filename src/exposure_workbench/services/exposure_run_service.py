"""Exposure run service — create and manage workflow runs."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import ExposureRun
from exposure_workbench.utils.ids import new_run_id


async def create_run(
    db: AsyncSession,
    portfolio_id: str,
    as_of_date: date,
    task_id: str | None = None,
    triggered_by: str = "manual",
) -> ExposureRun:
    run = ExposureRun(
        id=new_run_id(),
        portfolio_id=portfolio_id,
        as_of_date=as_of_date,
        status="pending",
        task_id=task_id,
        triggered_by=triggered_by,
    )
    db.add(run)
    await db.flush()
    return run


async def get_run(db: AsyncSession, run_id: str) -> ExposureRun | None:
    result = await db.execute(
        select(ExposureRun)
        .where(ExposureRun.id == run_id)
        .options(
            selectinload(ExposureRun.workflow_events),
            selectinload(ExposureRun.metrics),
            selectinload(ExposureRun.risk_alerts),
            selectinload(ExposureRun.daily_report),
            selectinload(ExposureRun.sector_exposures),
            selectinload(ExposureRun.issuer_exposures),
            selectinload(ExposureRun.factor_attributions),
        )
    )
    return result.scalar_one_or_none()


async def list_runs(
    db: AsyncSession,
    portfolio_id: str | None = None,
    limit: int = 20,
) -> list[ExposureRun]:
    q = select(ExposureRun).order_by(ExposureRun.created_at.desc()).limit(limit)
    if portfolio_id:
        q = q.where(ExposureRun.portfolio_id == portfolio_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_run_status(
    db: AsyncSession,
    run_id: str,
    status: str,
    error_message: str | None = None,
    error_code: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Move a run along, and — when it stopped — record why in three parts.

    Same shape as research_run_service.update_status, deliberately: one idea of
    what "a run that stopped" says (V13-S2). error_message carries a sentence
    only when it was written for the reader — which for this workflow is the
    common case, since RunRefused names the stale holdings and the way out.
    """
    result = await db.execute(select(ExposureRun).where(ExposureRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        return

    run.status = status
    if status == "running" and run.started_at is None:
        run.started_at = datetime.now(timezone.utc)
    if status in ("completed", "failed"):
        run.completed_at = datetime.now(timezone.utc)
    if error_message:
        run.error_message = error_message
    if error_code:
        run.error_code = error_code
    if error_detail:
        run.error_detail = error_detail
    await db.flush()


async def get_latest_completed_run(
    db: AsyncSession,
    portfolio_id: str,
    before_run_id: str | None = None,
) -> ExposureRun | None:
    """Get the most recent completed run for a portfolio, optionally excluding a specific run."""
    q = (
        select(ExposureRun)
        .where(
            ExposureRun.portfolio_id == portfolio_id,
            ExposureRun.status == "completed",
        )
        .order_by(ExposureRun.as_of_date.desc(), ExposureRun.completed_at.desc())
        .limit(1)
    )
    if before_run_id:
        q = q.where(ExposureRun.id != before_run_id)
    result = await db.execute(q)
    return result.scalar_one_or_none()
