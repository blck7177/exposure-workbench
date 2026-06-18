"""Portfolio service — portfolios and positions."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Portfolio, Position, RiskLimit


async def get_portfolio(db: AsyncSession, portfolio_id: str) -> Portfolio | None:
    result = await db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id)
    )
    return result.scalar_one_or_none()


async def list_portfolios(db: AsyncSession, active_only: bool = True) -> list[Portfolio]:
    q = select(Portfolio).order_by(Portfolio.name)
    if active_only:
        q = q.where(Portfolio.is_active == True)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_positions(
    db: AsyncSession,
    portfolio_id: str,
    as_of_date: date | None = None,
) -> list[Position]:
    q = (
        select(Position)
        .where(Position.portfolio_id == portfolio_id)
        .order_by(Position.market_value.desc())
    )
    if as_of_date:
        q = q.where(Position.as_of_date == as_of_date)
    else:
        # Latest available date
        latest_q = (
            select(Position.as_of_date)
            .where(Position.portfolio_id == portfolio_id)
            .order_by(Position.as_of_date.desc())
            .limit(1)
        )
        latest_result = await db.execute(latest_q)
        latest_date = latest_result.scalar_one_or_none()
        if latest_date:
            q = q.where(Position.as_of_date == latest_date)

    result = await db.execute(q)
    return list(result.scalars().all())


async def get_positions_latest(
    db: AsyncSession,
    portfolio_id: str,
) -> list[Position]:
    """Get positions for the most recent available date."""
    return await get_positions(db, portfolio_id, as_of_date=None)


async def get_risk_limits(
    db: AsyncSession,
    portfolio_id: str,
    active_only: bool = True,
) -> list[RiskLimit]:
    q = select(RiskLimit).where(RiskLimit.portfolio_id == portfolio_id)
    if active_only:
        q = q.where(RiskLimit.is_active == True)
    result = await db.execute(q)
    return list(result.scalars().all())
