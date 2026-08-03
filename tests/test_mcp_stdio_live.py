"""P1.3/P2 — the stdio door, over a real transport and a real database (live).

Run with:  pytest -m live -k mcp_stdio

The offline tests prove the module cannot construct a privileged connection,
refuses to start without an identity, and serves the face it was given. What
they cannot prove is the part that matters: that a call arriving through the
transport is scoped by row-level security to the user named in the environment,
lands in the trace attributed to them, and that a bad call is refused by the
gate rather than by the transport.

So these go through a real MCP client session. Nothing here calls invoke()
directly — the wiring is the thing under test.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from dotenv import load_dotenv
from mcp.shared.memory import create_connected_server_and_client_session
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
    monkeypatch.setattr(server, "_session", server._Session())
    monkeypatch.setenv("MCP_STDIO_USER_ID", STDIO_USER)
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


async def _steps(session_id: str) -> list[tuple[str, str]]:
    engine = create_async_engine(OWNER_URL)
    try:
        async with engine.connect() as c:
            rows = (await c.execute(
                text("SELECT tool_name, status FROM agent_steps WHERE session_id = :i "
                     "ORDER BY created_at"),
                {"i": session_id},
            )).all()
            return [(r.tool_name, r.status) for r in rows]
    finally:
        await engine.dispose()


async def test_an_unknown_user_cannot_open_the_door(two_users):
    from apps.mcp import server

    with pytest.raises(RuntimeError) as exc:
        await server._open(f"user_not_in_the_table_{TAG}")
    assert "users" in str(exc.value)


async def test_a_call_is_attributed_and_tenant_scoped(two_users):
    """One call, three claims: the session has an owner, the step is recorded
    under it, and the stranger's portfolio is not in the reply."""
    from apps.mcp import server

    built = await server.build_stdio_server()
    async with create_connected_server_and_client_session(built) as client:
        out = await client.call_tool("get_portfolio_snapshot", {})

    assert not out.isError, out.content
    body = out.content[0].text
    payload = json.loads(body)
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
    await engine.dispose()

    assert await _steps(server._session.id) == [("get_portfolio_snapshot", "completed")]


async def test_a_bad_call_is_refused_by_the_gate_not_the_transport(two_users):
    """The SDK would have validated inputSchema itself and returned one flat
    string, leaving no trace step — the rejection would exist for the model and
    not for the desk. This asserts the refusal that arrives is the gate's."""
    from apps.mcp import server

    built = await server.build_stdio_server()
    async with create_connected_server_and_client_session(built) as client:
        out = await client.call_tool("get_fact_series", {"ticker": "NVDA"})   # no metric

    assert out.isError
    payload = json.loads(out.content[0].text)
    assert payload["error"] == "invalid_arguments"
    assert [p["field"] for p in payload["problems"]] == ["metric"]
    assert "Input validation error" not in out.content[0].text

    assert await _steps(server._session.id) == [("get_fact_series", "rejected")]


async def test_the_door_serves_the_whole_meta_face(two_users):
    """The four delegation/gate tools were trimmed away on every startup before
    P1.1; now that a call can be attributed to a user, they are served."""
    from apps.mcp import server
    from exposure_workbench.tools import faces

    built = await server.build_stdio_server()
    async with create_connected_server_and_client_session(built) as client:
        listed = await client.list_tools()

    assert [t.name for t in listed.tools] == faces.FACE_META_AGENT
    assert {"ensure_company_ready", "start_issuer_research", "start_exposure_run", "respond"} <= {
        t.name for t in listed.tools
    }
    # and the schemas are the registry's own, not a signature-inspected stand-in
    assert all(t.inputSchema.get("type") == "object" for t in listed.tools)
    assert "kwargs" not in json.dumps([t.inputSchema for t in listed.tools])
