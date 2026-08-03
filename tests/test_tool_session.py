"""P3 — what the model is shown does not change on the way through (offline).

The loops used to read `registry.schemas(face)` and hand that to the provider.
Now the same list arrives over MCP. If one description, one parameter name or
one required list differs between those two routes, the model's behaviour
changes for a reason nobody wrote down — and the first symptom would be a
regression in answers, not a failing test.

So the conversion is asserted to be byte-identical, not merely equivalent.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents.meta_agent import build_meta_registry
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.tools import faces
from exposure_workbench.workflow.issuer_research_workflow import build_research_registry


def _no_db():
    raise AssertionError("listing tools must not touch the database")


@pytest.mark.parametrize(
    "builder, face",
    [(build_meta_registry, faces.FACE_META_AGENT),
     (build_research_registry, faces.FACE_RESEARCH)],
)
async def test_the_tools_the_model_sees_are_the_registrys_own(builder, face):
    registry = builder()
    before = registry.schemas(faces.resolve(registry, face))

    async with tool_session(registry, face, db_factory=_no_db,
                            session_id="sess_offline_probe") as tools:
        after = tools.tools

    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)


async def test_the_order_survives_the_transport():
    """Order is what a provider's prompt cache keys on, and the face's declared
    order is also the order an auditor reads."""
    registry = build_meta_registry()
    async with tool_session(registry, faces.FACE_META_AGENT, db_factory=_no_db,
                            session_id="sess_offline_probe") as tools:
        assert [t["function"]["name"] for t in tools.tools] == faces.FACE_META_AGENT


async def test_a_transport_failure_is_a_result_not_an_exception():
    """invoke() promises never to raise to the loop, and the loops are written
    to that: a tool failure is something the model reads and adapts to. Adding
    a transport must not add an exception path around it."""
    from exposure_workbench.agents.tool_session import ToolSession

    class _Boom:
        async def call_tool(self, name, args):
            raise RuntimeError("connection died mid-call")

    session = ToolSession(_Boom(), [])
    out = await session.call("get_fact_series", {"ticker": "NVDA"})
    assert out["error"] == "tool_transport_error"
    assert "connection died" in out["detail"]


async def test_a_result_that_is_not_our_json_is_reported_as_one():
    from exposure_workbench.agents.tool_session import ToolSession

    class _Content:
        text = "not json at all"

    class _Result:
        content = [_Content()]

    class _Odd:
        async def call_tool(self, name, args):
            return _Result()

    out = await ToolSession(_Odd(), []).call("think", {"thought": "x"})
    assert out["error"] == "tool_transport_error"
    assert "not json" in out["detail"]
