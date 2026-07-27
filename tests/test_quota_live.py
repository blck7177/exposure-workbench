"""E2 + E3 — the conditional upsert and the turn lease, against a real DB (live).

Run with:  pytest -m live -k quota_live

Both mechanisms are single SQL statements whose whole value is what they do
under concurrency, so neither can be exercised offline. Covered here:

  charge()    under the limit / exactly exhausted / two callers racing for the
              last unit / the global backstop counted separately from the user /
              both charges rolling back together
  claim_turn  free -> claimed / claimed -> refused / expired -> reclaimed /
              release frees it immediately

Connects as app_rls, since usage_daily deliberately has no RLS and that is the
role the claim is proven not to need a tenant for. Teardown runs as the owner
because app_rls holds no DELETE grant.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.services import agent_session_service, usage_service
from exposure_workbench.utils.dates import today_utc

pytestmark = pytest.mark.live

OWNER_URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)
APP_URL = os.getenv(
    "DATABASE_URL_LOCAL_APP",
    "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench",
)

TAG = uuid.uuid4().hex[:8]
USER = f"user_quota_{TAG}"
KIND = "chat_turn"


@pytest.fixture
async def owner():
    engine = create_async_engine(OWNER_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)

    # Every charge also hits the shared '_global' row, and that row belongs to
    # everyone. Left alone, a few runs of this suite would eat into the backstop
    # and start refusing real users for reasons they could never diagnose — so
    # snapshot it and put it back, rather than deleting it.
    async with mk() as db:
        before = {
            k: v for k, v in (await db.execute(
                text("SELECT kind, used FROM usage_daily WHERE user_id = :g AND day = CURRENT_DATE"),
                {"g": usage_service.GLOBAL_SCOPE},
            )).all()
        }
    try:
        yield mk
    finally:
        async with mk() as db, db.begin():
            await db.execute(text("DELETE FROM usage_daily WHERE user_id LIKE :p"),
                             {"p": f"user_quota_{TAG}%"})
            await db.execute(text("DELETE FROM agent_sessions WHERE id LIKE :p"),
                             {"p": f"sess_turn_{TAG}%"})
            await db.execute(text("DELETE FROM users WHERE id LIKE :p"),
                             {"p": f"user_quota_{TAG}%"})
            for kind, used in before.items():
                await db.execute(
                    text("UPDATE usage_daily SET used = :n WHERE user_id = :g "
                         "AND day = CURRENT_DATE AND kind = :k"),
                    {"n": used, "g": usage_service.GLOBAL_SCOPE, "k": kind},
                )
            # kinds this run created from nothing go away entirely
            await db.execute(
                text("DELETE FROM usage_daily WHERE user_id = :g AND day = CURRENT_DATE "
                     "AND NOT (kind = ANY(:keep))"),
                {"g": usage_service.GLOBAL_SCOPE, "keep": list(before) or [""]},
            )
        await engine.dispose()


@pytest.fixture
async def app_rls():
    engine = create_async_engine(APP_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        yield mk
    finally:
        await engine.dispose()


# ── charge() ──────────────────────────────────────────────────────────────────

async def test_charge_counts_up_then_refuses_at_the_limit(owner, app_rls):
    limit, _ = usage_service.limits_for(KIND)

    for i in range(limit):
        async with app_rls() as db, db.begin():
            await usage_service.charge(db, USER, KIND)
        async with app_rls() as db:
            assert await usage_service.get_used(db, USER, KIND) == i + 1

    with pytest.raises(usage_service.QuotaExceeded) as e:
        async with app_rls() as db, db.begin():
            await usage_service.charge(db, USER, KIND)
    assert e.value.scope == "user"
    assert (e.value.used, e.value.limit) == (limit, limit)

    async with app_rls() as db:
        assert await usage_service.get_used(db, USER, KIND) == limit, (
            "a refused charge must not move the counter"
        )


async def test_the_two_charges_commit_or_roll_back_together(owner, app_rls):
    """The user pool and the global backstop are charged in one transaction, which
    is the entire reason there is no refund path anywhere in the system."""
    user = f"{USER}_atomic"
    before_global = None
    async with app_rls() as db:
        before_global = await usage_service.get_used(db, usage_service.GLOBAL_SCOPE, KIND)

    # a caller that fails after charging gets both counters back
    with pytest.raises(RuntimeError):
        async with app_rls() as db, db.begin():
            await usage_service.charge(db, user, KIND)
            raise RuntimeError("caller blew up after charging")

    async with app_rls() as db:
        assert await usage_service.get_used(db, user, KIND) == 0
        assert await usage_service.get_used(db, usage_service.GLOBAL_SCOPE, KIND) == before_global


async def test_global_backstop_counts_across_users(owner, app_rls):
    a, b = f"{USER}_a", f"{USER}_b"
    async with app_rls() as db:
        before = await usage_service.get_used(db, usage_service.GLOBAL_SCOPE, KIND)
    for u in (a, b):
        async with app_rls() as db, db.begin():
            await usage_service.charge(db, u, KIND)
    async with app_rls() as db:
        assert await usage_service.get_used(db, a, KIND) == 1
        assert await usage_service.get_used(db, b, KIND) == 1
        assert await usage_service.get_used(db, usage_service.GLOBAL_SCOPE, KIND) == before + 2, (
            "the shared pool must see both users — that is why usage_daily has no RLS"
        )


async def test_two_callers_cannot_both_take_the_last_unit(owner, app_rls):
    """The race the conditional upsert exists for. Both start at limit-1 used."""
    user = f"{USER}_race"
    limit, _ = usage_service.limits_for(KIND)
    async with app_rls() as db, db.begin():
        await db.execute(
            text("INSERT INTO usage_daily (user_id, day, kind, used) VALUES (:u, :d, :k, :n)"),
            {"u": user, "d": today_utc(), "k": KIND, "n": limit - 1},
        )

    async def attempt():
        try:
            async with app_rls() as db, db.begin():
                await usage_service.charge(db, user, KIND)
            return "ok"
        except usage_service.QuotaExceeded:
            return "refused"

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == ["ok", "refused"], f"exactly one should win, got {results}"
    async with app_rls() as db:
        assert await usage_service.get_used(db, user, KIND) == limit


# ── turn lease ────────────────────────────────────────────────────────────────

async def _make_session(owner_mk, suffix: str, *, started_secs_ago: int | None = None) -> str:
    """A session whose turn started `started_secs_ago` in the past, or is free.

    Two separate statements rather than a CASE over the parameter: asyncpg infers
    parameter types from context and cannot type a bare NULL inside one.
    """
    sid = f"sess_turn_{TAG}_{suffix}"
    if started_secs_ago is None:
        sql, params = (
            "INSERT INTO agent_sessions (id, kind, owner_id, turn_started_at) "
            "VALUES (:id, 'meta', :owner, NULL)",
            {"id": sid, "owner": USER},
        )
    else:
        sql, params = (
            "INSERT INTO agent_sessions (id, kind, owner_id, turn_started_at) "
            "VALUES (:id, 'meta', :owner, now() - make_interval(secs => :off))",
            {"id": sid, "owner": USER, "off": started_secs_ago},
        )
    async with owner_mk() as db, db.begin():
        await db.execute(text(sql), params)
    return sid


async def test_turn_lease_claim_refuse_and_expiry(owner, app_rls):
    current_user_ctx.set(USER)   # agent_sessions IS an RLS table
    lease = get_settings().turn_lease_seconds

    free = await _make_session(owner, "free")
    async with app_rls() as db, db.begin():
        assert await agent_session_service.claim_turn(db, free) is True

    async with app_rls() as db, db.begin():
        assert await agent_session_service.claim_turn(db, free) is False, (
            "a second turn on the same session must be refused, not queued"
        )

    stale = await _make_session(owner, "stale", started_secs_ago=lease + 60)
    async with app_rls() as db, db.begin():
        assert await agent_session_service.claim_turn(db, stale) is True, (
            "an expired lease self-heals — nothing renews it, so this is the only recovery"
        )

    fresh = await _make_session(owner, "fresh", started_secs_ago=lease - 60)
    async with app_rls() as db, db.begin():
        assert await agent_session_service.claim_turn(db, fresh) is False, (
            "a turn still inside its lease must never be stolen from a live request"
        )


async def test_release_frees_the_slot_immediately(owner, app_rls, monkeypatch):
    current_user_ctx.set(USER)
    monkeypatch.setattr(agent_session_service, "get_session_factory", lambda: app_rls)

    sid = await _make_session(owner, "release")
    async with app_rls() as db, db.begin():
        assert await agent_session_service.claim_turn(db, sid) is True

    await agent_session_service.release_turn(sid)

    async with app_rls() as db, db.begin():
        assert await agent_session_service.claim_turn(db, sid) is True, (
            "release must not depend on the lease expiring"
        )


async def test_release_never_raises_even_for_an_unknown_session(owner, app_rls, monkeypatch):
    """It is called from a finally on error paths; raising there would replace the
    real failure with a bookkeeping one."""
    current_user_ctx.set(USER)
    monkeypatch.setattr(agent_session_service, "get_session_factory", lambda: app_rls)
    await agent_session_service.release_turn("sess_does_not_exist")


async def test_another_tenant_sees_no_session_to_claim(owner, app_rls):
    """Cross-user is a 0-row UPDATE, not a 403 — the route's 404 precheck is what
    keeps 'not yours' distinguishable from 'busy'."""
    sid = await _make_session(owner, "tenant")
    current_user_ctx.set(f"{USER}_intruder")
    async with app_rls() as db, db.begin():
        assert await agent_session_service.claim_turn(db, sid) is False
    current_user_ctx.set(USER)
    async with app_rls() as db, db.begin():
        assert await agent_session_service.claim_turn(db, sid) is True, (
            "and the real owner is unaffected by the intruder's attempt"
        )
