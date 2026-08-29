"""Research routes — enqueue readiness / research runs, read run status + brief.

Pure enqueue + read. Zero judgment, zero LLM.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import optional_user, require_user
from apps.api.schemas import WorkflowEventOut
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.models import Company, IssuerBrief, ResearchRun, WorkflowEvent
from exposure_workbench.db.session import get_db
from exposure_workbench.services import company_service, research_run_service, task_service, usage_service

router = APIRouter()


# ── readiness ────────────────────────────────────────────────────────────────────

class ReadinessRequest(BaseModel):
    ticker: str
    skip_market_refresh: bool = False


class TaskAck(BaseModel):
    task_id: str
    status: str


@router.post("/companies/{ticker}/ensure-ready", response_model=TaskAck, status_code=201)
async def ensure_ready(
    ticker: str, body: ReadinessRequest | None = None,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    tk = ticker.upper()
    try:
        await company_service.require_investigable(db, tk)
    except company_service.CompanyNotFound:
        raise HTTPException(404, {"error": "unknown_ticker", "ticker": tk})
    except company_service.NotInvestigable:
        raise HTTPException(422, {"error": "not_investigable", "ticker": tk})
    try:
        task = await task_service.create_task(
            db, task_type="company_readiness",
            payload={"ticker": tk, "skip_market_refresh": bool(body and body.skip_market_refresh)},
            owner_user_id=user.user_id,
        )
    except usage_service.QuotaExceeded as e:
        raise HTTPException(429, e.as_dict()) from e
    await db.commit()
    return TaskAck(task_id=task.id, status=task.status)


# ── research runs ──────────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    ticker: str
    portfolio_id: str | None = None
    skip_external_research: bool = False
    skip_market_refresh: bool = False


class ResearchRunOut(BaseModel):
    id: str
    company_id: str
    status: str
    triggered_by: str | None
    agent_session_id: str | None
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
    # V7-U1. The outer timeline of the run, so the page can say which of the
    # minutes-long readiness steps is under way instead of spinning. Empty from
    # POST by construction — a run that was only just enqueued has no events —
    # and filled by the GET the page polls.
    workflow_events: list[WorkflowEventOut] = []

    model_config = {"from_attributes": True}


@router.post("/research-runs", response_model=ResearchRunOut, status_code=201)
async def create_research_run(
    body: ResearchRequest,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    tk = body.ticker.upper()
    try:
        company = await company_service.require_investigable(db, tk)
    except company_service.CompanyNotFound:
        raise HTTPException(404, {"error": "unknown_ticker", "ticker": tk})
    except company_service.NotInvestigable:
        raise HTTPException(422, {"error": "not_investigable", "ticker": tk})

    # Check for an active run BEFORE enqueuing (V2-E3). create_run raises
    # ActiveRunExists after the fact, and charging quota for a request that is
    # about to 409 would let a user burn their research allowance on a conflict.
    # The REST path never leaked an orphan task — get_db rolls back on the raise —
    # but the agent path did, and both now share this ordering.
    active = await research_run_service.get_active_run(db, company.id)
    if active is not None:
        raise HTTPException(409, detail={"error": "active_run_exists", "run_id": active.id})

    try:
        task = await task_service.create_task(
            db, task_type="issuer_research", payload={"ticker": tk}, owner_user_id=user.user_id,
        )
    except usage_service.QuotaExceeded as e:
        raise HTTPException(429, e.as_dict()) from e
    try:
        run = await research_run_service.create_run(
            db, company.id, body.portfolio_id, triggered_by="manual", task_id=task.id,
            owner_id=user.user_id,
        )
    except research_run_service.ActiveRunExists as e:
        # lost a race with a concurrent request between the precheck and here
        raise HTTPException(409, detail={"error": "active_run_exists", "run_id": e.run_id})

    task.payload = {**task.payload, "run_id": run.id,
                    "skip_external_research": body.skip_external_research,
                    "skip_market_refresh": body.skip_market_refresh}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.commit()
    return await research_run_service.get_run(db, run.id)


class ResearchRunSummaryOut(BaseModel):
    id: str
    company_id: str
    ticker: str | None = None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None = None


@router.get("/research-runs", response_model=list[ResearchRunSummaryOut])
async def list_research_runs(
    limit: int = 20,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own research runs, newest first (V13-S5).

    There was no way to list these. A run was reachable only by holding its id,
    so a person who started one and navigated away had lost it — and the agent
    was told to hand the id over in the reply, which is how `rrun_5b247ec1db21`
    came to be a thing a user was expected to keep.

    RLS scopes research_runs by owner, so this is the caller's work and no
    filter here is doing the securing. The ticker is joined in because a list of
    ids is not a list.
    """
    rows = (await db.execute(
        select(ResearchRun, Company.ticker)
        .outerjoin(Company, Company.id == ResearchRun.company_id)
        .order_by(ResearchRun.created_at.desc()).limit(min(limit, 100))
    )).all()
    return [
        ResearchRunSummaryOut(
            id=r.id, company_id=r.company_id, ticker=ticker, status=r.status,
            started_at=r.started_at, completed_at=r.completed_at, error_code=r.error_code)
        for r, ticker in rows
    ]


@router.get("/research-runs/{run_id}", response_model=ResearchRunOut,
            dependencies=[Depends(optional_user)])
async def get_research_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await research_run_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    # An explicit query, not a relationship load like the exposure route's: the
    # database has no FK on workflow_events.run_id (it is polymorphic over
    # exposure runs, research runs and tasks — see the policy in init.sql), so
    # ResearchRun has no navigation to load, matching the issuer-intelligence
    # models' deliberate no-relationship rule.
    #
    # id breaks the tie on created_at because a step writes 'running' and then
    # 'completed', the client keeps only the LAST row per step name, and both
    # rows can land on the same timestamp — reversed, a finished step would sit
    # on the page spinning forever.
    events = (await db.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.run_id == run_id)
        .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
    )).scalars().all()
    out = ResearchRunOut.model_validate(run)
    out.workflow_events = [WorkflowEventOut.model_validate(e) for e in events]
    return out


class BriefOut(BaseModel):
    id: str
    research_run_id: str
    company_id: str
    financial_summary: str | None
    key_changes: str | None
    management_explanation: str | None
    market_context: str | None
    portfolio_implications: str | None
    open_questions: str | None
    citations: list
    confidence_flags: dict

    model_config = {"from_attributes": True}


@router.get("/research-runs/{run_id}/brief", response_model=BriefOut,
            # optional_user sets the RLS tenant. Without it current_setting is NULL
            # and the policy matches only is_public rows — so the owner of a private
            # result cannot read it back, which is worse than a leak: they paid a
            # quota unit for something they can never see.
            dependencies=[Depends(optional_user)])
async def get_brief(run_id: str, db: AsyncSession = Depends(get_db)):
    brief = (await db.execute(select(IssuerBrief).where(IssuerBrief.research_run_id == run_id))).scalar_one_or_none()
    if brief is None:
        raise HTTPException(404, "no brief for this run")
    return brief
