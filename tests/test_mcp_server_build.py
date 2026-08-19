"""P2/R2 — one constructor per MOUNT, one identity per REQUEST (offline).

The module used to be a script: a registry chosen at import, a face computed at
import, one process-global session, and the identity of whoever was calling
nowhere in the picture. Making it a constructor answered half of that — registry,
face and db_factory differ per face, so they became arguments.

R2 answered the other half by taking three arguments AWAY. A server that
outlives every turn in it serves every tenant this desk has, so session, user and
message cannot be properties of the object; they arrive per request, verified at
the door and read out of tools/mcp_request.py. What is asserted here is what a
consumer depends on: the face it is given is the face it serves, in a stable
order, with the registry's own schemas — and that identity is nowhere in the
constructor's signature.

That the binding survives the real transport into the handler is a different
claim and this file cannot make it; test_mcp_identity_binding does.
"""

from __future__ import annotations

import inspect
import json
from contextlib import contextmanager

import pytest

from exposure_workbench.auth.internal_token import InternalClaims
from exposure_workbench.tools import faces, mcp_request
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.meta_tools import register_meta_tools


def _never_called():
    raise AssertionError("listing tools must not touch the database")


def _build(face=None, face_name=faces.FACE_NAME_META):
    from exposure_workbench.tools.mcp_server import build_mcp_server

    registry = register_meta_tools(build_read_registry())
    return build_mcp_server(
        registry, face or faces.FACE_META_AGENT,
        db_factory=_never_called, face_name=face_name,
    )


@contextmanager
def _as(user_id="user_offline_probe", session_id="sess_offline_probe", deny=()):
    """One request's claims, bound the way the door binds them.

    A test that skipped this would be testing a state the server refuses to run
    in — current() raises rather than returning None, because a handler with no
    verified request behind it is the pre-P1.3 anonymous door.
    """
    token = mcp_request.bind(InternalClaims(
        user_id=user_id, session_id=session_id, face=faces.FACE_NAME_META, deny=tuple(deny),
    ))
    try:
        yield
    finally:
        mcp_request.current_mcp_request.reset(token)


async def _list(server, deny=()):
    """The registered list_tools handler, called the way the SDK calls it."""
    from mcp import types

    handler = server.request_handlers[types.ListToolsRequest]
    with _as(deny=deny):
        result = await handler(types.ListToolsRequest(method="tools/list"))
    return result.root.tools


async def test_the_face_it_is_given_is_the_face_it_serves():
    tools = await _list(_build())
    assert [t.name for t in tools] == faces.FACE_META_AGENT


async def test_a_narrower_face_is_served_narrowly():
    """A face is what a mount serves. The other narrowing — a skip flag — is per
    request now and rides in the token; both end at the same view, and
    test_mcp_face_scope drives that one through the door."""
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
                         db_factory=_never_called, face_name=faces.FACE_NAME_META)


def test_the_constructor_cannot_be_handed_an_identity():
    """The R2 property, stated as an absence.

    While user_id, session_id and message_id were parameters, a server was a
    tenant's server and residency was impossible. Re-adding any of them would
    not break a single assertion above — every face would still be served
    correctly — so the signature itself is what is pinned. db_factory stays a
    parameter because which database a face reaches is a property of the mount,
    not of a request.
    """
    from exposure_workbench.tools.mcp_server import build_mcp_server

    parameters = inspect.signature(build_mcp_server).parameters
    assert list(parameters) == ["registry", "face", "db_factory", "face_name"]


async def test_each_mount_introduces_itself_by_its_face():
    """Both faces are resident in one process. Two servers introducing
    themselves identically at initialize would leave a captured handshake, a
    client log line and a future second replica unable to say which one
    answered."""
    meta = _build(face_name=faces.FACE_NAME_META)
    research = _build(face_name=faces.FACE_NAME_RESEARCH)

    assert meta.name == "exposure-workbench-meta"
    assert research.name == "exposure-workbench-research"


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
    from exposure_workbench.tools import mcp_server as mod

    source = inspect.getsource(mod.build_mcp_server)
    assert "validate_input=False" in source
