"""Portfolio routes — list portfolios, get positions, limits, and dashboard."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.session import get_db
from exposure_workbench.services import portfolio_service, exposure_run_service

router = APIRouter()


# ─── Response models ──────────────────────────────────────────────────────────

class PortfolioOut(BaseModel):
    id: str
    name: str
    description: str | None
    currency: str
    base_nav: float | None
    benchmark: str | None
    manager: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class PositionOut(BaseModel):
    id: str
    ticker: str
    asset_class: str
    sector: str | None
    region: str | None
    currency: str
    quantity: float
    cost_basis: float | None
    price: float | None
    market_value: float | None
    as_of_date: date

    model_config = {"from_attributes": True}


class RiskLimitOut(BaseModel):
    id: str
    limit_type: str
    entity_type: str | None
    entity_id: str | None
    warning_level: float
    breach_level: float
    unit: str | None
    is_active: bool

    model_config = {"from_attributes": True}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/portfolios", response_model=list[PortfolioOut])
async def list_portfolios(db: AsyncSession = Depends(get_db)):
    return await portfolio_service.list_portfolios(db)


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioOut)
async def get_portfolio(portfolio_id: str, db: AsyncSession = Depends(get_db)):
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


@router.get("/portfolios/{portfolio_id}/positions", response_model=list[PositionOut])
async def get_positions(
    portfolio_id: str,
    as_of_date: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await portfolio_service.get_positions(db, portfolio_id, as_of_date)


@router.get("/portfolios/{portfolio_id}/limits", response_model=list[RiskLimitOut])
async def get_risk_limits(
    portfolio_id: str,
    db: AsyncSession = Depends(get_db),
):
    return await portfolio_service.get_risk_limits(db, portfolio_id)


# ─── Dashboard endpoint ───────────────────────────────────────────────────────

class DashboardOut(BaseModel):
    portfolio: PortfolioOut
    positions: list[PositionOut]
    limits: list[RiskLimitOut]
    latest_run_id: str | None
    latest_run_status: str | None
    latest_run_date: date | None
    metrics: dict[str, Any] | None
    sector_exposures: list[dict[str, Any]]
    issuer_exposures: list[dict[str, Any]]
    factor_attributions: list[dict[str, Any]]
    risk_alerts: list[dict[str, Any]]
    report_summary: dict[str, Any] | None


@router.get("/portfolios/{portfolio_id}/dashboard", response_model=DashboardOut)
async def get_portfolio_dashboard(
    portfolio_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated portfolio dashboard data in a single request."""
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    positions = await portfolio_service.get_positions(db, portfolio_id)
    limits = await portfolio_service.get_risk_limits(db, portfolio_id)

    latest_run = await exposure_run_service.get_latest_completed_run(db, portfolio_id)

    metrics = None
    sector_exposures: list[dict] = []
    issuer_exposures: list[dict] = []
    factor_attributions: list[dict] = []
    risk_alerts: list[dict] = []
    report_summary = None
    latest_run_id = None
    latest_run_status = None
    latest_run_date = None

    if latest_run:
        latest_run_id = latest_run.id
        latest_run_status = latest_run.status
        latest_run_date = latest_run.as_of_date

        full_run = await exposure_run_service.get_run(db, latest_run.id)
        if full_run:
            if full_run.metrics:
                m = full_run.metrics
                metrics = {
                    "portfolio_market_value": m.portfolio_market_value,
                    "daily_pnl": m.daily_pnl,
                    "daily_return": m.daily_return,
                    "gross_exposure_pct": m.gross_exposure_pct,
                    "net_exposure_pct": m.net_exposure_pct,
                    "rolling_vol_30d": m.rolling_vol_30d,
                    "var_95_1d": m.var_95_1d,
                    "expected_shortfall_95": m.expected_shortfall_95,
                    "max_drawdown": m.max_drawdown,
                    "stress_loss_tech": m.stress_loss_tech,
                    "stress_loss_rates": m.stress_loss_rates,
                    "stress_loss_market": m.stress_loss_market,
                }

            sector_exposures = [
                {"sector": se.sector, "market_value": se.market_value,
                 "weight": se.weight, "weight_change": se.weight_change}
                for se in (full_run.sector_exposures or [])
            ]
            issuer_exposures = [
                {"ticker": ie.ticker, "sector": ie.sector,
                 "market_value": ie.market_value, "weight": ie.weight,
                 "daily_pnl": ie.daily_pnl, "daily_return": ie.daily_return}
                for ie in (full_run.issuer_exposures or [])
            ]
            factor_attributions = [
                {"factor_name": fa.factor_name, "factor_ticker": fa.factor_ticker,
                 "beta": fa.beta, "factor_return": fa.factor_return,
                 "contribution": fa.contribution, "r_squared": fa.r_squared}
                for fa in (full_run.factor_attributions or [])
            ]
            risk_alerts = [
                {"id": ra.id, "alert_type": ra.alert_type, "severity": ra.severity,
                 "entity_type": ra.entity_type, "entity_id": ra.entity_id,
                 "current_value": ra.current_value, "limit_value": ra.limit_value,
                 "utilization": ra.utilization, "message": ra.message}
                for ra in (full_run.risk_alerts or [])
            ]
            if full_run.daily_report:
                rpt = full_run.daily_report
                report_summary = {
                    "id": rpt.id,
                    "executive_summary": rpt.executive_summary,
                    "recommended_actions": rpt.recommended_actions,
                    "markdown_report": rpt.markdown_report,
                    "agent_mode": rpt.agent_mode,
                }

    return DashboardOut(
        portfolio=PortfolioOut.model_validate(portfolio),
        positions=[PositionOut.model_validate(p) for p in positions],
        limits=[RiskLimitOut.model_validate(lim) for lim in limits],
        latest_run_id=latest_run_id,
        latest_run_status=latest_run_status,
        latest_run_date=latest_run_date,
        metrics=metrics,
        sector_exposures=sector_exposures,
        issuer_exposures=issuer_exposures,
        factor_attributions=factor_attributions,
        risk_alerts=risk_alerts,
        report_summary=report_summary,
    )
