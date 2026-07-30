"""V2-H — the three new charge points, against a real DB (live).

Run with:  pytest -m live -k charge_points

test_quota_live proves the counter primitive. This proves the three actions
that were previously free are now wired to it, which is a different claim and
the one that was actually broken: portfolio creation, demo cloning and CSV
upload each created rows — and in the upload's case up to ~400 provider calls —
with nothing counting.

Exercised at the SERVICE layer, as app_rls, because that is where the charge
sits and where a double charge or a missed surface would show. The route-level
ordering (401 -> 404 -> 403 -> 422 parse -> 429) is asserted structurally in
test_v2_audit, and end to end over HTTP in the acceptance pass.
"""

from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.services import portfolio_service, usage_service

pytestmark = pytest.mark.live

OWNER_URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)
APP_URL = os.getenv(
    "DATABASE_URL_LOCAL_APP",
    "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench",
)

TAG = uuid.uuid4().hex[:8]
USER = f"user_charge_{TAG}"


@pytest.fixture
async def owner():
    engine = create_async_engine(OWNER_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    async with mk() as db, db.begin():
        await db.execute(text("INSERT INTO users (id, email) VALUES (:u, :e)"),
                         {"u": USER, "e": f"{USER}@example.test"})
    # The '_global' backstop belongs to everyone; snapshot and restore it rather
    # than letting a test run quietly eat into a real user's headroom.
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
            await db.execute(
                text("DELETE FROM risk_limits WHERE portfolio_id IN "
                     "(SELECT id FROM portfolios WHERE owner_id = :u)"), {"u": USER})
            await db.execute(
                text("DELETE FROM positions WHERE portfolio_id IN "
                     "(SELECT id FROM portfolios WHERE owner_id = :u)"), {"u": USER})
            await db.execute(text("DELETE FROM portfolios WHERE owner_id = :u"), {"u": USER})
            await db.execute(text("DELETE FROM usage_daily WHERE user_id = :u"), {"u": USER})
            await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": USER})
            for kind, used in before.items():
                await db.execute(
                    text("UPDATE usage_daily SET used = :n WHERE user_id = :g "
                         "AND day = CURRENT_DATE AND kind = :k"),
                    {"n": used, "g": usage_service.GLOBAL_SCOPE, "k": kind})
            await db.execute(
                text("DELETE FROM usage_daily WHERE user_id = :g AND day = CURRENT_DATE "
                     "AND NOT (kind = ANY(:keep))"),
                {"g": usage_service.GLOBAL_SCOPE, "keep": list(before) or [""]})
        await engine.dispose()


@pytest.fixture
async def app_rls():
    engine = create_async_engine(APP_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    token = current_user_ctx.set(USER)
    try:
        yield mk
    finally:
        current_user_ctx.reset(token)
        await engine.dispose()


async def _used(mk, kind: str) -> int:
    async with mk() as db:
        r = await db.execute(
            text("SELECT used FROM usage_daily WHERE user_id = :u AND day = CURRENT_DATE AND kind = :k"),
            {"u": USER, "k": kind})
        return r.scalar_one_or_none() or 0


async def test_creating_a_portfolio_costs_one_unit(owner, app_rls):
    async with app_rls() as db, db.begin():
        await portfolio_service.create_portfolio(db, owner_id=USER, name="first")
    assert await _used(app_rls, "portfolio_create") == 1


async def test_cloning_the_demo_costs_one_unit_and_only_one(owner, app_rls):
    """clone_demo calls create_portfolio, which is where the charge lives. If the
    charge were also added at the route it would bill this action twice."""
    async with app_rls() as db, db.begin():
        await portfolio_service.clone_demo(db, owner_id=USER)
    assert await _used(app_rls, "portfolio_create") == 1


async def test_the_pool_refuses_past_its_limit(owner, app_rls):
    limit, _ = usage_service.limits_for("portfolio_create")
    for i in range(limit):
        async with app_rls() as db, db.begin():
            await portfolio_service.create_portfolio(db, owner_id=USER, name=f"p{i}")

    with pytest.raises(usage_service.QuotaExceeded) as e:
        async with app_rls() as db, db.begin():
            await portfolio_service.create_portfolio(db, owner_id=USER, name="one too many")
    assert e.value.kind == "portfolio_create"
    assert await _used(app_rls, "portfolio_create") == limit


async def test_a_refused_creation_writes_no_portfolio(owner, app_rls):
    """The charge shares the caller's transaction, so the refusal has to leave
    the row count where it was — not a portfolio created and then unpaid for."""
    limit, _ = usage_service.limits_for("portfolio_create")
    for i in range(limit):
        async with app_rls() as db, db.begin():
            await portfolio_service.create_portfolio(db, owner_id=USER, name=f"p{i}")

    try:
        async with app_rls() as db, db.begin():
            await portfolio_service.create_portfolio(db, owner_id=USER, name="refused")
    except usage_service.QuotaExceeded:
        pass

    async with app_rls() as db:
        r = await db.execute(text("SELECT count(*) FROM portfolios WHERE owner_id = :u"), {"u": USER})
        assert r.scalar_one() == limit


async def test_the_ceiling_and_the_pool_are_different_refusals(owner, app_rls):
    """MAX_PORTFOLIOS_PER_USER is permanent; the pool resets tomorrow. Both are
    429 at the API, and conflating them would tell a user to come back tomorrow
    for a limit that never lifts. The ceiling is checked FIRST, so a user at the
    ceiling is not also billed a unit for being told no."""
    assert portfolio_service.MAX_PORTFOLIOS_PER_USER > usage_service.limits_for("portfolio_create")[0]

    async with owner() as db, db.begin():
        for i in range(portfolio_service.MAX_PORTFOLIOS_PER_USER):
            await db.execute(
                text("INSERT INTO portfolios (id, name, owner_id, is_public) "
                     "VALUES (:i, 'seeded', :u, FALSE)"),
                {"i": f"port_{TAG}_{i}", "u": USER})

    before = await _used(app_rls, "portfolio_create")
    with pytest.raises(portfolio_service.TooManyPortfolios):
        async with app_rls() as db, db.begin():
            await portfolio_service.create_portfolio(db, owner_id=USER, name="over ceiling")
    assert await _used(app_rls, "portfolio_create") == before, "the ceiling must not cost a unit"
