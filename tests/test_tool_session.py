"""P3/R4 — what the model is shown does not change on the way through (offline).

The loops used to read `registry.schemas(face)` and hand that to the provider.
Since P3 the same list arrives over MCP, and since R4 it arrives from another
process. If one description, one parameter name or one required list differs
between those routes, the model's behaviour changes for a reason nobody wrote
down — and the first symptom would be a regression in answers, not a failing
test. So the conversion is asserted byte-identical, not merely equivalent.

R4 moved the seam, so this file drives the real client: the real mint, the real
Authorization header, the URL this module builds, the real bearer door and the
real stateless transport (tests/mcp_mount.py). Only the socket is stubbed, by an
ASGI app standing in for the compose network — which also lets the mount say
which path it was actually asked for, a thing a real server would answer for
silently.
"""

from __future__ import annotations

import json

import httpx
import pytest

from exposure_workbench.agents import tool_session as tool_session_module
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.internal_token import InternalAuthError, verify
from exposure_workbench.tools import faces
from exposure_workbench.tools.definitions import build_read_registry
from exposure_workbench.tools.meta_tools import register_meta_tools
from exposure_workbench.workflow.issuer_research_workflow import build_research_registry
from tests.mcp_mount import BASE_URL, mounted, use_secret


def build_meta_face_registry():
    """The meta mount's registry, spelled the way apps/mcp/http.py spells it."""
    return register_meta_tools(build_read_registry())


class _Network:
    """The compose network as far as this process is concerned: paths to doors.

    Exact paths only, and it records every request. A mount answers on
    /mcp/<face> and nothing else — R2 used Starlette's Route rather than Mount
    so that a bare path is served instead of redirected — so a client that built
    /mcp/meta/ must fail here rather than be quietly redirected, and the bearer
    it sent has to be visible to be asserted about.
    """

    def __init__(self):
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.doors: dict[str, object] = {}

    async def __call__(self, scope, receive, send) -> None:
        headers = {k.decode(): v.decode() for k, v in scope.get("headers", ())}
        self.requests.append((scope["path"], headers))
        door = self.doors.get(scope["path"])
        if door is None:
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b"no such mount"})
            return
        await door(scope, receive, send)

    @property
    def paths(self) -> list[str]:
        return [path for path, _headers in self.requests]

    def bearer(self) -> str:
        return self.requests[0][1]["authorization"].removeprefix("Bearer ")


@pytest.fixture
def network(monkeypatch):
    """Route the module's own httpx client into this process.

    The one substitution is the transport. The token, the header, the URL and
    the client are all the shipped ones, because they are what this file is
    about — a test that built its own client would assert that the SDK works.
    """
    use_secret(monkeypatch)
    monkeypatch.setattr(get_settings(), "mcp_url", BASE_URL)
    net = _Network()

    class _Loopback:
        """httpx, as tool_session imports it, with the socket taken out."""

        @staticmethod
        def AsyncClient(**kwargs):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=net), **kwargs)

    monkeypatch.setattr(tool_session_module, "httpx", _Loopback)
    return net


@pytest.mark.parametrize(
    "builder, face, face_name",
    [(build_meta_face_registry, faces.FACE_META_AGENT, faces.FACE_NAME_META),
     (build_research_registry, faces.FACE_RESEARCH, faces.FACE_NAME_RESEARCH)],
    ids=["meta", "research"],
)
async def test_the_tools_the_model_sees_are_the_registrys_own(network, builder, face, face_name):
    registry = builder()
    before = registry.schemas(faces.resolve(registry, face))

    async with mounted(registry, face, face_name=face_name) as door:
        network.doors[f"/mcp/{face_name}"] = door
        async with tool_session(face_name, session_id="sess_offline_probe",
                                user_id="user_offline_probe") as tools:
            after = tools.tools

    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)


async def test_the_order_survives_the_transport(network):
    """Order is what a provider's prompt cache keys on, and the face's declared
    order is also the order an auditor reads."""
    async with mounted(build_meta_face_registry(), faces.FACE_META_AGENT,
                       face_name=faces.FACE_NAME_META) as door:
        network.doors["/mcp/meta"] = door
        async with tool_session(faces.FACE_NAME_META, session_id="sess_offline_probe",
                                user_id="user_offline_probe") as tools:
            assert [t["function"]["name"] for t in tools.tools] == faces.FACE_META_AGENT


async def test_the_turns_identity_travels_with_the_request(network):
    """What the loop passes in is what the mount will run as. Everything about
    the tenant now rests on this one header, so it is asserted from the outside:
    the token on the wire, decoded, is this turn."""
    async with mounted(build_meta_face_registry(), faces.FACE_META_AGENT,
                       face_name=faces.FACE_NAME_META) as door:
        network.doors["/mcp/meta"] = door
        async with tool_session(faces.FACE_NAME_META, session_id="sess_7",
                                user_id="user_7", message_id="msg_7",
                                deny=("think",)):
            pass

    claims = verify(network.bearer(), expected_face=faces.FACE_NAME_META)
    assert (claims.user_id, claims.session_id) == ("user_7", "sess_7")
    assert (claims.message_id, claims.deny) == ("msg_7", ("think",))


async def test_the_face_is_a_path_and_the_path_is_exact(network, monkeypatch):
    """No trailing slash and no redirect: R2 mounted each face with Route rather
    than Mount so a bare /mcp/<face> is served, and tool_session rstrips MCP_URL
    because that is the one part of this an operator writes by hand. A redirect
    followed here would send a bearer to somewhere nobody chose."""
    # What a hand-typed MCP_URL looks like. Unstripped it builds //mcp/research,
    # which no route matches and which is reported as a 404 from a server that
    # is up and healthy.
    monkeypatch.setattr(get_settings(), "mcp_url", BASE_URL + "/")

    async with mounted(build_research_registry(), faces.FACE_RESEARCH,
                       face_name=faces.FACE_NAME_RESEARCH) as door:
        network.doors["/mcp/research"] = door
        async with tool_session(faces.FACE_NAME_RESEARCH, session_id="sess_offline_probe",
                                user_id="user_offline_probe"):
            pass

    assert set(network.paths) == {"/mcp/research"}


async def test_an_anonymous_tool_session_cannot_be_opened_at_all(network):
    """user_id used to default to None, and the only caller that ever passed it
    was a test measuring a face rather than a tenant. A token has to name
    somebody, so this fails at the mint — before a connection exists."""
    with pytest.raises(InternalAuthError) as exc:
        async with tool_session(faces.FACE_NAME_META, session_id="sess_1", user_id=None):
            pass

    assert exc.value.reason == "blank_user_id"
    assert network.requests == [], "a request went out for a turn with no identity"


async def test_a_face_that_refuses_the_bearer_ends_the_turn_at_the_caller(network):
    """R4's measured correction, pinned because it is a contract.

    A 401 does not arrive in ToolSession.call. An HTTP-level failure kills the
    stream's task group, so the failure surfaces where the session was opened —
    and that is the right place for it. A 401 is not a tool that failed, it is
    the turn having lost the identity it was minted with; handed to the model as
    a tool result it would invite thirty more attempts against a face it can no
    longer reach, with no second identity to try.

    Provoked here by a mount whose door expects the other face, which is what a
    mistyped MCP_URL looks like from the client side.
    """
    async with mounted(build_meta_face_registry(), faces.FACE_META_AGENT,
                       face_name=faces.FACE_NAME_RESEARCH) as wrong_face_door:
        network.doors["/mcp/meta"] = wrong_face_door
        with pytest.raises(BaseExceptionGroup) as exc:
            async with tool_session(faces.FACE_NAME_META, session_id="sess_1",
                                    user_id="user_1"):
                pass

    refusals = [e for e in exc.value.exceptions if isinstance(e, httpx.HTTPStatusError)]
    assert [e.response.status_code for e in refusals] == [401]


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
