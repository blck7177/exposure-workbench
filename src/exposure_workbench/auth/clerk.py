"""Clerk session-token verification (V2-A).

Verify a Clerk-issued RS256 session JWT against Clerk's JWKS and check
issuer + authorized-party + expiry. On any failure raise AuthError — never fall
through to a half-authenticated state (fail loud, no fallback). Everything else
about identity (login, OAuth, MFA, sessions, password storage) is Clerk's.
"""

from __future__ import annotations

import threading
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

# Unknown key ids are a denial-of-service lever, not a caching detail.
# PyJWKClient.get_signing_key re-fetches the entire JWK Set whenever a token's
# `kid` is not in its cache, and that fetch is urllib — fully synchronous. An
# unauthenticated stranger sending tokens with RANDOM kids therefore gets one
# outbound Clerk request per request of their own, and (before this) one blocked
# event loop with it. Measured on the live API: 30 such requests took a plain
# GET /api/health from 2ms to 1.7s, and Clerk's own rate limiter would start
# refusing the JWKS endpoint, breaking sign-in for everyone.
#
# A per-kid negative cache does NOT fix that — every request carries a fresh
# random kid, so every one is a first-time miss. The bound has to be on the
# REFRESH itself: however many unknown kids arrive, we go and ask Clerk at most
# once per cooldown. A genuine key rotation still resolves, within one cooldown,
# for everyone. The per-kid memory below is a cheap short-circuit on top, for the
# repeat case.
_REFRESH_COOLDOWN_SECONDS = 60
_UNKNOWN_KID_TTL_SECONDS = 300
_MAX_REMEMBERED_KIDS = 4096

_last_refresh: dict[str, float] = {}
_refresh_lock = threading.Lock()
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
    except Exception:  # noqa: BLE001 — a malformed header is rejected below anyway
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


def _resolve_signing_key(jwks_url: str, kid: str | None):
    """The cached set first; the network only if a refresh is affordable.

    The lock is acquired non-blockingly on purpose. Under a flood of unknown
    kids, blocking would simply move the queue from the network to the lock and
    still tie up one worker thread per attacker request. A caller that cannot
    take it learns nothing by waiting — whoever holds it is already fetching the
    only answer there is.
    """
    client = _jwks_client(jwks_url)
    key = PyJWKClient.match_kid(client.get_signing_keys(), kid)
    if key is not None:
        return key

    now = time.monotonic()
    last = _last_refresh.get(jwks_url)
    if last is not None and now - last < _REFRESH_COOLDOWN_SECONDS:
        raise AuthError("unknown_kid")
    if not _refresh_lock.acquire(blocking=False):
        raise AuthError("unknown_kid")
    try:
        # re-check under the lock: several threads can pass the cooldown test
        # at once, and only the first should actually go out.
        last = _last_refresh.get(jwks_url)
        if last is not None and time.monotonic() - last < _REFRESH_COOLDOWN_SECONDS:
            raise AuthError("unknown_kid")
        _last_refresh[jwks_url] = time.monotonic()
        key = PyJWKClient.match_kid(client.get_signing_keys(refresh=True), kid)
    finally:
        _refresh_lock.release()

    if key is None:
        raise AuthError("unknown_kid")
    return key


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
        signing_key = _resolve_signing_key(f"{issuer}/.well-known/jwks.json", kid)
    except AuthError:
        _remember_unknown(kid)
        raise
    except Exception as e:  # noqa: BLE001 — network / malformed both mean "can't verify"
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
