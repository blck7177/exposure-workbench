"""Identity route (V2-A) — who am I. Requires a valid Clerk token."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.auth_deps import require_user
from exposure_workbench.auth.clerk import UserClaims

router = APIRouter()


@router.get("/me")
async def me(user: UserClaims = Depends(require_user)):
    return {"user_id": user.user_id, "email": user.email}
