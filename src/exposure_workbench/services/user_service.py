"""User service (V2-A) — local bootstrap + last-seen for Clerk users.

Identity lives in Clerk; we keep a local `users` row so ownership FKs resolve and
we can show an email. First authenticated request upserts the row (idempotent).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import User


async def touch(db: AsyncSession, user_id: str, email: str | None) -> None:
    """Upsert the user row and stamp last_seen. Called on every authed request."""
    row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(User(id=user_id, email=email, last_seen_at=now))
    else:
        row.last_seen_at = now
        if email and not row.email:
            row.email = email
    await db.flush()


async def get(db: AsyncSession, user_id: str) -> User | None:
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
