"""The identity the resident tool server is serving under, right now (MCP_PLAN R1).

Until R1 the tool server got its identity as constructor arguments: a server was
built per turn, so user, session and message were fixed before a single request
existed and could not be wrong. Residency trades that away — one long-lived
server, many callers — and this contextvar is what it is traded for. The
middleware verifies the bearer and binds here; the call_tool handler reads here;
there is no third way to learn who is calling.

current() raises when nothing is bound. A handler that reached a tool with no
verified request behind it is a transport wiring bug, and the shape of that bug
is already on record: before P1.3 the stdio door ran every call under one
process-global session with owner_id=None, so the trace could not say whose work
it was and RLS had no tenant to scope to. Returning None here would let that
state reappear as a caller's `or "anonymous"`. There is nothing to serve, so it
is not served.

Three request-scoped variables, deliberately not merged:
  auth.context.current_user_ctx — the DB tenant, read by the session listener
    when a transaction begins. Set from these claims, but consumed by a layer
    that must know nothing about MCP.
  tools.registry._session_ctx — the agent session id, so calc primitives stamp
    calc_ledger.invoked_by.
  this — the whole envelope the request arrived with, including face and deny,
    which neither of the other two has any business carrying.
"""

from __future__ import annotations

import contextvars

from exposure_workbench.auth.internal_token import InternalClaims

current_mcp_request: contextvars.ContextVar[InternalClaims | None] = contextvars.ContextVar(
    "current_mcp_request", default=None
)


class NoMcpRequestBound(RuntimeError):
    """A tool handler ran with no verified request bound to it."""


def bind(claims: InternalClaims) -> contextvars.Token:
    """Bind for the duration of one request. The caller resets the returned
    Token in a finally — a resident server outlives every request in it."""
    return current_mcp_request.set(claims)


def current() -> InternalClaims:
    claims = current_mcp_request.get()
    if claims is None:
        raise NoMcpRequestBound(
            "no verified MCP request is bound: a tool handler was reached without the "
            "bearer middleware having run in the same task. Mount the face behind "
            "apps.mcp.middleware.bearer_identity."
        )
    return claims
