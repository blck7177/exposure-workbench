"""V2-G — tenant isolation, as a replayable script (live: needs a real Postgres).

Run with:  pytest -m live -k tenancy

V2-C proved this by hand with two browser accounts. Hand-proof does not survive
a schema change, and every phase since has added tables and policies. This is the
same argument in a form that runs.

Everything here connects as `app_rls` — the non-owner runtime role — and switches
tenant the way the app does, transaction-locally. Reading it as the owner would
prove nothing at all: the table owner bypasses RLS, which is the single biggest
foot-gun in this design.

The strong claim being tested is not "B gets 403 for A's data". It is that A's
data is INVISIBLE to B: the same query returns zero rows, so there is no
existence oracle and no code path that has to remember to check.
"""

from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

pytestmark = pytest.mark.live

OWNER_URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)
APP_URL = os.getenv(
    "DATABASE_URL_LOCAL_APP",
    "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench",
)

TAG = uuid.uuid4().hex[:8]
A = f"user_tenancy_A_{TAG}"
B = f"user_tenancy_B_{TAG}"
DEMO_PORTFOLIO = "port_001"


@pytest.fixture
async def owner():
    engine = create_async_engine(OWNER_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    async with mk() as db, db.begin():
        for uid in (A, B):
            await db.execute(text("INSERT INTO users (id, email) VALUES (:u, :e)"),
                             {"u": uid, "e": f"{uid}@example.test"})
        # A owns a private book with one holding and one run; B owns nothing.
        await db.execute(
            text("""INSERT INTO portfolios (id, name, owner_id, is_public)
                    VALUES (:p, 'A private book', :a, FALSE)"""),
            {"p": f"port_{TAG}_a", "a": A})
        await db.execute(
            text("""INSERT INTO positions (id, portfolio_id, as_of_date, ticker, quantity)
                    VALUES (:i, :p, CURRENT_DATE, 'AAPL', 10)"""),
            {"i": f"pos_{TAG}_a", "p": f"port_{TAG}_a"})
        await db.execute(
            text("""INSERT INTO exposure_runs (id, portfolio_id, status, as_of_date)
                    VALUES (:r, :p, 'completed', CURRENT_DATE)"""),
            {"r": f"run_{TAG}_a", "p": f"port_{TAG}_a"})
        await db.execute(
            text("""INSERT INTO exposure_metrics (run_id, portfolio_market_value)
                    VALUES (:r, 12345.67)"""),
            {"r": f"run_{TAG}_a"})
        await db.execute(
            text("""INSERT INTO agent_sessions (id, kind, owner_id)
                    VALUES (:s, 'meta', :a)"""),
            {"s": f"sess_{TAG}_a", "a": A})
        await db.execute(
            text("""INSERT INTO agent_messages (id, session_id, role, content)
                    VALUES (:m, :s, 'user', 'A private question')"""),
            {"m": f"msg_{TAG}_a", "s": f"sess_{TAG}_a"})
    try:
        yield mk
    finally:
        async with mk() as db, db.begin():
            for table, col, val in [
                ("agent_messages", "id", f"msg_{TAG}_a"),
                ("agent_sessions", "id", f"sess_{TAG}_a"),
                ("exposure_metrics", "run_id", f"run_{TAG}_a"),
                ("exposure_runs", "id", f"run_{TAG}_a"),
                ("positions", "id", f"pos_{TAG}_a"),
                ("portfolios", "id", f"port_{TAG}_a"),
            ]:
                await db.execute(text(f"DELETE FROM {table} WHERE {col} = :v"), {"v": val})
            await db.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": A, "b": B})
        await engine.dispose()


@pytest.fixture
async def app_engine():
    engine = create_async_engine(APP_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


async def as_tenant(engine, uid: str | None, sql: str, params: dict | None = None):
    """One transaction as app_rls with app.user_id set exactly like the app does."""
    mk = async_sessionmaker(engine, expire_on_commit=False)
    async with mk() as db, db.begin():
        if uid is not None:
            await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": uid})
        return (await db.execute(text(sql), params or {})).all()


# ── visibility ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query,label", [
    ("SELECT id FROM portfolios WHERE id = :p", "portfolio"),
    ("SELECT id FROM positions WHERE portfolio_id = :p", "positions"),
    ("SELECT id FROM exposure_runs WHERE portfolio_id = :p", "runs"),
])
async def test_b_cannot_see_a_s_portfolio_tree(owner, app_engine, query, label):
    p = {"p": f"port_{TAG}_a"}
    assert len(await as_tenant(app_engine, A, query, p)) == 1, f"A must see their own {label}"
    assert await as_tenant(app_engine, B, query, p) == [], f"B can see A's {label}"


async def test_b_cannot_see_a_s_run_children_even_by_direct_id(owner, app_engine):
    """The child tables carry no owner column — they cascade through EXISTS on the
    parent. Naming the run id directly is the case that would expose a policy
    written against the wrong parent."""
    q = "SELECT portfolio_market_value FROM exposure_metrics WHERE run_id = :r"
    p = {"r": f"run_{TAG}_a"}
    assert len(await as_tenant(app_engine, A, q, p)) == 1
    assert await as_tenant(app_engine, B, q, p) == []


async def test_b_cannot_read_a_s_conversation(owner, app_engine):
    q = "SELECT content FROM agent_messages WHERE session_id = :s"
    p = {"s": f"sess_{TAG}_a"}
    assert len(await as_tenant(app_engine, A, q, p)) == 1
    assert await as_tenant(app_engine, B, q, p) == []


async def test_an_unset_tenant_sees_only_public_rows(owner, app_engine):
    """Fail-closed: a request that never set a tenant must not become a superuser.
    The public demo stays visible, because the anonymous shop window is a
    deliberate product decision rather than a leak."""
    rows = await as_tenant(app_engine, None, "SELECT id, is_public FROM portfolios")
    assert rows, "the public demo must still be visible anonymously"
    assert all(r[1] for r in rows), f"non-public rows visible with no tenant: {rows}"
    assert any(r[0] == DEMO_PORTFOLIO for r in rows)


# ── writes ────────────────────────────────────────────────────────────────────

async def test_b_cannot_write_into_a_s_portfolio(owner, app_engine):
    """USING hides it; WITH CHECK is what stops a blind write to a known id."""
    with pytest.raises(Exception) as e:
        await as_tenant(
            app_engine, B,
            "INSERT INTO positions (id, portfolio_id, as_of_date, ticker, quantity) "
            "VALUES (:i, :p, CURRENT_DATE, 'EVIL', 1) RETURNING id",
            {"i": f"pos_{TAG}_evil", "p": f"port_{TAG}_a"},
        )
    assert "row-level security" in str(e.value).lower()


async def test_b_updating_a_s_portfolio_silently_matches_nothing(owner, app_engine):
    """An UPDATE against a row B cannot see does not raise — it matches zero rows,
    because USING filters the rows the statement is allowed to consider before
    WITH CHECK ever runs. That distinction matters to callers: a service that
    treats "0 rows updated" as success would report a write that never happened.

    The property under test is the outcome, not which half of the policy produced
    it, so assert the data rather than the exception."""
    changed = await as_tenant(
        app_engine, B,
        "UPDATE portfolios SET name = 'stolen' WHERE id = :p RETURNING id",
        {"p": f"port_{TAG}_a"},
    )
    assert changed == [], "B's update must match no rows at all"

    still = await as_tenant(app_engine, A, "SELECT name FROM portfolios WHERE id = :p",
                            {"p": f"port_{TAG}_a"})
    assert still[0][0] == "A private book", "A's data must be untouched"


async def test_the_public_demo_is_readable_but_not_writable_by_a_visitor(owner, app_engine):
    seen = await as_tenant(app_engine, B, "SELECT id FROM portfolios WHERE id = :p",
                           {"p": DEMO_PORTFOLIO})
    assert len(seen) == 1, "the demo is the public shop window"
    with pytest.raises(Exception) as e:
        await as_tenant(
            app_engine, B,
            "INSERT INTO positions (id, portfolio_id, as_of_date, ticker, quantity) "
            "VALUES (:i, :p, CURRENT_DATE, 'EVIL', 1) RETURNING id",
            {"i": f"pos_{TAG}_demo", "p": DEMO_PORTFOLIO},
        )
    assert "row-level security" in str(e.value).lower()


# ── the pooling hazard ────────────────────────────────────────────────────────

async def test_alternating_tenants_on_a_pooled_connection_never_leak(owner, app_engine):
    """set_config(..., true) is transaction-local, so a pooled connection cannot
    carry one user's tenant into the next request. This is the failure that would
    be invisible under low load and catastrophic under real traffic, so it is
    worth hammering rather than checking once."""
    q = "SELECT count(*) FROM portfolios WHERE id = :p"
    p = {"p": f"port_{TAG}_a"}
    for _ in range(12):
        assert (await as_tenant(app_engine, A, q, p))[0][0] == 1
        assert (await as_tenant(app_engine, B, q, p))[0][0] == 0
        assert (await as_tenant(app_engine, None, q, p))[0][0] == 0


async def test_the_runtime_role_cannot_delete_anything(owner, app_engine):
    """Append-only is hardened at the grant layer, not by convention — which is
    also why the lease reaper marks records failed instead of removing them."""
    with pytest.raises(Exception) as e:
        await as_tenant(app_engine, A, "DELETE FROM portfolios WHERE id = :p",
                        {"p": f"port_{TAG}_a"})
    assert "permission denied" in str(e.value).lower()
