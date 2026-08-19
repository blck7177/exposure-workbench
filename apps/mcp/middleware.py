"""The door of the resident tool server (MCP_PLAN R1/N7).

One middleware per mount, wrapping one face. It is the only place in the system
that decodes an internal bearer: everything downstream reads the bound claims and
never sees the token, which is also why the token is never forwarded anywhere.

A request without a valid bearer does not reach the inner app at all. There is no
anonymous face to degrade to — the mount serves tools that read a tenant's
filings and spend a tenant's budget, and "which tenant" is precisely what the
bearer answers.
"""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse

from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.auth.internal_token import InternalAuthError, verify
from exposure_workbench.tools import mcp_request

logger = logging.getLogger(__name__)


def _bearer(scope) -> str:
    """The token, or a raise with the reason it is not there.

    ASGI servers lower-case header names, and a header the caller omitted, sent
    under another scheme, or sent empty are three distinct operator mistakes, so
    they get three distinct reasons rather than one "unauthenticated".
    """
    for name, value in scope.get("headers", ()):
        if name != b"authorization":
            continue
        scheme, _, token = value.decode("latin-1").partition(" ")
        if scheme.lower() != "bearer":
            raise InternalAuthError("bad_scheme")
        if not token.strip():
            raise InternalAuthError("empty_bearer")
        return token.strip()
    raise InternalAuthError("no_authorization")


def bearer_identity(app, *, expected_face: str):
    """Wrap `app` so it only ever runs with a verified identity bound.

    expected_face is the mount's own name (faces.FACE_NAME_META /
    FACE_NAME_RESEARCH), handed to verify() as the second lock on top of the
    signature.
    """

    async def middleware(scope, receive, send) -> None:
        # A lifespan scope carries no Authorization header and has no response to
        # refuse with — sending an http.response.start into it is a protocol
        # error, so an unconditional 401 here would take the server down before
        # it ever served a request.
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        try:
            claims = verify(_bearer(scope), expected_face=expected_face)
        except InternalAuthError as e:
            logger.warning(
                "mcp bearer rejected on face=%s path=%s: %s",
                expected_face, scope.get("path"), e.reason,
            )
            await JSONResponse(
                {"error": "unauthenticated", "reason": e.reason}, status_code=401
            )(scope, receive, send)
            return

        # Bound here and awaited here, in this task. This is a pure ASGI callable
        # rather than a BaseHTTPMiddleware subclass for exactly that:
        # BaseHTTPMiddleware runs the downstream app in a task of its own, and a
        # contextvar set in this frame would or would not be visible to the tool
        # handler depending on how anyio happened to spawn it. The whole design
        # rests on the handler seeing these claims, so it cannot rest on
        # scheduling. Stateless transports build their session inside this call,
        # which keeps the chain unbroken all the way down.
        request_token = mcp_request.bind(claims)
        user_token = current_user_ctx.set(claims.user_id)
        try:
            await app(scope, receive, send)
        finally:
            mcp_request.current_mcp_request.reset(request_token)
            current_user_ctx.reset(user_token)

    return middleware
