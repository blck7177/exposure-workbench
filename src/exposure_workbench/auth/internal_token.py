"""The internal bearer between an agent loop and the resident tool server (MCP_PLAN R1/N7).

Not a user credential and not an authorization boundary: the api and the worker
already know whose work they are doing, and this is how they carry that knowledge
across the one process hop that R4 introduces. HS256 with a shared secret is
right for exactly that reason — both ends are this repo, deployed together, and
an asymmetric key would buy a distinction (who may mint vs who may verify) that
does not exist here. The outward-facing boundary is B2, still sealed; nothing in
this module is a step toward it, and no token minted here is ever forwarded to
an upstream.

Six claims, no more: sub (user), sid (agent session), face, deny, iat, exp, plus
mid when a turn has a message. A token is not a place to stash context — every
claim added here becomes something the verifier must decide about, and something
a reader of a captured token learns.

deny is the skip-flag channel and it NARROWS only. The mount decides which face
it serves; deny removes names from that face for one request, so a research run
started with skip_external_research reaches a face that physically lacks
search_external_research rather than a tool that checks a flag and refuses. This
module carries the list and proves it is a list of strings; applying it is the
mount's job (R2), because only the mount knows what the face contains.

InternalAuthError deliberately does not reuse auth/clerk.py's AuthError. A Clerk
token failing and an internal bearer failing are different boundaries with
different operators and different fixes — one is a signed-out browser, the other
is a misconfigured compose file — and one exception type would make them one line
in the logs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import jwt

from exposure_workbench.app_state.settings import get_settings

_ALGORITHM = "HS256"

# Clock skew allowance. Both ends run on the same host today, so this is slack
# against a container's clock stepping, not against a real time difference.
_LEEWAY_SECONDS = 60

# Absent, not merely falsy: pyjwt raises MissingRequiredClaimError before any
# value check runs, which is what turns "a token minted by something that is not
# mint()" into a rejection rather than a KeyError deeper in.
_REQUIRED_CLAIMS = ["exp", "iat", "sub", "sid", "face"]


class InternalAuthError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class InternalClaims:
    """One request's whole identity envelope, as the tool server will serve it."""

    user_id: str
    session_id: str
    face: str
    message_id: str | None = None
    deny: tuple[str, ...] = ()


def require_secret() -> str:
    """The signing key, or a raise naming what to set.

    Public because the entrypoints call it at startup, before they serve or mint
    anything: .env.example promises that an empty MCP_INTERNAL_SECRET stops the
    api, the worker and the mcp container from coming up at all, and a second
    copy of that test somewhere else is a second place that could disagree about
    what "configured" means.
    """
    secret = get_settings().mcp_internal_secret
    if not secret:
        raise InternalAuthError(
            "mcp_internal_secret_unset: set MCP_INTERNAL_SECRET to the same value on "
            "api, worker and exposure-mcp"
        )
    return secret


def _text(value, field: str) -> str:
    """A required identifier, or a raise naming which one was blank.

    Checked at mint rather than only at verify: a token minted with an empty sub
    is a 401 half an hour later, in another container, attributed to whatever
    request happened to spend it. Here it is attributed to the caller that had
    nothing to put in it.
    """
    if not isinstance(value, str) or not value.strip():
        raise InternalAuthError(f"blank_{field}")
    return value.strip()


def mint(
    *,
    user_id: str,
    session_id: str,
    face: str,
    message_id: str | None = None,
    deny: Sequence[str] = (),
) -> str:
    secret = require_secret()
    now = int(time.time())
    payload = {
        "sub": _text(user_id, "user_id"),
        "sid": _text(session_id, "session_id"),
        "face": _text(face, "face"),
        "deny": [_text(name, "deny_entry") for name in deny],
        "iat": now,
        "exp": now + get_settings().mcp_token_ttl_seconds,
    }
    if message_id is not None:
        payload["mid"] = _text(message_id, "message_id")
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def verify(token: str, *, expected_face: str) -> InternalClaims:
    """The claims, or a raise carrying the reason a caller may put in a 401.

    algorithms is a one-element list on purpose. Anything wider is the alg
    confusion family — a list containing "none" accepts unsigned tokens outright,
    and a list mixing HS with RS lets a token signed with a public key verify
    against it as an HMAC secret.
    """
    secret = require_secret()
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            options={"require": _REQUIRED_CLAIMS},
            leeway=_LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError:
        raise InternalAuthError("expired")
    except jwt.MissingRequiredClaimError as e:
        raise InternalAuthError(f"missing_claim:{e.claim}")
    except jwt.PyJWTError as e:
        raise InternalAuthError(f"invalid_token:{e}")

    # require= only proves the claims are present. Present-and-empty passes it,
    # and an empty sub is an anonymous tool call with a valid signature on it.
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise InternalAuthError("no_sub")
    sid = claims.get("sid")
    if not isinstance(sid, str) or not sid:
        raise InternalAuthError("no_sid")
    face = claims.get("face")
    if not isinstance(face, str) or not face:
        raise InternalAuthError("no_face")

    # The second lock. The mount has already decided which face it serves, so
    # this can only fire when the two disagree — a token minted for the research
    # face arriving at the meta mount, which is what a mistyped MCP_URL or a
    # swapped mount table looks like from in here. Without it that request would
    # be served the meta face under a research run's identity and nothing would
    # say so.
    if face != expected_face:
        raise InternalAuthError(f"face_mismatch:token={face}")

    mid = claims.get("mid")
    if mid is not None and (not isinstance(mid, str) or not mid):
        raise InternalAuthError("bad_mid")

    # mint() always writes deny, so a signed token without it was produced by
    # something else. Reading absence as "nothing denied" would let such a token
    # buy back the exact tool a skip flag was set to remove.
    deny = claims.get("deny")
    if not isinstance(deny, list) or not all(isinstance(n, str) and n for n in deny):
        raise InternalAuthError("bad_deny")

    return InternalClaims(
        user_id=sub, session_id=sid, face=face, message_id=mid, deny=tuple(deny)
    )
