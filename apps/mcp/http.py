"""The resident tool face (MCP_PLAN R2, decisions N6/N9/N10).

One process holding both agent faces: /mcp/meta for the api's meta-agent,
/mcp/research for the worker's research subagent. Each is a mount of its own,
with its own registry, its own server object and its own door — N9, physically
rather than by a claim read at dispatch time. A single endpoint that picked a
face from the token would be faces.available()'s silent trimming brought back
with a signature on it: the wrong answer would still be a working answer.

A container of its own because the face is not a library. Until R2 the server
was built per turn inside whichever process ran the loop, so the tools, their
database pool and their provider keys were duplicated into api and worker and
lived exactly as long as one turn. Resident, the surface has one address, one
set of credentials, one restart policy, and one place to look when an agent
reports that a tool failed. The LLM call did not move and must not: completion
stays in the loops, in api and worker; nothing behind this door talks to a model
except the retrieval tools that embed their own query.

Enforcement is unchanged and did not move either. Budget, argument validation,
citation linkage and the trace row are all still inside registry.invoke(), one
call below the handler this transport reaches. Residency changed where the code
runs, not what it does; identity is the single thing that changed shape, from a
constructor argument into a per-request bearer, which is apps/mcp/middleware.py.

Run:
    uvicorn apps.mcp.http:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from apps.mcp.middleware import bearer_identity
from exposure_workbench.auth import internal_token
from exposure_workbench.db.session import get_session_factory
from exposure_workbench.tools import faces
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.mcp_server import build_mcp_server
from exposure_workbench.tools.meta_tools import register_meta_tools
from exposure_workbench.workflow.issuer_research_workflow import build_research_registry

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp-http")

# This process IS the tool face: every registry tool, and the database and the
# provider keys behind them, with nothing in front of it but a verified bearer.
# Coming up without a key to verify that bearer with is the one state it must
# never reach, so the check happens before the app object exists rather than on
# the first request — .env.example promises exactly that, and R3's healthcheck
# would otherwise report a process in that state as healthy.
internal_token.require_secret()

# Face name -> (registry, face), each registry built once. The mount name is the
# key, so the name the server is built under, the name its door expects in the
# token and the path it answers on are one value read three times rather than
# three literals that agree until somebody edits one.
MOUNTS = {
    faces.FACE_NAME_META: (register_meta_tools(build_read_registry()), faces.FACE_META_AGENT),
    faces.FACE_NAME_RESEARCH: (build_research_registry(), faces.FACE_RESEARCH),
}

# One server and one session manager per mount, built at import and held for the
# life of the process: that is what residency means here. It also puts
# faces.resolve() at startup, where P1.1 wants it — a face naming a tool nobody
# registered stops this container from coming up, rather than failing whichever
# request happened to arrive first.
SESSION_MANAGERS: dict[str, StreamableHTTPSessionManager] = {
    name: StreamableHTTPSessionManager(
        app=build_mcp_server(
            registry, face, db_factory=get_session_factory(), face_name=name,
        ),
        # stateless: a fresh transport per request, no session id, nothing
        # remembered between two calls of the same run. The 2026-07-28 spec
        # removed protocol sessions (SEP-2567), and this server has nothing to
        # keep in one anyway — every handle it hands out (run_id, fact_id,
        # calc_id) is server-minted and comes back as a plain argument, and the
        # agent session itself lives in Postgres under the token's sid. That is
        # what makes a second replica a scaling decision rather than a
        # correctness one: any replica can serve any request of any run.
        stateless=True,
    )
    for name, (registry, face) in MOUNTS.items()
}


class _Face:
    """One mount, as a raw ASGI app: the bearer door in front of its transport.

    An object rather than the closure bearer_identity hands back, because
    Starlette decides what an endpoint IS by type. A plain function is assumed
    to be func(request) -> response and gets wrapped, so the door would be
    handed a Request where it reads a scope; anything else is passed through as
    ASGI, untouched.

    Route rather than Mount, the other way to attach an ASGI app: Mount matches
    /mcp/meta/<rest> and answers a bare /mcp/meta with a 307 to the trailing
    slash — an extra round trip on each of the thirty-odd tool calls a research
    run makes, and a redirect a client is entitled not to follow.
    """

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        await self._app(scope, receive, send)


async def healthz(request):
    """Liveness, deliberately outside the bearer.

    A healthcheck that has to present a credential reports on the credential: it
    would call this container unhealthy for a probe misconfiguration that has
    nothing to do with the process, and it would still say nothing about the one
    thing R3 asks — whether this process is up and serving HTTP. It exposes no
    tool, no name and no tenant, so there is nothing here to authenticate for.
    """
    return JSONResponse({"status": "ok"})


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    """Every session manager runs, or the process does not.

    run() is once-per-instance by contract and it is what creates the task group
    each mount spawns its per-request server into — handle_request raises
    without it, so a mount left out here is a mount that fails every call. An
    exit stack rather than nested with-blocks because how many faces there are
    is MOUNTS' business, and a face added there must not need a second line
    here to come alive.
    """
    async with contextlib.AsyncExitStack() as stack:
        for name, manager in SESSION_MANAGERS.items():
            await stack.enter_async_context(manager.run())
            logger.info("mcp mount /mcp/%s serving %d tools", name, len(MOUNTS[name][1]))
        yield


app = Starlette(
    routes=[
        Route("/healthz", healthz, methods=["GET"]),
        *[
            Route(
                f"/mcp/{name}",
                endpoint=_Face(bearer_identity(manager.handle_request, expected_face=name)),
                name=f"mcp-{name}",
            )
            for name, manager in SESSION_MANAGERS.items()
        ],
    ],
    lifespan=lifespan,
)
