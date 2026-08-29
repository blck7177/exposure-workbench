"""Identity + quota routes (V2-A, V2-E4) — who am I, and what have I spent today."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import require_user
from exposure_workbench.auth.clerk import UserClaims
from sqlalchemy import func, select

from exposure_workbench.db.models import AgentMessage, AgentSession, AgentStep
from exposure_workbench.db.session import get_db
from exposure_workbench.services import usage_service
from exposure_workbench.utils.dates import today_utc

router = APIRouter()


@router.get("/me")
async def me(user: UserClaims = Depends(require_user)):
    return {"user_id": user.user_id, "email": user.email}


class PoolOut(BaseModel):
    kind: str
    used: int
    limit: int
    remaining: int
    unlimited: bool = False


class UsageOut(BaseModel):
    day: str
    resets_at: str
    pools: list[PoolOut]


@router.get("/me/usage", response_model=UsageOut)
async def my_usage(
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Today's quota for the caller, straight off usage_daily.

    Deliberately not a view. V2-E0 had just finished repairing two views that
    read past RLS because a view defaults to running with its definer's
    privileges; adding another over a tenant-scoped read would reopen exactly
    that hole. The global backstop row is never exposed here — it is an operator
    number, not a user's business.
    """
    pools = await usage_service.summary_for(db, user.user_id)
    return UsageOut(
        day=today_utc().isoformat(),
        resets_at=usage_service.next_reset_at(),
        pools=[PoolOut(kind=p.kind, used=p.used, limit=p.limit, remaining=p.remaining,
                       unlimited=p.unlimited)
               for p in pools],
    )


class AuditSummaryOut(BaseModel):
    """What this desk has actually done, counted (V13-S4).

    The product's argument is that its numbers are checked and its refusals are
    real. Both are recorded — agent_steps has been append-only since V1 — and
    neither was ever shown, so the claim rested on being believed.

    Owner-scoped by RLS: agent_sessions carries owner_id and agent_steps hangs
    off it, so these counts are the caller's own work and nobody else's. That is
    also why this is not a global operator dashboard — it is the audit layer of
    one desk, for the person who owns it.
    """

    answers_gated: int          # replies the citation gate accepted
    answers_refused: int        # turns that ended without an answer it would take
    lookups_made: int
    lookups_refused: int        # budget spent, or a malformed call
    model_calls: int
    figures_checked: int        # over every accepted answer that recorded it


@router.get("/me/audit-summary", response_model=AuditSummaryOut)
async def my_audit_summary(
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    # semantic, not security: agent_sessions carries a FOR ALL tenant policy, so
    # RLS has already made another tenant's rows invisible to this connection and
    # the filter cannot widen anything. It is here so the query says out loud
    # what it counts — this desk's own work — rather than depending on the reader
    # knowing which tables are policed.
    mine = select(AgentSession.id).where(AgentSession.owner_id == user.user_id)

    async def _steps(**where) -> int:
        q = select(func.count()).select_from(AgentStep).where(AgentStep.session_id.in_(mine))
        for column, value in where.items():
            q = q.where(getattr(AgentStep, column) == value)
        return int((await db.execute(q)).scalar_one())

    messages = (await db.execute(
        select(AgentMessage.meta).where(AgentMessage.session_id.in_(mine),
                                        AgentMessage.role == "assistant")
    )).scalars().all()

    # Read off the message rather than recounted here: `verified` is what the
    # gate found at the moment it accepted the answer, and a second count taken
    # later would be a second opinion. A message with no `verified` predates
    # V13-S3 and contributes nothing rather than a guess.
    figures = sum(int((m or {}).get("verified", {}).get("figures", 0) or 0) for m in messages)
    refused = sum(1 for m in messages if (m or {}).get("gate") == "exhausted")

    return AuditSummaryOut(
        answers_gated=await _steps(step_type="respond", status="completed"),
        answers_refused=refused,
        lookups_made=await _steps(step_type="tool_call", status="completed"),
        lookups_refused=await _steps(step_type="tool_call", status="rejected"),
        model_calls=await _steps(step_type="llm_call"),
        figures_checked=figures,
    )
