"""R1/N7 — the door: nothing reaches a face without a verified identity (offline).

At the ASGI level, with a stub inner app that records what it saw. Two things
are being asserted and only one of them is the 401: a rejected request must not
merely fail, it must never run the inner app at all. The mount behind this door
is the entire tool surface — every registry tool and the database behind them —
so "reached the transport and was refused later" is a different system from
"was never let in".

The good-path assertion is the other half of the trade MCP_PLAN §4 describes.
The inner app sees the claims AND auth.context.current_user_ctx, because the
tenant GUC is set from that second one by db/session.py's listener, one layer
below anything that knows what MCP is.

Whether the binding survives the REAL transport's task scheduling is a
different question and a stub cannot answer it — test_mcp_identity_binding does.
"""

from __future__ import annotations

import json

import pytest

from apps.mcp.middleware import bearer_identity
from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.auth.internal_token import mint
from exposure_workbench.tools import faces, mcp_request
from tests.mcp_mount import use_secret

FACE = faces.FACE_NAME_META


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    use_secret(monkeypatch)


class _Inner:
    """The face, as far as the door is concerned: a thing that records the
    identity it was run under, and how many times it ran."""

    def __init__(self, raises: Exception | None = None):
        self.calls: list[dict] = []
        self._raises = raises

    async def __call__(self, scope, receive, send) -> None:
        self.calls.append({
            "type": scope["type"],
            "claims": mcp_request.current_mcp_request.get(),
            "tenant": current_user_ctx.get(),
        })
        if self._raises is not None:
            raise self._raises
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"served": true}'})


def _scope(headers: list[tuple[bytes, bytes]] | None = None, scope_type: str = "http") -> dict:
    return {
        "type": scope_type, "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": f"/mcp/{FACE}", "raw_path": None,
        "query_string": b"", "root_path": "", "headers": headers or [],
        "client": ("127.0.0.1", 51000), "server": ("exposure-mcp", 8000),
    }


async def _receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _drive(door, scope) -> list[dict]:
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    await door(scope, _receive, send)
    return sent


def _response(sent: list[dict]) -> tuple[int, dict]:
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(body)


def _bearer(**identity) -> list[tuple[bytes, bytes]]:
    token = mint(face=FACE, **{"user_id": "user_a", "session_id": "sess_a", **identity})
    return [(b"authorization", f"Bearer {token}".encode())]


@pytest.mark.parametrize("headers, reason", [
    ([], "no_authorization"),
    ([(b"authorization", b"Basic dXNlcjpwdw==")], "bad_scheme"),
    ([(b"authorization", b"Bearer    ")], "empty_bearer"),
    ([(b"authorization", b"Bearer not.a.token")], "invalid_token"),
], ids=["no header", "another scheme", "an empty bearer", "an unverifiable token"])
async def test_a_request_without_a_good_bearer_never_reaches_the_face(headers, reason):
    inner = _Inner()
    sent = await _drive(bearer_identity(inner, expected_face=FACE), _scope(headers))

    status, body = _response(sent)
    assert status == 401
    assert body["error"] == "unauthenticated"
    assert body["reason"].startswith(reason)
    assert inner.calls == [], "the face ran for a request that was not authenticated"


async def test_a_token_for_the_other_mount_is_refused_by_this_one():
    """N9's two locks are two: the path chose the face, and the claim has to
    agree with it. This is the one a mistyped MCP_URL produces."""
    inner = _Inner()
    token = mint(user_id="user_a", session_id="sess_a", face=faces.FACE_NAME_RESEARCH)
    sent = await _drive(bearer_identity(inner, expected_face=faces.FACE_NAME_META),
                        _scope([(b"authorization", f"Bearer {token}".encode())]))

    status, body = _response(sent)
    assert (status, body["reason"]) == (401, "face_mismatch:token=research")
    assert inner.calls == []


async def test_a_verified_request_runs_the_face_under_its_own_identity():
    """Two requests, two identities, one door — because one request cannot tell
    a bound identity from a hardcoded one. Sequential is enough here: what is
    under test is that the door reads each token, and the harder question of
    whether the binding survives a real transport's scheduling belongs to
    test_mcp_identity_binding."""
    inner = _Inner()
    door = bearer_identity(inner, expected_face=FACE)

    first = await _drive(door, _scope(_bearer(user_id="user_a", session_id="sess_a",
                                              message_id="msg_1", deny=["think"])))
    await _drive(door, _scope(_bearer(user_id="user_b", session_id="sess_b")))

    assert _response(first) == (200, {"served": True})
    claims = inner.calls[0]["claims"]
    assert (claims.user_id, claims.session_id, claims.message_id) == ("user_a", "sess_a", "msg_1")
    assert (claims.face, claims.deny) == (FACE, ("think",))

    second = inner.calls[1]["claims"]
    assert (second.user_id, second.session_id) == ("user_b", "sess_b")
    assert (second.message_id, second.deny) == (None, ())

    # The tenant the database will scope to, set here rather than by anything
    # that knows what MCP is: db/session.py's listener reads this contextvar
    # when a transaction begins. Both, so no single value satisfies it.
    assert [c["tenant"] for c in inner.calls] == ["user_a", "user_b"]


async def test_a_request_that_is_not_http_passes_through_untouched():
    """The lifespan scope carries no Authorization header and has nothing to
    refuse with. An unconditional 401 here would send an http.response.start
    into a lifespan — a protocol error — and take the container down before it
    served a single request."""
    inner = _Inner()
    sent = await _drive(bearer_identity(inner, expected_face=FACE),
                        _scope(scope_type="lifespan"))

    assert [c["type"] for c in inner.calls] == ["lifespan"]
    assert sent == [], "the door answered a scope that has no response"
    assert inner.calls[0]["claims"] is None, "a lifespan has no identity to bind"


async def test_nothing_is_left_bound_when_the_request_is_over():
    """A resident server outlives every request in it. A claims envelope left
    bound is the next request's identity if that one is ever served in this
    task, which is exactly the class of error residency introduced."""
    inner = _Inner()
    await _drive(bearer_identity(inner, expected_face=FACE), _scope(_bearer()))

    assert mcp_request.current_mcp_request.get() is None
    assert current_user_ctx.get() is None


async def test_nothing_is_left_bound_when_the_face_raises():
    """The reset has to be in a finally, and a tool face is exactly the kind of
    thing that raises."""
    inner = _Inner(raises=RuntimeError("the transport blew up"))

    with pytest.raises(RuntimeError):
        await _drive(bearer_identity(inner, expected_face=FACE), _scope(_bearer()))

    assert mcp_request.current_mcp_request.get() is None
    assert current_user_ctx.get() is None
