"""User service (V2-A) — local bootstrap + last-seen for Clerk users.

Identity lives in Clerk; we keep a local `users` row so ownership FKs resolve and
we can show an email. First authenticated request upserts the row (idempotent).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    # A single upsert, not read-then-insert. Two concurrent requests from a user
    # who has never signed in before would both find no row and both INSERT, and
    # one would take a primary-key violation — a 500 on somebody's very first
    # request, which is the least forgiving moment to get one.
    #
    # COALESCE keeps an email already on file rather than letting a token that
    # happens to omit the claim blank it out.
    now = datetime.now(timezone.utc)
    stmt = pg_insert(User).values(id=user_id, email=email, last_seen_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "last_seen_at": stmt.excluded.last_seen_at,
            "email": func.coalesce(User.email, stmt.excluded.email),
        },
    )
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(stmt)


async def get(db: AsyncSession, user_id: str) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
