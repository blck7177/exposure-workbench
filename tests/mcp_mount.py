"""A mount of the resident tool face, in this process, with no socket under it.

MCP_PLAN R5. The guards written against R4 have to drive the REAL door — the
same bearer middleware, the same StreamableHTTPSessionManager in the same
stateless mode, the same lowlevel server the container serves — because what
they exist to prove is that a contextvar bound at the door is still bound when a
tool handler runs, and that is a claim about how those three schedule tasks. A
hand-rolled inner app cannot say anything about it: R1's middleware tests passed
against one while the question was still open.

What is left out is the socket. httpx's ASGITransport hands the request straight
to the app object, so these tests need no port, no uvicorn and no teardown race,
while every layer that decides anything is the shipped one. The two things it
cannot show are a real network failure and a real database, which is what the
live half of parity is still for.

The registry is the caller's. A test about identity therefore needs no database
at all: its tool can be a function that records whose claims it ran under.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from apps.mcp.middleware import bearer_identity
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth import internal_token
from exposure_workbench.tools.mcp_server import build_mcp_server

# 32 bytes of it, because pyjwt 2.13 warns on every HMAC key shorter than that
# and a suite that prints a warning per token is a suite nobody reads.
TEST_SECRET = "test-internal-secret-0123456789abcdef"

# Any absolute URL will do — ASGITransport routes on the app object, not on the
# host — but it is spelled the way MCP_URL is so a test reads like the deploy.
BASE_URL = "http://exposure-mcp:8000"


def use_secret(monkeypatch, secret: str = TEST_SECRET) -> None:
    """Sign with a known key rather than whatever .env happens to hold.

    Several live test modules load .env at import, so os.environ during a test
    run depends on the developer's machine. An offline guard that would pass or
    fail on that is not a guard.
    """
    monkeypatch.setattr(get_settings(), "mcp_internal_secret", secret)


class RecordingDb:
    """Enough session for invoke()'s trace write, and nothing else.

    Deliberately not a mock of the database: the tools these tests mount are
    reflection-class, so nothing reserves budget and nothing reads a row. The
    only real call underneath is trace_service.record_step, which asks for the
    next seq and adds a row.
    """

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    async def __aenter__(self) -> "RecordingDb":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def execute(self, *_a, **_k):
        class _Result:
            def scalar_one(self_inner) -> int:
                return len(self.added) + 1

        return _Result()

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


@asynccontextmanager
async def mounted(registry, face, *, face_name, db_factory=None):
    """One mount, as the container assembles it: door in front of transport.

    Built per test rather than imported from apps/mcp/http.py because
    StreamableHTTPSessionManager.run() is once-per-instance by contract, and the
    module-level managers there would be spent after the first test that used
    them.
    """
    server = build_mcp_server(
        registry, face, db_factory=db_factory or RecordingDb, face_name=face_name,
    )
    manager = StreamableHTTPSessionManager(app=server, stateless=True)
    door = bearer_identity(manager.handle_request, expected_face=face_name)
    async with manager.run():
        yield door


@asynccontextmanager
async def connected(door, *, face_name, token=None, **identity):
    """An initialized ClientSession against `door`, carrying a minted bearer.

    `token` is for the tests that need a bearer mint() would not produce;
    everything else names an identity and gets the real thing.
    """
    if token is None:
        token = internal_token.mint(face=face_name, **identity)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=door),
        headers={"Authorization": f"Bearer {token}"},
        base_url=BASE_URL,
    ) as http_client:
        async with streamable_http_client(
            f"{BASE_URL}/mcp/{face_name}", http_client=http_client,
        ) as (read_stream, write_stream, _get_session_id):
            async with ClientSession(read_stream, write_stream) as client:
                await client.initialize()
                yield client
