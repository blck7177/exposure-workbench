"""Auth dependencies (V2-A) — the single place a request becomes a user.

- require_user: 401 unless a valid Clerk token is present. Every write route.
- optional_user: UserClaims or None. For reads whose visibility varies by
  identity (wired in V2-C once RLS exists).

On success both set the current-user contextvar — so V2-C's tenant DB session
and any service can see the tenant without threading it through signatures —
and then upsert the users row. That order is load-bearing: user_service.touch
opens its own session, and the after_begin listener reads the contextvar when
that session's transaction starts.

Neither dependency takes a DB session (V2-E0). They used to, and the users-row
upsert then rode the request-scoped transaction, holding a row lock on users for
the entire turn; the same user's second concurrent request blocked here instead
of reaching the route.
"""

from __future__ import annotations

from fastapi import Header, HTTPException
from starlette.concurrency import run_in_threadpool

from exposure_workbench.auth.clerk import AuthError, UserClaims, verify_token
from exposure_workbench.auth.context import current_user_ctx
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
) -> UserClaims | None:
    token = _bearer(authorization)
    if not token:
        return None
    try:
        # Blocking (it can fetch the JWK Set) — never on the event loop.
        claims = await run_in_threadpool(verify_token, token)
    except AuthError:
        return None
    current_user_ctx.set(claims.user_id)
    await user_service.touch(claims.user_id, claims.email)
    return claims


async def require_user(
    authorization: str | None = Header(default=None),
) -> UserClaims:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(401, {"error": "unauthenticated"})
    try:
        # Blocking (it can fetch the JWK Set) — never on the event loop.
        claims = await run_in_threadpool(verify_token, token)
    except AuthError as e:
        raise HTTPException(401, {"error": "unauthenticated", "reason": e.reason})
    current_user_ctx.set(claims.user_id)
    await user_service.touch(claims.user_id, claims.email)
    return claims
