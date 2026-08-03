"""The agents' connection to the tool face (MCP_PLAN P3/P4).

Both loops reach their tools through an MCP client over an in-memory transport:
same registry, same wrapper, same trace, one hop of protocol in between. The
point is not the hop. It is that "the agent face is MCP" stops being a sentence
in the architecture notes and becomes the only way the agents can call anything
— so the face cannot quietly acquire a second definition, and a consumer that
is not this repo's own loop is served by construction rather than by intention.

In-memory rather than a socket: there is no second process to supervise, no port
to bind, and nothing about the enforcement changes with the transport, because
enforcement was never in the transport. A server is built per turn (per run for
research), which is also what carries the turn's identity — registry, face,
session, tenant and message id are fixed when the pair is created.

The loops keep speaking OpenAI's function-calling dialect, so `tools` is
converted back into that shape here. A test asserts the conversion is
byte-identical to what registry.schemas() produced before, because a tool
description that changes on the way to the model is a behaviour change nobody
wrote.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from mcp.shared.memory import create_connected_server_and_client_session

from exposure_workbench.tools import registry as R
from exposure_workbench.tools.mcp_server import build_mcp_server

logger = logging.getLogger(__name__)


def _as_openai_tool(tool) -> dict:
    """An MCP tool as an OpenAI function schema — the shape registry.schemas()
    produced when the loops read the registry directly."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.inputSchema,
        },
    }


class ToolSession:
    """What a loop holds for the length of a turn: the tool list and one verb."""

    def __init__(self, client, mcp_tools):
        self._client = client
        self.tools = [_as_openai_tool(t) for t in mcp_tools]

    async def call(self, name: str, args: dict) -> dict:
        """One tool call, returning what invoke() returned.

        Never raises, because invoke() does not and the loops are written to
        that contract: a tool failure is a result the model reads and adapts to,
        not an exception that ends the turn. The transport can only add two new
        ways to fail — an empty content list and a payload that is not the JSON
        we serialised — and both are reported in the same shape as everything
        else rather than as a traceback.
        """
        try:
            out = await self._client.call_tool(name, args)
        except Exception as exc:  # noqa: BLE001 — see docstring
            logger.warning("tool session call %s failed: %s", name, exc, exc_info=True)
            return {"error": "tool_transport_error", "detail": str(exc)}

        text = next((c.text for c in out.content if getattr(c, "text", None)), None)
        if text is None:
            return {"error": "tool_transport_error", "detail": "no content in tool result"}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": "tool_transport_error", "detail": text[:500]}


@asynccontextmanager
async def tool_session(
    registry: R.ToolRegistry,
    face: list[str],
    *,
    db_factory,
    session_id: str,
    user_id: str | None = None,
    message_id: str | None = None,
):
    """A connected client for one turn. The pair dies with the turn."""
    server = build_mcp_server(
        registry, face, db_factory=db_factory, session_id=session_id,
        user_id=user_id, message_id=message_id,
    )
    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        yield ToolSession(client, listed.tools)
