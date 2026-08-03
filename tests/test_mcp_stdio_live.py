"""P1.3 — the stdio door, against a real database (live).

Run with:  pytest -m live -k mcp_stdio

The offline tests prove the module cannot construct a privileged connection and
refuses to start without an identity. What they cannot prove is the part that
matters: that a call arriving through this door is scoped by row-level security
to the user named in the environment, and lands in the trace attributed to them.
Proving that needs the real policies, so it runs here.

Everything goes through the module's own entry points — no test-only session, no
test-only factory — because the thing under test is the wiring.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

pytestmark = pytest.mark.live

OWNER_URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)
# The runtime role, reached on the host's published port. Same role the app uses,
# so the policies under test are the ones that ship — reading as the owner would
# prove nothing, since the table owner bypasses RLS.
APP_URL = os.getenv(
    "DATABASE_URL_LOCAL_APP",
    "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench",
)

TAG = uuid.uuid4().hex[:8]
STDIO_USER = f"user_mcp_stdio_{TAG}"
OTHER_USER = f"user_mcp_other_{TAG}"


@pytest.fixture(autouse=True)
def app_factory_on_the_host(monkeypatch):
    """Point the door's factory at the published port.

    The shipped settings name the container's hostname, which does not resolve
    here. Only the URL changes: the sessions still come from a plain
    async_sessionmaker, so db/session.py's after_begin listener — the single
    place the tenant GUC is set — applies exactly as it does in the app.
    """
    from apps.mcp import server

    engine = create_async_engine(APP_URL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(server, "get_session_factory", lambda: factory)
    yield


@pytest.fixture
async def two_users():
    """A user for the door and a stranger whose portfolio it must not see."""
    engine = create_async_engine(OWNER_URL)
    async with engine.begin() as c:
        for uid in (STDIO_USER, OTHER_USER):
            await c.execute(text("INSERT INTO users (id, email) VALUES (:i, :e) ON CONFLICT DO NOTHING"),
                            {"i": uid, "e": f"{uid}@example.test"})
        await c.execute(
            text("INSERT INTO portfolios (id, name, owner_id, is_public) "
                 "VALUES (:i, :n, :o, false) ON CONFLICT DO NOTHING"),
            {"i": f"port_{TAG}", "n": "stranger's book", "o": OTHER_USER},
        )
    yield
    async with engine.begin() as c:
        await c.execute(text("DELETE FROM agent_steps WHERE session_id IN "
                             "(SELECT id FROM agent_sessions WHERE owner_id = :o)"), {"o": STDIO_USER})
        await c.execute(text("DELETE FROM agent_sessions WHERE owner_id = :o"), {"o": STDIO_USER})
        await c.execute(text("DELETE FROM portfolios WHERE id = :i"), {"i": f"port_{TAG}"})
        await c.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": STDIO_USER, "b": OTHER_USER})
    await engine.dispose()


async def test_an_unknown_user_cannot_open_the_door(two_users):
    from apps.mcp import server

    with pytest.raises(RuntimeError) as exc:
        await server._open(f"user_not_in_the_table_{TAG}")
    assert "users" in str(exc.value)


async def test_a_call_is_attributed_and_tenant_scoped(two_users, monkeypatch):
    """One call, three claims: the session has an owner, the step is recorded
    under it, and the stranger's portfolio is not in the reply."""
    from apps.mcp import server

    monkeypatch.setattr(server, "_session", server._Session())
    monkeypatch.setenv("MCP_STDIO_USER_ID", STDIO_USER)

    out = await server.call_tool("get_portfolio_snapshot", {})
    payload = json.loads(out[0].text)
    body = json.dumps(payload)

    assert "error" not in payload, payload
    # Both halves, because either one alone is satisfied by a read that returned
    # nothing at all: the public demo book IS visible to any authenticated user,
    # and the stranger's private one is not.
    assert "port_001" in body, "the read produced nothing, so its scope proves nothing"
    assert f"port_{TAG}" not in body, "RLS did not scope the door's read"

    engine = create_async_engine(OWNER_URL)
    async with engine.connect() as c:
        row = (await c.execute(
            text("SELECT owner_id, kind, turn_tool_budget FROM agent_sessions WHERE id = :i"),
            {"i": server._session.id},
        )).one()
        assert row.owner_id == STDIO_USER
        assert row.kind == "mcp"
        # per_turn=False: a process is not a conversation and never claims a turn,
        # so a per-turn counter would be spent once and never reset (V3-R6).
        assert row.turn_tool_budget is None

        steps = (await c.execute(
            text("SELECT tool_name, status FROM agent_steps WHERE session_id = :i"),
            {"i": server._session.id},
        )).all()
        assert [(s.tool_name, s.status) for s in steps] == [("get_portfolio_snapshot", "completed")]
    await engine.dispose()


async def test_the_door_serves_the_whole_meta_face(two_users):
    """The four delegation/gate tools were trimmed away on every startup before
    P1.1; now that a call can be attributed to a user, they are served."""
    from apps.mcp import server
    from exposure_workbench.tools import faces

    tools = await server.list_tools()
    assert [t.name for t in tools] == faces.FACE_META_AGENT
    assert {"ensure_company_ready", "start_issuer_research", "start_exposure_run", "respond"} <= {
        t.name for t in tools
    }
    # and the schemas are the registry's own, not a signature-inspected stand-in
    assert all(t.inputSchema.get("type") == "object" for t in tools)
    assert "kwargs" not in json.dumps([t.inputSchema for t in tools])
