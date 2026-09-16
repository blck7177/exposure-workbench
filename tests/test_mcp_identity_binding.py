"""R5 — two tenants, one resident mount, at the same instant (offline).

This file is what v2 traded away. Until R2 a server was built per turn with the
tenant fixed in its closure, so two tenants could not be confused: there were
two servers. Residency replaced that with "the door binds a contextvar and the
handler reads it", and a contextvar is only as good as the task the handler
happens to run in — the transport spawns that task, not this repo.

So the proof cannot be a stub. Everything below the token is the shipped
article: apps/mcp/middleware.bearer_identity, StreamableHTTPSessionManager with
stateless=True, the lowlevel Server that build_mcp_server returns, and the same
MCP client the agent loops use. Only the socket is missing (tests/mcp_mount.py).

And it cannot be sequential. Two calls one after the other pass under a
process-global identity too, because the last writer simply wins. The tool below
holds both requests inside its own handler on a barrier and only then reads who
it is running as, so the assertion is made in the one arrangement that tells a
bound identity from an ambient one.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.auth.internal_token import InternalClaims
from exposure_workbench.tools import faces, mcp_request, registry as R
from tests.mcp_mount import RecordingDb, connected, mounted, use_secret

FACE = faces.FACE_NAME_META
FACE_TOOLS = ["whoami"]


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    use_secret(monkeypatch)


def _registry(gate: asyncio.Barrier | None = None) -> R.ToolRegistry:
    """One tool, whose whole job is to say whose request it is running inside.

    A reflection tool because reflections spend no budget: this face has no
    database and nothing to reserve against, and the question here is identity,
    not enforcement — that is invoke()'s and it is tested where it lives.
    """

    async def whoami(db) -> dict:
        # Both requests are made to stand here together, so an identity that was
        # ambient rather than bound has already been overwritten by the other
        # one by the time either reads it.
        if gate is not None:
            await gate.wait()
        claims = mcp_request.current()
        return {
            "user_id": claims.user_id,
            "session_id": claims.session_id,
            "message_id": claims.message_id,
            # The two the request also has to carry, because they are what the
            # database and the ledger read: the tenant GUC comes from the first
            # (db/session.py's listener) and calc_ledger.invoked_by from the
            # second (registry._session_ctx).
            "tenant": current_user_ctx.get(),
            "traced_session": R.current_session_id(),
        }

    registry = R.ToolRegistry()
    registry.register(R.Tool(
        name="whoami", description="Report the identity this call is running under.",
        json_schema={"type": "object", "properties": {}, "additionalProperties": False},
        fn=whoami, tool_class=R.REFLECTION,
    ))
    return registry


def _payload(result) -> dict:
    return json.loads(result.content[0].text)


async def _call_as(door, *, user_id, session_id, message_id=None):
    async with connected(door, face_name=FACE, user_id=user_id,
                         session_id=session_id, message_id=message_id) as client:
        return _payload(await client.call_tool("whoami", {}))


async def test_two_tenants_calling_at_once_each_run_under_their_own_identity():
    gate = asyncio.Barrier(2)
    async with mounted(_registry(gate), FACE_TOOLS, face_name=FACE) as door:
        # Deliberately a THIRD value, and set before the requests are made: if
        # anything downstream inherits the calling context instead of reading
        # what the door bound, both calls come back as this one.
        current_user_ctx.set("user_neither_of_them")

        for_a, for_b = await asyncio.wait_for(asyncio.gather(
            _call_as(door, user_id="user_a", session_id="sess_a", message_id="msg_a"),
            _call_as(door, user_id="user_b", session_id="sess_b", message_id="msg_b"),
        ), timeout=30)

    assert for_a == {"user_id": "user_a", "session_id": "sess_a", "message_id": "msg_a",
                     "tenant": "user_a", "traced_session": "sess_a"}
    assert for_b == {"user_id": "user_b", "session_id": "sess_b", "message_id": "msg_b",
                     "tenant": "user_b", "traced_session": "sess_b"}


async def test_the_identity_of_one_request_does_not_survive_into_the_next():
    """The same mount, twice, sequentially — the arrangement a long-lived server
    is actually in most of the time. Nothing may be left over from the first
    request for the second to inherit."""
    async with mounted(_registry(), FACE_TOOLS, face_name=FACE) as door:
        first = await _call_as(door, user_id="user_a", session_id="sess_a")
        second = await _call_as(door, user_id="user_b", session_id="sess_b")

    assert (first["user_id"], first["tenant"]) == ("user_a", "user_a")
    assert (second["user_id"], second["tenant"]) == ("user_b", "user_b")
    assert mcp_request.current_mcp_request.get() is None


async def test_two_tenants_listing_at_once_each_see_their_own_face():
    """list_tools reads the same claims call_tool does, so it can be told the
    same lie. Concurrency here is what proves the deny list is per REQUEST and
    not per mount — one connection asking for a narrower face must not narrow
    what the other is shown."""
    gate = asyncio.Barrier(2)

    async def _list_as(*, user_id, session_id, deny):
        async with connected(door, face_name=FACE, user_id=user_id,
                             session_id=session_id, deny=deny) as client:
            await gate.wait()
            listed = await client.list_tools()
            return [t.name for t in listed.tools]

    async with mounted(_registry(), FACE_TOOLS, face_name=FACE) as door:
        full, narrowed = await asyncio.wait_for(asyncio.gather(
            _list_as(user_id="user_a", session_id="sess_a", deny=()),
            _list_as(user_id="user_b", session_id="sess_b", deny=("whoami",)),
        ), timeout=30)

    assert full == ["whoami"]
    assert narrowed == []


async def test_the_tenant_comes_from_the_claims_and_not_from_the_context():
    """call_tool's own station, isolated from the door's.

    The door sets current_user_ctx too, so in an HTTP request the two agree and
    either one alone would look sufficient. They are not the same station: a
    handler runs in whatever task the transport gives it, and the stdio door
    binds claims from an environment variable with no door in front of it at
    all. So the assertion is made where only the handler can satisfy it — claims
    bound for one user, the ambient tenant set to somebody else, and the tool
    reads the tenant the request named.
    """
    from exposure_workbench.tools.mcp_server import build_mcp_server
    from mcp import types

    server = build_mcp_server(_registry(), FACE_TOOLS, db_factory=RecordingDb,
                              face_name=FACE)
    handler = server.request_handlers[types.CallToolRequest]

    current_user_ctx.set("user_neither_of_them")
    token = mcp_request.bind(InternalClaims(user_id="user_b", session_id="sess_b", face=FACE))
    try:
        result = await handler(types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="whoami", arguments={}),
        ))
    finally:
        mcp_request.current_mcp_request.reset(token)

    assert json.loads(result.root.content[0].text) == {
        "user_id": "user_b", "session_id": "sess_b", "message_id": None,
        "tenant": "user_b", "traced_session": "sess_b",
    }


async def test_a_tool_handler_with_no_verified_request_behind_it_refuses_to_guess():
    """The state this whole mechanism exists to make unreachable: before P1.3 the
    stdio door ran every call under one process-global session with
    owner_id=None, so the trace could not say whose work it was and RLS had no
    tenant to scope to. current() raising is what stops that from coming back as
    somebody's `or "anonymous"`."""
    from exposure_workbench.tools.mcp_server import build_mcp_server
    from mcp import types

    server = build_mcp_server(_registry(), FACE_TOOLS, db_factory=None, face_name=FACE)
    handler = server.request_handlers[types.ListToolsRequest]

    with pytest.raises(mcp_request.NoMcpRequestBound):
        await handler(types.ListToolsRequest(method="tools/list"))


# ── V37/M1: which agent of the turn made the call ────────────────────────────

async def _call_with_actor(actor: str | None) -> list:
    """One real call through the real mount, and the step it wrote.

    `db_factory=lambda: db` so the row survives the request: invoke() opens the
    factory per call and the trace write is the only thing underneath.
    """
    db = RecordingDb()
    async with mounted(_registry(), FACE_TOOLS, face_name=FACE, db_factory=lambda: db) as door:
        async with connected(door, face_name=FACE, user_id="user_a", session_id="sess_a",
                             message_id="msg_a") as client:
            await client.call_tool("whoami", {}, meta={"actor": actor} if actor else None)
    return db.added


async def test_the_call_says_which_agent_of_the_turn_made_it():
    """V37/M1. One turn holds a lead analyst and a domain analyst per delegated
    task, and they share a bearer by design (D3): their facts have to land on one
    ledger, so the token names the turn and cannot name the caller. Round B's
    communication table therefore had to attribute all one hundred `run` calls to
    whoever had spoken last, and said so with a `~` on every row.

    The actor rides on the CALL, as request metadata, through the shipped
    middleware and transport. It is trace only — enforcement is still the face
    and the bearer, verified at the door — so what is asserted here is that it
    arrives and is written down, and that the identity it travels beside is
    untouched.
    """
    [step] = await _call_with_actor("sub:book_market_risk")
    assert step.actor == "sub:book_market_risk"
    assert (step.session_id, step.message_id) == ("sess_a", "msg_a"), "the bearer still says whose turn"


async def test_a_call_that_names_no_actor_is_the_loop_that_owns_the_turn():
    """None, not a guess and not a default: every row written before V37 reads
    this way, and the lead analyst's own calls still do."""
    [step] = await _call_with_actor(None)
    assert step.actor is None
