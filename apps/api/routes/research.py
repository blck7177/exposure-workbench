"""Research routes — enqueue readiness / research runs, read run status + brief.

Pure enqueue + read. Zero judgment, zero LLM.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company, IssuerBrief, ResearchRun
from exposure_workbench.db.session import get_db
from exposure_workbench.services import company_service, research_run_service, task_service

router = APIRouter()


# ── readiness ────────────────────────────────────────────────────────────────────

class ReadinessRequest(BaseModel):
    ticker: str
    skip_market_refresh: bool = False


class TaskAck(BaseModel):
    task_id: str
    status: str


@router.post("/companies/{ticker}/ensure-ready", response_model=TaskAck, status_code=201)
async def ensure_ready(ticker: str, body: ReadinessRequest | None = None, db: AsyncSession = Depends(get_db)):
    tk = ticker.upper()
    try:
        await company_service.require_investigable(db, tk)
    except company_service.CompanyNotFound:
        raise HTTPException(404, f"unknown ticker {tk}")
    except company_service.NotInvestigable:
        raise HTTPException(422, f"{tk} is not investigable")
    task = await task_service.create_task(
        db, task_type="company_readiness",
        payload={"ticker": tk, "skip_market_refresh": bool(body and body.skip_market_refresh)},
    )
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
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


@router.post("/research-runs", response_model=ResearchRunOut, status_code=201)
async def create_research_run(body: ResearchRequest, db: AsyncSession = Depends(get_db)):
    tk = body.ticker.upper()
    try:
        company = await company_service.require_investigable(db, tk)
    except company_service.CompanyNotFound:
        raise HTTPException(404, f"unknown ticker {tk}")
    except company_service.NotInvestigable:
        raise HTTPException(422, f"{tk} is not investigable")

    task = await task_service.create_task(db, task_type="issuer_research", payload={"ticker": tk})
    try:
        run = await research_run_service.create_run(
            db, company.id, body.portfolio_id, triggered_by="manual", task_id=task.id,
        )
    except research_run_service.ActiveRunExists as e:
        # a run is already active for this issuer — point the caller at it
        raise HTTPException(409, detail={"message": "active run exists", "run_id": e.run_id})

    task.payload = {**task.payload, "run_id": run.id,
                    "skip_external_research": body.skip_external_research,
                    "skip_market_refresh": body.skip_market_refresh}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.commit()
    return await research_run_service.get_run(db, run.id)


@router.get("/research-runs/{run_id}", response_model=ResearchRunOut)
async def get_research_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await research_run_service.get_run(db, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


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


@router.get("/research-runs/{run_id}/brief", response_model=BriefOut)
async def get_brief(run_id: str, db: AsyncSession = Depends(get_db)):
    brief = (await db.execute(select(IssuerBrief).where(IssuerBrief.research_run_id == run_id))).scalar_one_or_none()
    if brief is None:
        raise HTTPException(404, "no brief for this run")
    return brief
