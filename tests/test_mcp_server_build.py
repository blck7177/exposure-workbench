"""P2 — one constructor builds the server, whoever is connecting (offline).

The module used to be a script: a registry chosen at import, a face computed at
import, one process-global session, and the identity of whoever was calling
nowhere in the picture. That shape only ever fits one caller, and this project
has three coming — the stdio debug door, the meta-agent, and the research
session, each with its own registry, face, session and tenant.

So the server is built, not imported. What is asserted here is the part a
consumer depends on: the face it is given is the face it serves, in a stable
order, with the registry's own schemas.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.tools import faces
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.meta_tools import register_meta_tools


def _never_called():
    raise AssertionError("listing tools must not touch the database")


def _build(face=None):
    from exposure_workbench.tools.mcp_server import build_mcp_server

    registry = register_meta_tools(build_read_registry())
    return build_mcp_server(
        registry, face or faces.FACE_META_AGENT,
        db_factory=_never_called, session_id="sess_offline_probe",
    )


async def _list(server):
    """The registered list_tools handler, called the way the SDK calls it."""
    from mcp import types

    handler = server.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest(method="tools/list"))
    return result.root.tools


async def test_the_face_it_is_given_is_the_face_it_serves():
    tools = await _list(_build())
    assert [t.name for t in tools] == faces.FACE_META_AGENT


async def test_a_narrower_face_is_served_narrowly():
    """Face trimming is how skip-flags work: the capability does not exist for
    that session rather than being refused inside the tool."""
    tools = await _list(_build(faces.READ_CORE))
    assert [t.name for t in tools] == faces.READ_CORE
    assert "start_issuer_research" not in {t.name for t in tools}


async def test_the_order_is_stable_across_calls():
    """A list that reshuffles costs the consumer its prompt cache for nothing;
    the 2026-07-28 spec asks servers for a deterministic order for exactly this.
    Declared order is that order — it is also the order an auditor reads.
    """
    first = [t.name for t in await _list(_build())]
    second = [t.name for t in await _list(_build())]
    assert first == second == faces.FACE_META_AGENT


async def test_the_schemas_are_the_registrys_own():
    """build_http_app() published every tool as taking one string called kwargs,
    because FastMCP inferred schemas from a **kwargs handler. A transport that
    describes the tools differently from the registry is a second source of
    truth about what an argument is."""
    registry = register_meta_tools(build_read_registry())
    tools = await _list(_build())

    for tool in tools:
        assert tool.inputSchema == registry.get(tool.name).json_schema
        assert tool.description == registry.get(tool.name).description
    assert "kwargs" not in json.dumps([t.inputSchema for t in tools])


async def test_a_face_the_registry_cannot_satisfy_never_builds():
    with pytest.raises(faces.FaceNotRegistered):
        from exposure_workbench.tools.mcp_server import build_mcp_server

        build_mcp_server(build_read_registry(), faces.FACE_META_AGENT,
                         db_factory=_never_called, session_id="sess_offline_probe")


async def test_the_server_carries_its_instructions():
    """Sent at initialize, so the discipline reaches a consumer that has never
    read this repo's system prompts."""
    server = _build()
    assert server.instructions
    assert "cite" in server.instructions.lower()


def test_the_transport_does_not_validate_arguments_itself():
    """The SDK's call_tool decorator validates against inputSchema by default and
    returns a flat 'Input validation error: ...' string for the FIRST failure.

    That would preempt the gate: the rejection would carry one problem instead
    of all of them, and — because it never reaches invoke() — would leave no
    trace step at all. The single enforcement point has to stay single, so the
    flag is off, and this test is here because the default is on.
    """
    import inspect

    from exposure_workbench.tools import mcp_server as mod

    source = inspect.getsource(mod.build_mcp_server)
    assert "validate_input=False" in source
