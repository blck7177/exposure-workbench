"""Request-scoped current user (V2-A, consumed by V2-C tenant isolation).

A contextvar so the DB layer and services can learn the tenant without threading
user_id through every signature. Deliberately SEPARATE from
tools/registry._session_ctx (that is the tool/agent session; this is the
authenticated user) — the two must never be merged.
"""

from __future__ import annotations

import contextvars

current_user_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user_id", default=None
)


def current_user_id() -> str | None:
    return current_user_ctx.get()
