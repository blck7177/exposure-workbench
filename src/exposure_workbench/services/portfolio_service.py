"""Portfolio service — portfolios, positions, and the portfolio-level snapshot.

The issuer tools are all ticker-scoped; a question like "what fundamental risk is
my portfolio most exposed to" has no ticker to start from. `snapshot_all` is the
missing orthogonal read: it surfaces the desk's portfolio(s), their latest
exposure metrics, largest sector/issuer weights and active alerts — the entry
point the agent discovers holdings from, so it never asks the user for an
internal id. Every portfolio number is produced by an exposure run, so the
snapshot carries that run_id; run_ resolves through the evidence resolver and
passes the citation gate, so a portfolio-level claim is cited like an issuer one.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Portfolio, Position, RiskLimit
from exposure_workbench.services import exposure_run_service

_TOP_SECTORS = 8
_TOP_ISSUERS = 10


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


# ── portfolio snapshot (agent entry point) ────────────────────────────────────

def _f(v) -> float | None:
    return float(v) if v is not None else None


def _metrics(m) -> dict | None:
    if m is None:
        return None
    return {
        "market_value": _f(m.portfolio_market_value),
        "daily_pnl": _f(m.daily_pnl),
        "daily_return": _f(m.daily_return),
        "gross_exposure_pct": _f(m.gross_exposure_pct),
        "net_exposure_pct": _f(m.net_exposure_pct),
        "rolling_vol_30d": _f(m.rolling_vol_30d),
        "var_95_1d": _f(m.var_95_1d),
        "max_drawdown": _f(m.max_drawdown),
    }


async def _snapshot_one(db: AsyncSession, p: Portfolio) -> dict:
    base = {
        "portfolio_id": p.id, "name": p.name, "benchmark": p.benchmark,
        "currency": p.currency, "manager": p.manager,
    }
    latest = await exposure_run_service.get_latest_completed_run(db, p.id)
    if latest is None:
        # No completed run yet — honest empty, not fabricated zeros.
        return {**base, "run_id": None, "as_of_date": None,
                "metrics": None, "top_sectors": [], "top_issuers": [], "alerts": []}

    run = await exposure_run_service.get_run(db, latest.id)  # eager-loaded relations
    top_sectors = sorted(run.sector_exposures, key=lambda s: (s.weight or 0), reverse=True)[:_TOP_SECTORS]
    top_issuers = sorted(run.issuer_exposures, key=lambda i: (i.weight or 0), reverse=True)[:_TOP_ISSUERS]
    return {
        **base,
        "run_id": run.id,
        "as_of_date": run.as_of_date.isoformat(),
        "metrics": _metrics(run.metrics),
        "top_sectors": [
            {"sector": s.sector, "weight": _f(s.weight), "market_value": _f(s.market_value)}
            for s in top_sectors
        ],
        "top_issuers": [
            {"ticker": i.ticker, "sector": i.sector, "weight": _f(i.weight),
             "market_value": _f(i.market_value), "daily_return": _f(i.daily_return)}
            for i in top_issuers
        ],
        # alert_type (not "type") so the evidence walker harvests a clean alert ref
        # off the id, not one typed by the alert category.
        "alerts": [
            {"id": a.id, "alert_type": a.alert_type, "severity": a.severity,
             "entity_id": a.entity_id, "message": a.message, "utilization": _f(a.utilization)}
            for a in run.risk_alerts
        ],
    }


async def snapshot_all(db: AsyncSession) -> list[dict]:
    """Every active portfolio the desk manages, latest exposure state first.

    Returns a list (data-driven: one portfolio today, many later, same shape) —
    no "default portfolio" rule.
    """
    portfolios = await list_portfolios(db, active_only=True)
    return [await _snapshot_one(db, p) for p in portfolios]
