"""Identity + quota routes (V2-A, V2-E4) — who am I, and what have I spent today."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import require_user
from exposure_workbench.auth.clerk import UserClaims
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
        pools=[PoolOut(kind=p.kind, used=p.used, limit=p.limit, remaining=p.remaining)
               for p in pools],
    )
