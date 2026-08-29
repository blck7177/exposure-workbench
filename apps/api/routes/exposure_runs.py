"""Exposure run routes — create runs, poll status, get full results."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import optional_user, require_user
from apps.api.schemas import WorkflowEventOut
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.models import LimitCheck, StressResult
from exposure_workbench.db.session import get_db
from exposure_workbench.analytics import display_names as dn, factor_model
from exposure_workbench.services import (
    calc_service, exposure_run_service, market_data_service, portfolio_service,
    reconcile_service, task_service, usage_service,
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


def _f(v) -> float | None:
    """A Numeric column as a float, or None. Every chart read goes through it so
    a Decimal never reaches JSON as a string and a null never becomes a zero —
    the second is the one that matters: a check that recorded nothing and a check
    that measured zero are different facts."""
    return None if v is None else float(v)


# ── chart reads (V13-S5) ──────────────────────────────────────────────────────
#
# Every one of these serves a panel and none of them computes anything new. They
# read what a run already recorded, or call the same service the agent's own tool
# calls, so a figure on a chart and the same figure in an answer come from one
# place. A panel that recomputed would be a second opinion nobody asked for and
# free to differ in the third decimal, which is where trust in a risk page goes.


@router.get("/exposure-runs/{run_id}/limit-book", dependencies=[Depends(optional_user)])
async def run_limit_book(run_id: str, db: AsyncSession = Depends(get_db)):
    """Every mandate check this run evaluated, with what it measured.

    All twenty-seven, not the two that raised something. "Two warnings" alone
    leaves the reader to assume the rest were checked and fine, which is the
    assumption V8-P3 established was not safe to make — and even once it is safe,
    a book sitting at 93% of a tier and one at 28% are different books.
    """
    run = await exposure_run_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(404, {"error": "unknown_run", "run_id": run_id})

    rows = (await db.execute(
        select(LimitCheck).where(LimitCheck.run_id == run_id).order_by(LimitCheck.limit_type)
    )).scalars().all()

    out = []
    for r in rows:
        limit_type, _, entity = r.limit_type.partition(":")
        group = ("Stress" if limit_type == "stress_loss"
                 else "Issuer" if limit_type == "issuer_concentration"
                 else "Sector" if limit_type == "sector_concentration"
                 else "Portfolio")
        name = dn.label("limit", limit_type)
        if entity:
            entity_label = (dn.label("sector", entity) if limit_type == "sector_concentration"
                            else dn.label("scenario", entity) if limit_type == "stress_loss"
                            else entity)
            name = f"{entity_label} · {name.lower()}" if limit_type != "stress_loss" else entity_label
        out.append({
            "key": r.limit_type,
            "label": name,
            "group": group,
            "fired": r.fired,
            "alert_id": r.alert_id,
            "current": _f(r.current_value),
            "warning": _f(r.warning_level),
            "breach": _f(r.breach_level),
            "status": r.status,
            # The share of the way to a BREACH, which is what "utilisation"
            # means on an alert row and is the one number that orders these
            # against each other. None where the run did not record the tiers —
            # rows written before V13 were not backfilled, and a utilisation
            # computed from today's thresholds would describe a check that never
            # ran against them.
            "utilisation": (None if r.current_value is None or not r.breach_level
                            else round(float(r.current_value) / float(r.breach_level), 6)),
        })
    unrecorded = sum(1 for r in rows if r.current_value is None)
    return {
        "run_id": run_id, "as_of": run.as_of_date.isoformat(),
        "checks": out,
        "detail": (None if not unrecorded else
                   f"{unrecorded} of {len(rows)} checks ran before this desk recorded "
                   "what they measured, so their levels are not shown"),
    }


@router.get("/exposure-runs/{run_id}/stress", dependencies=[Depends(optional_user)])
async def run_stress(run_id: str, db: AsyncSession = Depends(get_db)):
    """The scenarios, their shocks, and what each one leaves standing still.

    `factors_held_flat` is the honest half and the reason this is not just a bar
    chart: a market-downside scenario says nothing about high-yield credit, so
    HYG is held at zero while the book's beta to it is 1.29. That is an
    assertion about the world, not an absence of one.
    """
    run = await exposure_run_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(404, {"error": "unknown_run", "run_id": run_id})
    rows = (await db.execute(
        select(StressResult).where(StressResult.run_id == run_id)
        .order_by(StressResult.loss_pct.desc().nullslast())
    )).scalars().all()
    tiers = {r.limit_type.partition(":")[2]: (_f(r.warning_level), _f(r.breach_level))
             for r in (await db.execute(
                 select(LimitCheck).where(LimitCheck.run_id == run_id,
                                          LimitCheck.limit_type.like("stress_loss:%"))
             )).scalars().all()}
    return {"run_id": run_id, "scenarios": [
        {"key": r.scenario, "label": dn.label("scenario", r.scenario),
         "description": r.description, "shocks": r.shocks,
         "loss_pct": _f(r.loss_pct), "loss_usd": _f(r.loss_usd),
         "held_flat": r.factors_held_flat or [], "status": r.status, "reason": r.reason,
         "warning": tiers.get(r.scenario, (None, None))[0],
         "breach": tiers.get(r.scenario, (None, None))[1]}
        for r in rows
    ]}


@router.get("/exposure-runs/{run_id}/reconcile", dependencies=[Depends(optional_user)])
async def run_reconcile(run_id: str, db: AsyncSession = Depends(get_db)):
    """The day's move, split two ways — the same call the agent makes.

    reconcile_move is one service and this is not a second implementation of it,
    because the waterfall on the page and the sentence in an answer are about to
    be read side by side and must agree to the last basis point.

    It records a calc row the first time, and is asked for the existing one on
    every later read (V13-S5, find_recorded). A page that minted a ledger row per
    refresh would turn "this desk performed 25,119 calculations" into "a browser
    was open".
    """
    existing = await calc_service.find_recorded(
        db, "portfolio.reconcile", {"run_id": run_id})
    result = await reconcile_service.reconcile_move(db, run_id)
    if existing is not None and "error" not in result:
        result["calc_id"] = existing.id
    else:
        await db.commit()
    return result


@router.get("/exposure-runs/{run_id}/factor-correlation", dependencies=[Depends(optional_user)])
async def run_factor_correlation(run_id: str, db: AsyncSession = Depends(get_db)):
    """How much the factors move together, over the window this run was fitted on.

    The regression already records that it is collinear and refuses to let a
    single beta be cited alone (V11-F). This is the reason, in a form a reader
    can check: market and growth at 0.95 is why "the market beta is 1.18" is not
    a statement the data supports on its own.
    """
    run = await exposure_run_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(404, {"error": "unknown_run", "run_id": run_id})
    metrics = run.metrics
    if metrics is None or not metrics.observations:
        return {"run_id": run_id, "matrix": None,
                "detail": "this run did not record the window it was fitted over"}

    end = metrics.attribution_date or run.as_of_date
    days = metrics.regression_window_days or 1200
    start = end - timedelta(days=int(days))
    tickers = [fa.factor_ticker for fa in run.factor_attributions if fa.factor_ticker]
    names = {fa.factor_ticker: dn.label("factor", fa.factor_name)
             for fa in run.factor_attributions if fa.factor_ticker}
    if len(tickers) < 2:
        return {"run_id": run_id, "matrix": None,
                "detail": "fewer than two factors were fitted"}

    prices = await market_data_service.get_factor_prices_df(db, tickers, start, end)
    matrix = factor_model.factor_correlation(
        market_data_service.build_factor_returns_df(prices)[tickers])
    return {
        "run_id": run_id,
        "window": {"from": start.isoformat(), "to": end.isoformat(),
                   "observations": int(metrics.observations)},
        "max_vif": _f(metrics.max_vif), "collinear": bool(metrics.collinear),
        "tickers": tickers, "labels": [names[t] for t in tickers],
        "matrix": matrix,
    }


@router.get("/exposure-runs/{run_id}", response_model=ExposureRunOut,
            dependencies=[Depends(optional_user)])
async def get_exposure_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await exposure_run_service.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
