"""Clerk token verification + auth-dependency gating (offline).

Signs tokens with a local RS256 keypair and monkeypatches the JWKS client to
return the matching public key, so the full verify path runs with no network and
no real Clerk instance. Covers the four token classes the plan names
(valid / expired / bad issuer / bad azp) plus the no-token gate behaviour.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.api import auth_deps
from exposure_workbench.auth import clerk

ISS = "https://test-instance.clerk.accounts.dev"
AZP = "http://localhost:3103"


@dataclass
class _FakeSettings:
    clerk_issuer: str = ISS
    clerk_authorized_parties: str = AZP

    @property
    def clerk_authorized_parties_list(self) -> list[str]:
        return [p.strip() for p in self.clerk_authorized_parties.split(",") if p.strip()]


@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def _patch_clerk(monkeypatch, keypair):
    monkeypatch.setattr(clerk, "get_settings", lambda: _FakeSettings())
    pub = keypair.public_key()

    class _FakeSigningKey:
        key = pub

    class _FakeJWKS:
        def get_signing_key_from_jwt(self, token):  # noqa: ARG002
            return _FakeSigningKey()

    monkeypatch.setattr(clerk, "_jwks_client", lambda url: _FakeJWKS())


def _sign(keypair, **overrides) -> str:
    now = int(time.time())
    claims = {"sub": "user_abc", "iss": ISS, "azp": AZP, "iat": now, "exp": now + 3600}
    claims.update(overrides)
    return jwt.encode(claims, keypair, algorithm="RS256")


# ── verify_token: the four token classes ──────────────────────────────────────

def test_valid_token(keypair):
    claims = clerk.verify_token(_sign(keypair, email="a@b.com"))
    assert claims.user_id == "user_abc"
    assert claims.email == "a@b.com"


def test_expired_token(keypair):
    now = int(time.time())
    with pytest.raises(clerk.AuthError) as e:
        clerk.verify_token(_sign(keypair, iat=now - 7200, exp=now - 3600))
    assert e.value.reason == "expired"


def test_bad_issuer(keypair):
    with pytest.raises(clerk.AuthError) as e:
        clerk.verify_token(_sign(keypair, iss="https://evil.example.com"))
    assert e.value.reason == "bad_issuer"


def test_bad_azp(keypair):
    with pytest.raises(clerk.AuthError) as e:
        clerk.verify_token(_sign(keypair, azp="http://evil.example.com"))
    assert e.value.reason == "bad_azp"


def test_missing_azp_rejected_when_parties_configured(keypair):
    # a token with no azp cannot satisfy configured authorized parties
    tok = jwt.encode(
        {"sub": "u", "iss": ISS, "iat": int(time.time()), "exp": int(time.time()) + 3600},
        keypair, algorithm="RS256",
    )
    with pytest.raises(clerk.AuthError) as e:
        clerk.verify_token(tok)
    assert e.value.reason == "bad_azp"


def test_not_configured_raises(keypair, monkeypatch):
    monkeypatch.setattr(clerk, "get_settings", lambda: _FakeSettings(clerk_issuer=""))
    with pytest.raises(clerk.AuthError) as e:
        clerk.verify_token(_sign(keypair))
    assert e.value.reason == "clerk_not_configured"


def test_algorithm_is_pinned_to_rs256(keypair):
    """Lock in RS256 pinning: a token signed HS256 with the PUBLIC key as the HMAC
    secret (the classic alg-confusion attack) must NOT verify. Forged by hand
    because pyjwt's own encode() refuses to make it — the decode side is what we
    are testing, and verify_token passes algorithms=['RS256']."""
    import base64
    import hashlib
    import hmac
    import json

    from cryptography.hazmat.primitives import serialization

    pub_pem = keypair.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    def b64(d: bytes) -> bytes:
        return base64.urlsafe_b64encode(d).rstrip(b"=")

    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"sub": "attacker", "iss": ISS, "azp": AZP,
                              "iat": now, "exp": now + 3600}).encode())
    signing_input = header + b"." + payload
    sig = b64(hmac.new(pub_pem, signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + sig).decode()

    with pytest.raises(clerk.AuthError):
        clerk.verify_token(forged)


# ── bearer parsing ────────────────────────────────────────────────────────────

def test_bearer_extraction():
    assert auth_deps._bearer("Bearer abc.def.ghi") == "abc.def.ghi"
    assert auth_deps._bearer("bearer xyz") == "xyz"
    assert auth_deps._bearer("Basic abc") is None
    assert auth_deps._bearer(None) is None
    assert auth_deps._bearer("Bearer ") is None


# ── dependency gating (no DB touched on these paths) ──────────────────────────

async def test_require_user_no_token_401():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        await auth_deps.require_user(authorization=None, db=None)
    assert e.value.status_code == 401
    assert e.value.detail["error"] == "unauthenticated"


async def test_require_user_bad_token_401(keypair):
    from fastapi import HTTPException
    now = int(time.time())
    expired = _sign(keypair, iat=now - 7200, exp=now - 3600)
    with pytest.raises(HTTPException) as e:
        await auth_deps.require_user(authorization=f"Bearer {expired}", db=None)
    assert e.value.status_code == 401
    assert e.value.detail["reason"] == "expired"


async def test_optional_user_no_token_returns_none():
    assert await auth_deps.optional_user(authorization=None, db=None) is None


async def test_optional_user_bad_token_returns_none(keypair):
    now = int(time.time())
    expired = _sign(keypair, iat=now - 7200, exp=now - 3600)
    assert await auth_deps.optional_user(authorization=f"Bearer {expired}", db=None) is None
