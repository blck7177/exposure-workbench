"""Exposure run routes — create runs, poll status, get full results."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import optional_user, require_user
from apps.api.schemas import WorkflowEventOut
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.session import get_db
from exposure_workbench.services import (
    exposure_run_service, market_data_service, portfolio_service, task_service, usage_service,
)

router = APIRouter()


# ─── Nested response models ───────────────────────────────────────────────────

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
    # V13-S2. The code is on the wire; `error_detail` deliberately is NOT.
    #
    # The plan for this batch said the field could ride along because RLS
    # decides row visibility — which is true and beside the point: the demo book
    # is PUBLIC, so every anonymous visitor can read its runs, and a detail
    # column carrying "http://exposure-mcp:8000/mcp/research could not be
    # reached" would put the internal hostname back on the wire the moment
    # anyone opened devtools. That is the exact hole this batch closes, so the
    # honest fix is not a permission branch on the field but not serving it:
    # error_detail is written for the operator and read with psql, which is what
    # the audit layer of a one-person desk is today. A signed-in reader's own
    # runs can get it back through an owner-only endpoint when something needs
    # it; that is its own batch, not a field quietly widened here.
    error_code: str | None = None
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


# What a run started through this route is called, and the client does not get a
# say (V13-S1). `triggered_by` was a free string on the request body, so every
# acceptance script that ever posted one wrote its own label into an audit column
# on a book strangers read: five of the twenty runs on the public demo said
# `v8-p-live-acceptance`, `v5_validation`, `v5_deploy_check`, `v2h4_verification`.
# The label is a fact about which door the run came through, and the door knows.
# The other two values are minted where they are true: `agent:<session>` in
# meta_tools, `seed` by the seed script, both through the service.
_TRIGGERED_BY_API = "manual"


# ─── Request model ────────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    portfolio_id: str
    # Omit to report on the last completed session, which is what a "daily"
    # report means. An explicit date is honoured exactly — including one the data
    # cannot support, which fails the run loudly rather than reporting a figure
    # for a date nothing was priced on.
    as_of_date: date | None = None


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
                "triggered_by": _TRIGGERED_BY_API,
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
        triggered_by=_TRIGGERED_BY_API,
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
