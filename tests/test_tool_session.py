"""P3/R4 — what the model is shown does not change on the way through — and S1,
what happens when there is nothing on the other end (offline).

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

The second subject came with S1. A face that cannot be reached was already a
turn over, correctly; what it was not was a turn over with a NAME. It surfaced
as the ExceptionGroup anyio raises when the stream's task group dies, which
reached a chat user as a bare 500 and a research run's error_message as
"unhandled errors in a TaskGroup (1 sub-exception)". The translation and the one
route that catches it are asserted in the same file deliberately: they are two
halves of one contract, and split apart, the day somebody widens the exception
is the day the 503 quietly stops matching it.
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
from fastapi import HTTPException

from apps.api.routes import agent as agent_route
from exposure_workbench.agents import tool_session as tool_session_module
from exposure_workbench.agents.tool_session import ToolFaceUnavailable, tool_session
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.auth.internal_token import InternalAuthError, verify
from exposure_workbench.services import agent_session_service, usage_service
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry, build_research_registry
from tests.mcp_mount import BASE_URL, mounted, use_secret


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


def leaves_of(group: BaseExceptionGroup):
    """Every real exception in a group, at whatever depth.

    Spelled out here rather than borrowed from tool_session: a test that
    inspects a failure with the code under test can only ever confirm that the
    code agrees with itself. The depth varies — a task group whose child is a
    task group raises a group of groups — which is exactly why nothing in this
    file reads a leaf off the top level.
    """
    for exc in group.exceptions:
        yield from leaves_of(exc) if isinstance(exc, BaseExceptionGroup) else (exc,)


async def nothing_listening(scope, receive, send) -> None:
    """A face that is not running, from inside this process.

    ASGITransport calls an app where a socket would be, so an app that raises
    what the socket would have raised IS the refused connection: the same
    httpx.ConnectError, reaching tool_session by the same path, with every layer
    above it the shipped one. It is registered as a door because that is what a
    client finds at an address where nothing is serving.
    """
    raise httpx.ConnectError("[Errno 111] Connection refused")


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
        """httpx, as tool_session imports it, with the socket taken out.

        A stand-in for the module and not for the library: AsyncClient is the
        only name substituted, and everything else — the Timeout, and the
        exception classes the module tests a dead task group's leaves against —
        is delegated to the real httpx. A double carrying its own idea of what a
        ConnectError is would let this file agree with itself while production
        disagreed, which is the one thing a transport test must not do.
        """

        @staticmethod
        def AsyncClient(**kwargs):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=net), **kwargs)

        def __getattr__(self, name):
            return getattr(httpx, name)

    monkeypatch.setattr(tool_session_module, "httpx", _Loopback())
    return net


@pytest.mark.parametrize(
    "builder, face, face_name",
    [(build_meta_registry, faces.FACE_META_AGENT, faces.FACE_NAME_META),
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
    async with mounted(build_meta_registry(), faces.FACE_META_AGENT,
                       face_name=faces.FACE_NAME_META) as door:
        network.doors["/mcp/meta"] = door
        async with tool_session(faces.FACE_NAME_META, session_id="sess_offline_probe",
                                user_id="user_offline_probe") as tools:
            assert [t["function"]["name"] for t in tools.tools] == faces.FACE_META_AGENT


async def test_the_turns_identity_travels_with_the_request(network):
    """What the loop passes in is what the mount will run as. Everything about
    the tenant now rests on this one header, so it is asserted from the outside:
    the token on the wire, decoded, is this turn."""
    async with mounted(build_meta_registry(), faces.FACE_META_AGENT,
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

    S1 changed what arrives there, not where. The refusal is an
    httpx.HTTPStatusError, which is NOT a TransportError but the sibling under
    HTTPError meaning the door answered and said no — a distinction easy enough
    to get wrong that the reason word keeps it visible.

    Provoked here by a mount whose door expects the other face, which is what a
    mistyped MCP_URL looks like from the client side.
    """
    async with mounted(build_meta_registry(), faces.FACE_META_AGENT,
                       face_name=faces.FACE_NAME_RESEARCH) as wrong_face_door:
        network.doors["/mcp/meta"] = wrong_face_door
        with pytest.raises(ToolFaceUnavailable) as exc:
            async with tool_session(faces.FACE_NAME_META, session_id="sess_1",
                                    user_id="user_1"):
                pass

    assert exc.value.reason == "http_401"
    # The group is kept as the cause: the sentence is for the person, the leaf
    # is for whoever reads the traceback after them.
    refusals = [e for e in leaves_of(exc.value.__cause__)
                if isinstance(e, httpx.HTTPStatusError)]
    assert [e.response.status_code for e in refusals] == [401]


async def test_a_face_that_is_not_there_is_a_failure_with_a_name(network):
    """The failure S1 exists for: nothing is listening, so nothing above can be
    told anything useful unless this hop says it.

    The name has to carry the two facts an operator or a user acts on — which
    face, and at which URL — and must not carry the bearer, which is a
    credential and which an error message is the most-copied text in any
    incident."""
    network.doors["/mcp/meta"] = nothing_listening

    with pytest.raises(ToolFaceUnavailable) as exc:
        async with tool_session(faces.FACE_NAME_META, session_id="sess_1",
                                user_id="user_1"):
            pass

    assert exc.value.reason == "connect_error"
    assert exc.value.face_name == faces.FACE_NAME_META
    assert str(exc.value) == (
        f"the meta tool face at {BASE_URL}/mcp/meta could not be reached (connect_error)"
    )
    assert "Bearer" not in str(exc.value) and "eyJ" not in str(exc.value)


async def test_a_face_that_dies_mid_run_arrives_at_the_same_place(network):
    """Why one catch is enough, asserted rather than reasoned about.

    The session opens against a live mount and the face goes away underneath it.
    ToolSession.call does not return a result and does not raise either — its
    await is cancelled by the stream's task group — so the failure comes out of
    the `async with`, exactly where the open-time failure comes out. A second
    catch inside call() would have to invent a tool result for a face that is
    gone, which is the thirty-attempts loop this design refuses.
    """
    async with mounted(build_meta_registry(), faces.FACE_META_AGENT,
                       face_name=faces.FACE_NAME_META) as door:
        network.doors["/mcp/meta"] = door
        with pytest.raises(ToolFaceUnavailable) as exc:
            async with tool_session(faces.FACE_NAME_META, session_id="sess_1",
                                    user_id="user_1") as tools:
                assert tools.tools, "the session must be usable before the face dies"
                network.doors["/mcp/meta"] = nothing_listening
                await tools.call("think", {"thought": "anyone there"})
                pytest.fail("the call returned; a dead face was reported as a tool result")

    assert exc.value.reason == "connect_error"


async def test_an_exception_that_is_not_ours_passes_through_untouched(network):
    """Everything the loops raise passes through this same catch: the provider
    refusing a prompt, a bug in a handler, a bare assertion. Naming one of those
    ToolFaceUnavailable would answer a user 503 for a defect in this repo and
    hide the stack that shows where it is — swallowing an exception you cannot
    name is how a bug becomes a silence, and a group is where one hides.

    It comes back a group and not a RuntimeError, which is what pytest.raises is
    really asserting here — and it comes back nested, because the stream's task
    group wraps whatever the body raised on the way out.
    """
    async with mounted(build_meta_registry(), faces.FACE_META_AGENT,
                       face_name=faces.FACE_NAME_META) as door:
        network.doors["/mcp/meta"] = door
        with pytest.raises(BaseExceptionGroup) as exc:
            async with tool_session(faces.FACE_NAME_META, session_id="sess_1",
                                    user_id="user_1"):
                raise ExceptionGroup("the loop blew up", [ValueError("not a transport failure")])

    assert [type(e).__name__ for e in leaves_of(exc.value)] == ["ValueError"]


def test_a_transport_leaf_nobody_has_met_yet_still_gets_a_word():
    """The reason is httpx's own name for the leaf, not an entry in a table of
    the kinds seen so far. A table has to be extended by whoever first meets the
    kind it is missing, and what it produces until then is a nameless failure —
    which is the whole thing this exception was added to end."""
    reason = tool_session_module._transport_reason
    assert reason(httpx.ConnectError("refused")) == "connect_error"
    assert reason(httpx.ReadTimeout("no answer")) == "read_timeout"
    assert reason(httpx.PoolTimeout("no connection free")) == "pool_timeout"
    assert reason(ValueError("a bug in a tool handler")) is None


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


# ── S1: the one route that catches it ────────────────────────────────────────


class _GateDb:
    """The claim-and-charge transaction, with no database in it.

    `async with factory() as gate_db, gate_db.begin()` is the shape the route
    opens it in, and that shape is the only thing this stands in for: what the
    two statements inside it do is monkeypatched per test.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return self


class _Turn:
    """post_message with the database under it faked and the loop above it
    replaced by one exception.

    The route itself is the shipped function: its real order of gates, its real
    finally, its real except clauses in their real order. A fake stands in only
    for what this file is not asking about — which except clause matches an
    exception escaping handle_message is decided in the source under test.
    """

    STAMP = datetime(2026, 8, 21, 12, 0)

    def __init__(self, monkeypatch):
        self.released: list = []

        async def _get_session(db, session_id):
            return type("_S", (), {"last_prompt_tokens": 0})()

        async def _claim_turn(db, session_id):
            return self.STAMP

        async def _release_turn(session_id, claimed_at=None):
            self.released.append((session_id, claimed_at))

        async def _charge(db, user_id, action):
            return None

        monkeypatch.setattr(agent_route, "get_session_factory", lambda: _GateDb)
        monkeypatch.setattr(agent_session_service, "get_session", _get_session)
        monkeypatch.setattr(agent_session_service, "claim_turn", _claim_turn)
        monkeypatch.setattr(agent_session_service, "release_turn", _release_turn)
        monkeypatch.setattr(usage_service, "charge", _charge)
        self._monkeypatch = monkeypatch

    async def failing_with(self, exc: Exception) -> HTTPException:
        async def _raise(*args, **kwargs):
            raise exc

        self._monkeypatch.setattr(agent_route, "handle_message", _raise)
        with pytest.raises(HTTPException) as caught:
            await agent_route.post_message(
                "sess_1", agent_route.MessageIn(text="what changed at NVDA last quarter"),
                user=UserClaims(user_id="user_1"), db=None,
            )
        return caught.value


@pytest.fixture
def turn(monkeypatch):
    return _Turn(monkeypatch)


async def test_a_chat_turn_that_could_not_reach_its_tools_is_a_503(turn):
    """What the user got before S1 was FastAPI's bare 500, after the daily quota
    for that turn had been charged and committed.

    503 is the honest status: the request was fine and the thing behind it was
    not, which is also the only case where "try again" is real advice rather
    than a suggestion to re-run a bug. The detail names neither the face nor the
    URL — an internal hostname is not the user's business, and tool_session logs
    that line for the operator.
    """
    answer = await turn.failing_with(
        ToolFaceUnavailable(faces.FACE_NAME_META, f"{BASE_URL}/mcp/meta", "connect_error")
    )

    assert answer.status_code == 503
    assert answer.detail["error"] == "tool_face_unavailable"
    assert "not answered" in answer.detail["detail"]
    assert BASE_URL not in json.dumps(answer.detail)


async def test_the_failed_turn_still_frees_the_session(turn):
    """The finally covers this path as it covers every other one, fenced on the
    stamp this turn claimed. Without it the session is locked for a turn lease
    after every unreachable face, so a face that comes back in five seconds
    still costs the user their next message."""
    await turn.failing_with(
        ToolFaceUnavailable(faces.FACE_NAME_META, f"{BASE_URL}/mcp/meta", "connect_error")
    )

    assert turn.released == [("sess_1", _Turn.STAMP)]


async def test_the_413_clause_next_to_it_is_undisturbed(turn):
    """The 503 sits in front of the provider-context handling, which is the
    clause it could most easily eat: both are exceptions escaping the same
    handle_message call, and ToolFaceUnavailable is a RuntimeError, so an except
    ordered the other way round would answer 503 to a prompt that was merely too
    long — and tell the user to try again at the one thing that cannot work."""
    answer = await turn.failing_with(
        RuntimeError("BadRequestError: context_length_exceeded — 200000 tokens")
    )

    assert answer.status_code == 413
    assert answer.detail["error"] == "session_context_exhausted"
