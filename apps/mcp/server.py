"""MCP server over the ToolRegistry (M8/M10) — one constructor, three callers.

Registry-driven: list_tools/call_tool dispatch straight to the registry, so the
tools' exact JSON schemas are what a client sees and every call goes through the
same wrapper — argument validation, budget, citation-linked trace — no matter
who is connected.

The server is BUILT, not imported. It used to be a script: a registry chosen at
import time, a face computed at import time, one process-global session, and the
identity of whoever was calling nowhere in the picture. That shape fits exactly
one caller, and there are three — the stdio debug door below, and the meta-agent
and research session, which connect over an in-memory transport (MCP_PLAN
P3/P4). Registry, face, session and tenant are arguments because they differ per
caller; enforcement is not an argument, because it does not.

The stdio door is for local debugging: opening an inspector against a running
database and watching a tool call land. Two things it deliberately cannot do:

It cannot choose a database role. It used to build its own engine on
DATABASE_URL — the OWNER role, which bypasses row-level security — so the one
place a tool call reached the database outside the tenant mechanism was the
agent-facing one. It borrows the application's app_rls factory now, and a test
reads the import graph to keep it that way.

It cannot be anonymous. MCP_STDIO_USER_ID is required, checked against the users
table before the first request, with no demo fallback: a debug door is always
opened by somebody.

Run standalone over stdio:
    MCP_STDIO_USER_ID=user_... python -m apps.mcp.server
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from mcp import types
from mcp.server.lowlevel import Server
from sqlalchemy import select

from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.db.models import User
from exposure_workbench.db.session import get_session_factory
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.tools import faces, registry as R
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.meta_tools import register_meta_tools

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("mcp-server")

SERVER_NAME = "exposure-workbench"
STDIO_USER_ENV = "MCP_STDIO_USER_ID"

# Sent at initialize, so a consumer that has never read this repo's system
# prompts still learns the discipline the gate is going to hold it to. It says
# why, not what: the rules are enforced in the wrapper, and a list of them here
# would only be a second place for them to drift.
INSTRUCTIONS = """Tools for a portfolio risk and issuer-intelligence desk: financial facts and
calculations, filing search and full-text read, market stats, portfolio
holdings and alerts, and delegation of long work to background runs.

State no number you did not get from a tool, and cite the evidence ids
(fact_/chunk_/calc_/src_/run_/alert_/pos_) behind any factual claim — a figure
the desk cannot trace back to a filing, a calculation or a run is not usable,
and the gate will refuse an answer that cites what was never retrieved.

Calculations belong to the tools: a number you worked out yourself has no id to
cite. Delegation tools return immediately with a run id; they do not block."""


def build_mcp_server(
    registry: R.ToolRegistry,
    face: list[str],
    *,
    db_factory,
    session_id: str,
    user_id: str | None = None,
    message_id: str | None = None,
) -> Server:
    """An MCP server over `face` of `registry`, recording under `session_id`.

    `face` is resolved strictly (P1.1): a face naming a tool the registry does
    not have raises here rather than serving a quietly smaller surface.
    """
    tool_names = faces.resolve(registry, face)
    server = Server(SERVER_NAME, instructions=INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        # Declared order, which is both stable across calls — the 2026-07-28
        # spec asks for that so a consumer keeps its prompt cache — and the
        # order an auditor reads the face in.
        return [
            types.Tool(
                name=registry.get(name).name,
                description=registry.get(name).description,
                inputSchema=registry.get(name).json_schema,
            )
            for name in tool_names
        ]

    # validate_input=False: the decorator otherwise runs its own jsonschema check
    # against inputSchema and returns a flat "Input validation error" for the
    # FIRST failure. That preempts the gate — one problem instead of all of them,
    # and no trace step at all, because invoke() is never reached. The single
    # enforcement point has to stay single.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
        if user_id is not None:
            # Before the session opens: db/session.py sets the tenant GUC when a
            # transaction begins, so setting it afterwards leaves the first query
            # tenant-less. Set per call rather than trusted from the surrounding
            # context — a handler runs in whatever task the transport gives it.
            current_user_ctx.set(user_id)
        async with db_factory() as db:
            result = await R.invoke(registry, db, session_id, name, arguments or {},
                                    message_id=message_id)
            await db.commit()
        # isError marks a refusal as one for a client that cares, while the
        # structured payload — problems[], budget numbers, the tool's own error —
        # stays intact in the content, because that is what the model acts on.
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, default=str))],
            isError=bool(isinstance(result, dict) and result.get("error")),
        )

    return server


# ── the stdio debug door ────────────────────────────────────────────────────────

def stdio_user_id(env: dict | None = None) -> str:
    """Whose door this is. Absent or blank is a startup failure, not a default.

    A blank value is how a shell passes along a variable it does not have, so it
    is refused for the same reason an unset one is.
    """
    raw = (env if env is not None else os.environ).get(STDIO_USER_ENV) or ""
    user_id = raw.strip()
    if not user_id:
        raise RuntimeError(
            f"{STDIO_USER_ENV} is required: the stdio door runs as a real user so "
            "its trace can be attributed and RLS has a tenant to scope to. Set it "
            "to a row in the users table."
        )
    return user_id


class _Session:
    """The one agent session the stdio process records its work under."""

    user_id: str | None = None
    id: str | None = None


_session = _Session()


async def _open(user_id: str) -> str:
    """Validate the identity against the users table, then open the session.

    The check is a read under that user's own tenant, which is also the first
    proof that the GUC injection works from this entry point.
    """
    current_user_ctx.set(user_id)
    factory = get_session_factory()
    async with factory() as db:
        exists = (await db.execute(select(User.id).where(User.id == user_id))).scalar_one_or_none()
        if exists is None:
            raise RuntimeError(
                f"{STDIO_USER_ENV}={user_id!r} is not a row in users. The door does not "
                "create accounts; use an id that already exists."
            )
        # kind='mcp' so a debug session is distinguishable in the monitor from a
        # user's chat. per_turn=False because this is a process, not a
        # conversation: it never claims a turn, so a per-turn counter would be
        # spent once and never reset (V3-R6).
        s = await sess.create_session(db, kind="mcp", owner_id=user_id, per_turn=False)
        await db.commit()
        logger.info("stdio session %s opened for %s", s.id, user_id)
        return s.id


async def build_stdio_server() -> Server:
    """The debug door: whole meta face, real user, the app's own factory."""
    if _session.id is None:
        _session.user_id = stdio_user_id()
        _session.id = await _open(_session.user_id)
    return build_mcp_server(
        register_meta_tools(build_read_registry()),
        faces.FACE_META_AGENT,
        db_factory=get_session_factory(),
        session_id=_session.id,
        user_id=_session.user_id,
    )


async def _main() -> None:
    from mcp.server.stdio import stdio_server

    server = await build_stdio_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
