"""Auth dependencies (V2-A) — the single place a request becomes a user.

- require_user: 401 unless a valid Clerk token is present. Every write route.
- optional_user: UserClaims or None. For reads whose visibility varies by
  identity (wired in V2-C once RLS exists).

On success both upsert the users row (bootstrap) and set the current-user
contextvar, so V2-C's tenant DB session and any service can see the tenant
without threading it through signatures.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.auth.clerk import AuthError, UserClaims, verify_token
from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.db.session import get_db
from exposure_workbench.services import user_service


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


async def optional_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> UserClaims | None:
    token = _bearer(authorization)
    if not token:
        return None
    try:
        claims = verify_token(token)
    except AuthError:
        return None
    current_user_ctx.set(claims.user_id)
    await user_service.touch(db, claims.user_id, claims.email)
    return claims


async def require_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> UserClaims:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(401, {"error": "unauthenticated"})
    try:
        claims = verify_token(token)
    except AuthError as e:
        raise HTTPException(401, {"error": "unauthenticated", "reason": e.reason})
    current_user_ctx.set(claims.user_id)
    await user_service.touch(db, claims.user_id, claims.email)
    return claims
