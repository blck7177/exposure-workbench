"""Clerk session-token verification (V2-A).

Verify a Clerk-issued RS256 session JWT against Clerk's JWKS and check
issuer + authorized-party + expiry. On any failure raise AuthError — never fall
through to a half-authenticated state (fail loud, no fallback). Everything else
about identity (login, OAuth, MFA, sessions, password storage) is Clerk's.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from exposure_workbench.app_state.settings import get_settings


class AuthError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class UserClaims:
    user_id: str
    email: str | None = None


# One JWKS client per issuer url; PyJWKClient caches signing keys internally.
# Kept module-level so tests can monkeypatch `_jwks_client` to return local keys.
_clients: dict[str, PyJWKClient] = {}

# Unknown key ids are a denial-of-service lever, not a caching detail. PyJWKClient
# re-fetches the whole JWK Set whenever a token's `kid` is not in its cache, and
# that fetch is urllib — fully synchronous — so an unauthenticated stranger
# sending tokens with random kids pins the API's single event loop for one Clerk
# round trip per request and hammers Clerk's rate limiter at the same time.
# Measured before this guard: 30 concurrent such requests took a plain
# GET /api/health from 2ms to 1.7s.
#
# So: remember the kids we have already failed to resolve and refuse them without
# touching the network. A legitimate key rotation still gets through, because a
# rotated kid is unseen and is looked up once; only repeats are cheap-rejected.
# The window is short so a genuinely new key is never blocked for long.
_UNKNOWN_KID_TTL_SECONDS = 300
_MAX_REMEMBERED_KIDS = 4096
_unknown_kids: OrderedDict[str, float] = OrderedDict()


def _jwks_client(jwks_url: str) -> PyJWKClient:
    client = _clients.get(jwks_url)
    if client is None:
        client = PyJWKClient(jwks_url)
        _clients[jwks_url] = client
    return client


def _kid_of(token: str) -> str | None:
    try:
        return jwt.get_unverified_header(token).get("kid")
    except Exception:  # noqa: BLE001 — malformed header is its own rejection below
        return None


def _recently_unknown(kid: str | None) -> bool:
    if kid is None:
        return False
    seen_at = _unknown_kids.get(kid)
    if seen_at is None:
        return False
    if time.monotonic() - seen_at > _UNKNOWN_KID_TTL_SECONDS:
        _unknown_kids.pop(kid, None)
        return False
    return True


def _remember_unknown(kid: str | None) -> None:
    if kid is None:
        return
    _unknown_kids[kid] = time.monotonic()
    _unknown_kids.move_to_end(kid)
    while len(_unknown_kids) > _MAX_REMEMBERED_KIDS:
        _unknown_kids.popitem(last=False)


def verify_token(token: str) -> UserClaims:
    """Blocking: it may fetch the JWK Set. Call it off the event loop —
    apps/api/auth_deps.py runs it in a thread for exactly this reason."""
    settings = get_settings()
    issuer = settings.clerk_issuer.rstrip("/")
    if not issuer:
        raise AuthError("clerk_not_configured")
    parties = settings.clerk_authorized_parties_list

    kid = _kid_of(token)
    if _recently_unknown(kid):
        raise AuthError("unknown_kid")

    try:
        signing_key = _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token)
    except Exception as e:  # noqa: BLE001 — network / unknown-kid / malformed all mean "can't verify"
        _remember_unknown(kid)
        raise AuthError(f"jwks_error:{e}")

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("expired")
    except jwt.InvalidIssuerError:
        raise AuthError("bad_issuer")
    except jwt.PyJWTError as e:
        raise AuthError(f"invalid_token:{e}")

    # azp = the frontend origin the token was minted for. When authorized parties
    # are configured, the token must carry one of them (missing azp is rejected).
    if parties and claims.get("azp") not in parties:
        raise AuthError("bad_azp")

    sub = claims.get("sub")
    if not sub:
        raise AuthError("no_sub")
    email = claims.get("email") or claims.get("email_address")
    return UserClaims(user_id=sub, email=email)
