"""Agent conversation routes — the single meta-agent the user talks to.

POST messages runs the meta-agent loop and returns its reply synchronously.
Delegations inside the loop are non-blocking, so the turn stays responsive.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import require_user
from exposure_workbench.agents.meta_agent import handle_message
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.db.models import AgentMessage, AgentSession, AgentStep
from exposure_workbench.db.session import get_db, get_session_factory
from exposure_workbench.services import agent_session_service

router = APIRouter()


class SessionOut(BaseModel):
    id: str
    kind: str
    llm_model: str | None
    tools_used: int
    tool_budget: int | None

    model_config = {"from_attributes": True}


@router.post("/agent/sessions", response_model=SessionOut, status_code=201)
async def create_agent_session(
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    s = await agent_session_service.create_session(db, kind="meta", owner_id=user.user_id)
    await db.commit()
    return s


class MessageIn(BaseModel):
    text: str


class MessageOut(BaseModel):
    session_id: str
    message_id: str
    text: str
    citations: list


@router.post("/agent/sessions/{session_id}/messages", response_model=MessageOut)
async def post_message(
    session_id: str, body: MessageIn,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    s = await agent_session_service.get_session(db, session_id)
    if s is None:
        raise HTTPException(404, "unknown session")
    factory = get_session_factory()
    result = await handle_message(factory, session_id, body.text)
    return result


class StepOut(BaseModel):
    seq: int
    step_type: str
    tool_name: str | None
    status: str
    result_summary: str | None
    evidence_refs: list
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetailOut(BaseModel):
    id: str
    kind: str
    tools_used: int
    messages: list
    steps: list[StepOut]


@router.get("/agent/sessions/{session_id}", response_model=SessionDetailOut)
async def get_agent_session(session_id: str, db: AsyncSession = Depends(get_db)):
    s = await agent_session_service.get_session(db, session_id)
    if s is None:
        raise HTTPException(404, "unknown session")
    msgs = (await db.execute(
        select(AgentMessage).where(AgentMessage.session_id == session_id).order_by(AgentMessage.created_at)
    )).scalars().all()
    steps = (await db.execute(
        select(AgentStep).where(AgentStep.session_id == session_id).order_by(AgentStep.seq)
    )).scalars().all()
    return SessionDetailOut(
        id=s.id, kind=s.kind, tools_used=s.tools_used,
        messages=[{"id": m.id, "role": m.role, "content": m.content, "citations": m.citations} for m in msgs],
        steps=steps,
    )
