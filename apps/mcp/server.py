"""MCP server over the ToolRegistry — the local-dev debug door (M8/M10).

Registry-driven: list_tools/call_tool dispatch straight to the registry, so the
tools' exact JSON schemas are what the client sees and every call goes through
the same wrapper — budget, input validation, citation-linked trace — as the
agents do. This process is for opening an inspector against a running database
and watching a tool call land; the meta-agent and the research session reach the
same registry in-process (MCP_PLAN P3/P4), not through this entry point.

Two things this module deliberately cannot do:

It cannot choose a database role. It used to build its own engine on
DATABASE_URL — the OWNER role, which bypasses row-level security — so the one
place a tool call reached the database outside the tenant mechanism was the
agent-facing one. It now borrows the application's app_rls factory like every
other caller, and a test reads the import graph to keep it that way.

It cannot be anonymous. It ran every call under one process-global session with
owner_id=None, which meant the trace could not say whose work it was and RLS had
no tenant to scope to. MCP_STDIO_USER_ID is required, checked against the users
table before the first request, and there is no demo fallback: a debug door is
always opened by somebody.

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

# The debug door plays the meta-agent role, so it is handed the meta-agent face
# over the registry that satisfies it. resolve() raises rather than trimming, so
# a face and a registry that disagree stop the process here instead of quietly
# serving a smaller surface (P1.1).
_registry = register_meta_tools(build_read_registry())
_FACE = faces.resolve(_registry, faces.FACE_META_AGENT)


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
    """The one agent session this process records its work under."""

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


async def _ensure_open() -> None:
    if _session.id is None:
        _session.user_id = stdio_user_id()
        _session.id = await _open(_session.user_id)


server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=_registry.get(name).name,
            description=_registry.get(name).description,
            inputSchema=_registry.get(name).json_schema,
        )
        for name in _FACE
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    await _ensure_open()
    # Set before the session opens: the RLS listener reads the contextvar when a
    # transaction begins, so setting it afterwards would leave the first query
    # tenant-less.
    current_user_ctx.set(_session.user_id)
    factory = get_session_factory()
    async with factory() as db:
        result = await R.invoke(_registry, db, _session.id, name, arguments or {})
        await db.commit()
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


async def _main() -> None:
    from mcp.server.stdio import stdio_server

    await _ensure_open()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
