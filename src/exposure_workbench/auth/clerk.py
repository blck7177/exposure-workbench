"""Clerk session-token verification (V2-A).

Verify a Clerk-issued RS256 session JWT against Clerk's JWKS and check
issuer + authorized-party + expiry. On any failure raise AuthError — never fall
through to a half-authenticated state (fail loud, no fallback). Everything else
about identity (login, OAuth, MFA, sessions, password storage) is Clerk's.
"""

from __future__ import annotations

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


def _jwks_client(jwks_url: str) -> PyJWKClient:
    client = _clients.get(jwks_url)
    if client is None:
        client = PyJWKClient(jwks_url)
        _clients[jwks_url] = client
    return client


def verify_token(token: str) -> UserClaims:
    settings = get_settings()
    issuer = settings.clerk_issuer.rstrip("/")
    if not issuer:
        raise AuthError("clerk_not_configured")
    parties = settings.clerk_authorized_parties_list

    try:
        signing_key = _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token)
    except Exception as e:  # noqa: BLE001 — network / unknown-kid / malformed all mean "can't verify"
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
