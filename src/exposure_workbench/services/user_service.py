"""User service (V2-A) — local bootstrap + last-seen for Clerk users.

Identity lives in Clerk; we keep a local `users` row so ownership FKs resolve and
we can show an email. First authenticated request upserts the row (idempotent).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import User
from exposure_workbench.db.session import get_session_factory


async def touch(user_id: str, email: str | None) -> None:
    """Upsert the user row and stamp last_seen, in its OWN short transaction.

    Deliberately NOT on the request-scoped session (V2-E0): get_db holds its
    transaction open until the route returns, so writing here would keep an
    exclusive lock on the users row for the whole turn. The same user's second
    concurrent request would then block inside the auth dependency and never
    reach the route — E2's in-flight-turn 409 would be unreachable, and the
    symptom would be "hangs, then succeeds" rather than a clean conflict.
    Throttling the write (only every N minutes) does not fix it: the one request
    that does write still holds the lock for its whole turn.

    The caller must set current_user_ctx BEFORE calling this — db/session.py's
    after_begin listener reads the contextvar when this session opens its
    transaction, and users is an RLS table (a row is only insertable under its
    own tenant).
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        row = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row is None:
            session.add(User(id=user_id, email=email, last_seen_at=now))
        else:
            row.last_seen_at = now
            if email and not row.email:
                row.email = email


async def get(db: AsyncSession, user_id: str) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
