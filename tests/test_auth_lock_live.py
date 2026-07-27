"""E0-3 — the users-row upsert must not ride the request transaction (live: needs DB).

Run with:  pytest -m live -k auth_lock

require_user/optional_user call user_service.touch on every authenticated
request. While it wrote through the request-scoped session, the UPDATE held an
exclusive lock on that user's row until get_db committed — i.e. for the whole
turn. The same user's second concurrent request then blocked inside the auth
dependency and never reached the route, so E2's in-flight-turn 409 was
unreachable and the symptom was "hangs, then returns 200".

Two tests, and the control matters: the first proves touch now commits on its
own connection, the second proves a concurrent request is not blocked — and the
control alongside it proves that measurement is real by reproducing the block
with the old write shape.

Connects as app_rls (not the owner) so the RLS path is exercised too: users is
an RLS table, and a row is only insertable under its own tenant.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.db.models import User
from exposure_workbench.services import user_service

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL_APP",
    "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench",
)

# Stable id, upserted — the suite leaves exactly one probe row however often it runs
# (app_rls holds no DELETE grant by design, so tests cannot clean up after themselves).
USER = "user_e0_lock_probe"


@pytest.fixture
async def factory(monkeypatch):
    """Bind user_service.touch to a test engine. touch() resolves the factory at
    call time from its own module namespace, so patching there is enough."""
    engine = create_async_engine(URL, pool_size=5)
    mk = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(user_service, "get_session_factory", lambda: mk)
    current_user_ctx.set(USER)  # before any session opens: after_begin reads it
    try:
        yield mk
    finally:
        await engine.dispose()


async def test_touch_commits_independently_of_the_request_session(factory):
    """The property, tested directly rather than by timing: while a request-scoped
    transaction is open and uncommitted, touch's write is already visible from a
    THIRD connection. That is only possible if it committed on its own."""
    async with factory() as request_session:
        await request_session.execute(text("SELECT 1"))  # opens the request txn

        await user_service.touch(USER, "probe@example.com")

        async with factory() as observer:
            row = (
                await observer.execute(select(User).where(User.id == USER))
            ).scalar_one_or_none()
            assert row is not None, "touch did not commit on its own connection"

        await request_session.rollback()


async def test_concurrent_request_is_not_blocked(factory):
    """A second authenticated request from the same user must get through the auth
    dependency while the first request's transaction is still open."""
    await user_service.touch(USER, "probe@example.com")  # ensure the row exists

    async with factory() as request_session:
        await request_session.execute(text("SELECT 1"))
        await asyncio.wait_for(user_service.touch(USER, None), timeout=5.0)
        await request_session.rollback()


async def test_control_old_shape_still_blocks(factory):
    """Control for the test above. Writing users on the long-lived request session
    — what touch used to do — still deadlocks the next request, which proves the
    5s budget above is measuring a real lock and not just a fast no-op."""
    await user_service.touch(USER, "probe@example.com")

    async with factory() as request_session:
        await request_session.execute(
            text("UPDATE users SET last_seen_at = now() WHERE id = :u"), {"u": USER}
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(user_service.touch(USER, None), timeout=3.0)
        await request_session.rollback()
