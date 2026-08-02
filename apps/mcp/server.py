"""MCP server exposing the ToolRegistry (M8/M10).

Registry-driven: list_tools/call_tool dispatch straight to the registry, so the
tools' exact JSON schemas are what the client sees and every call goes through
the same wrapper (budget + citation-linked trace) as the in-process agent.

Run standalone over stdio:
    python -m apps.mcp.server

Or mount the streamable-HTTP app into another ASGI server (see build_http_app()).
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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.tools import faces, registry as R
from exposure_workbench.tools.definitions import build_read_registry

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("mcp-server")

SERVER_NAME = "exposure-workbench"

# The MCP host plays the meta-agent role -> it sees the meta-agent face.
_registry = build_read_registry()
_FACE = faces.available(_registry, faces.FACE_META_AGENT)


def _db_url() -> str:
    # In-network default (container) is DATABASE_URL; host runs use DATABASE_URL_LOCAL.
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("DATABASE_URL_LOCAL")
        or "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
    )


class _State:
    engine = None
    sessionmaker: async_sessionmaker | None = None
    agent_session_id: str | None = None


_state = _State()


async def _ensure_state() -> None:
    if _state.sessionmaker is None:
        _state.engine = create_async_engine(_db_url())
        _state.sessionmaker = async_sessionmaker(_state.engine, expire_on_commit=False)
    if _state.agent_session_id is None:
        async with _state.sessionmaker() as db:
            # per_turn=False: this session is the HOST PROCESS, not a
            # conversation. It never claims a turn, so a per-turn budget would
            # be spent once and never reset — 15 tool calls for the life of the
            # process (V3-R6).
            s = await sess.create_session(db, kind="meta", per_turn=False)
            await db.commit()
            _state.agent_session_id = s.id
            logger.info("MCP host session %s created", s.id)


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
    await _ensure_state()
    async with _state.sessionmaker() as db:
        result = await R.invoke(_registry, db, _state.agent_session_id, name, arguments or {})
        await db.commit()
    return [types.TextContent(type="text", text=json.dumps(result, default=str))]


def build_http_app():
    """Streamable-HTTP ASGI app, for mounting at /mcp in another server."""
    from mcp.server.fastmcp import FastMCP

    fast = FastMCP(SERVER_NAME)
    for name in _FACE:
        tool = _registry.get(name)

        def _make(tool_name):
            async def _handler(**kwargs):
                await _ensure_state()
                async with _state.sessionmaker() as db:
                    res = await R.invoke(_registry, db, _state.agent_session_id, tool_name, kwargs)
                    await db.commit()
                return res
            return _handler

        fast.add_tool(_make(name), name=tool.name, description=tool.description)
    return fast.streamable_http_app()


async def _main() -> None:
    from mcp.server.stdio import stdio_server

    await _ensure_state()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
