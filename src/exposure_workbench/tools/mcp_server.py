"""The registry's MCP face (M10) — one constructor, every caller.

Registry-driven: list_tools/call_tool dispatch straight to the registry, so the
tools' exact JSON schemas are what a client sees and every call goes through the
same wrapper — argument validation, budget, citation-linked trace — no matter
who is connected.

The server is BUILT, not imported. apps/mcp/server.py used to be a script: a
registry chosen at import time, a face computed at import time, one
process-global session, and the identity of whoever was calling nowhere in the
picture. That shape fits exactly one caller, and there are three — the stdio
debug door, the meta-agent, and the research session — each with its own
registry, face, session and tenant. Those are arguments because they differ per
caller; enforcement is not an argument, because it does not.

This lives in the tool layer rather than under apps/ because the agents connect
to it. Import direction is one-way (apps -> tools -> services), so a face the
agents consume cannot live above them.
"""

from __future__ import annotations

import json

from mcp import types
from mcp.server.lowlevel import Server

from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.tools import faces, registry as R

SERVER_NAME = "exposure-workbench"

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
    # The face scopes what can be CALLED, not only what is listed. Dispatching
    # against the whole registry made the face a description of what the model
    # had been told about: a research session, offered fourteen tools by a
    # registry holding eighteen, could still call read_issuer_brief — the
    # meta-only read that faces.py excludes from that face precisely because
    # citing a previous brief is a loop rather than a source.
    #
    # A view rather than a check, so there is no second place that decides what
    # exists. invoke() answers for a name it does not hold, already, in the same
    # shape and with the same trace row.
    scoped = R.ToolRegistry(tools={name: registry.tools[name] for name in tool_names})
    server = Server(SERVER_NAME, instructions=INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        # Declared order, which is both stable across calls — the 2026-07-28
        # spec asks for that so a consumer keeps its prompt cache — and the
        # order an auditor reads the face in.
        return [
            types.Tool(
                name=scoped.get(name).name,
                description=scoped.get(name).description,
                inputSchema=scoped.get(name).json_schema,
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
            # tenant-less. Set per call rather than inherited from the calling
            # context — a handler runs in whatever task the transport gives it,
            # and a tenant that depends on how a library schedules work is not a
            # tenant mechanism.
            current_user_ctx.set(user_id)
        async with db_factory() as db:
            result = await R.invoke(scoped, db, session_id, name, arguments or {},
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
