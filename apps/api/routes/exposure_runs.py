"""Exposure run routes — create runs, poll status, get full results."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import optional_user, require_user
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.session import get_db
from exposure_workbench.services import (
    exposure_run_service, market_data_service, portfolio_service, task_service, usage_service,
)

router = APIRouter()


# ─── Nested response models ───────────────────────────────────────────────────

class WorkflowEventOut(BaseModel):
    id: int
    step_name: str
    status: str
    message: str | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExposureMetricsOut(BaseModel):
    portfolio_market_value: float | None
    daily_pnl: float | None
    daily_return: float | None
    gross_exposure: float | None
    net_exposure: float | None
    gross_exposure_pct: float | None
    net_exposure_pct: float | None
    rolling_vol_30d: float | None
    rolling_vol_60d: float | None
    var_95_1d: float | None
    expected_shortfall_95: float | None
    max_drawdown: float | None
    stress_loss_tech: float | None
    stress_loss_rates: float | None
    stress_loss_credit: float | None
    stress_loss_market: float | None

    model_config = {"from_attributes": True}


class SectorExposureOut(BaseModel):
    sector: str
    market_value: float | None
    weight: float | None
    weight_change: float | None

    model_config = {"from_attributes": True}


class IssuerExposureOut(BaseModel):
    ticker: str
    sector: str | None
    market_value: float | None
    weight: float | None
    weight_change: float | None
    daily_pnl: float | None
    daily_return: float | None

    model_config = {"from_attributes": True}


class FactorAttributionOut(BaseModel):
    factor_name: str
    factor_ticker: str | None
    beta: float | None
    factor_return: float | None
    contribution: float | None
    r_squared: float | None

    model_config = {"from_attributes": True}


class RiskAlertOut(BaseModel):
    id: str
    alert_type: str
    severity: str
    entity_type: str | None
    entity_id: str | None
    current_value: float | None
    limit_value: float | None
    utilization: float | None
    message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DailyReportOut(BaseModel):
    id: str
    agent_mode: str | None
    executive_summary: str | None
    key_movements: str | None
    factor_explanation: str | None
    risk_alert_explanation: str | None
    recommended_actions: str | None
    markdown_report: str | None
    confidence_flags: dict[str, Any] = {}
    llm_model: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Run response models ──────────────────────────────────────────────────────

class ExposureRunOut(BaseModel):
    id: str
    portfolio_id: str
    status: str
    as_of_date: date
    task_id: str | None
    triggered_by: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    workflow_events: list[WorkflowEventOut] = []
    metrics: ExposureMetricsOut | None = None
    sector_exposures: list[SectorExposureOut] = []
    issuer_exposures: list[IssuerExposureOut] = []
    factor_attributions: list[FactorAttributionOut] = []
    risk_alerts: list[RiskAlertOut] = []
    daily_report: DailyReportOut | None = None

    model_config = {"from_attributes": True}


class RunSummaryOut(BaseModel):
    id: str
    portfolio_id: str
    status: str
    as_of_date: date
    triggered_by: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Request model ────────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    portfolio_id: str
    # Omit to report on the last completed session, which is what a "daily"
    # report means. An explicit date is honoured exactly — including one the data
    # cannot support, which fails the run loudly rather than reporting a figure
    # for a date nothing was priced on.
    as_of_date: date | None = None
    triggered_by: str = "manual"


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/exposure-runs", response_model=ExposureRunOut, status_code=201)
async def create_exposure_run(
    body: CreateRunRequest,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new exposure run and enqueue a worker task."""
    # The reporting date is resolved here, not by the caller: a browser's "today"
    # is not the market's, and before the close it would compare the newest bar
    # against itself. An explicit date is still honoured exactly.
    as_of = body.as_of_date or await market_data_service.latest_session_date(db)
    if as_of is None:
        raise HTTPException(422, {"error": "no_price_data",
                                  "detail": "no market prices are loaded yet"})

    # You can only run portfolios you own — the public demo is read-only (clone to
    # run). semantic, not security: RLS WITH CHECK is what actually stops the
    # write; this just produces a readable 403 rather than an aborted transaction.
    pf = await portfolio_service.get_portfolio(db, body.portfolio_id)
    if pf is None or pf.owner_id != user.user_id:
        raise HTTPException(403, "You can only run portfolios you own. Clone the demo to run it.")
    try:
        task = await task_service.create_task(
            db,
            task_type="exposure_update",
            payload={
                "portfolio_id": body.portfolio_id,
                "as_of_date": as_of.isoformat(),
                "triggered_by": body.triggered_by,
            },
            owner_user_id=user.user_id,
        )
    except usage_service.QuotaExceeded as e:
        raise HTTPException(429, e.as_dict()) from e
    run = await exposure_run_service.create_run(
        db,
        portfolio_id=body.portfolio_id,
        as_of_date=as_of,
        task_id=task.id,
        triggered_by=body.triggered_by,
    )
    # Link task payload back to run_id
    from sqlalchemy.orm.attributes import flag_modified
    task.payload = {**task.payload, "run_id": run.id}
    flag_modified(task, "payload")
    await db.commit()

    full_run = await exposure_run_service.get_run(db, run.id)
    return full_run


@router.get("/exposure-runs", response_model=list[RunSummaryOut],
            dependencies=[Depends(optional_user)])
async def list_exposure_runs(
    portfolio_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await exposure_run_service.list_runs(db, portfolio_id=portfolio_id, limit=limit)


@router.get("/exposure-runs/{run_id}", response_model=ExposureRunOut,
            dependencies=[Depends(optional_user)])
async def get_exposure_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await exposure_run_service.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
