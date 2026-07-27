"""Mint a Clerk session JWT without a browser — for live acceptance runs.

    python scripts/mint_clerk_token.py [email-local-part]

Creates (or reuses) a Clerk user on the configured instance, opens a session for
it, and prints a session token to stdout. That token is what a real browser would
send, with ONE difference: tokens minted through the Backend API carry no `azp`
claim, and auth/clerk.py rejects a missing azp whenever CLERK_AUTHORIZED_PARTIES
is set. So a run that uses this script must temporarily blank that setting:

    # in .env
    CLERK_AUTHORIZED_PARTIES=
    docker compose up -d --force-recreate exposure-api
    ... run the acceptance ...
    # restore the real value and recreate again — an empty authorized-parties
    # list in production would accept a token minted for any other origin.

Requires CLERK_SECRET_KEY in .env. Never commit a printed token; they are
short-lived but they are bearer credentials.
"""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

API = "https://api.clerk.com/v1"
SECRET = os.getenv("CLERK_SECRET_KEY", "")


def _headers() -> dict[str, str]:
    if not SECRET:
        raise SystemExit("CLERK_SECRET_KEY is not set in .env")
    return {"Authorization": f"Bearer {SECRET}", "Content-Type": "application/json"}


def get_or_create_user(client: httpx.Client, email: str) -> str:
    found = client.get(f"{API}/users", params={"email_address": [email]}, headers=_headers())
    found.raise_for_status()
    rows = found.json()
    if rows:
        return rows[0]["id"]

    # This instance requires username AND password on top of the email; asking
    # Clerk (422 body names the missing params) beats guessing.
    made = client.post(
        f"{API}/users",
        headers=_headers(),
        json={
            "email_address": [email],
            "username": local_part(email).replace("+", "_").replace("-", "_"),
            # exists only for automated acceptance runs on the dev instance
            "password": "ew-live-acceptance-" + local_part(email) + "-2026!",
            "skip_password_checks": True,
        },
    )
    made.raise_for_status()
    return made.json()["id"]


def local_part(email: str) -> str:
    return email.split("@", 1)[0]


def mint(client: httpx.Client, user_id: str) -> str:
    session = client.post(f"{API}/sessions", headers=_headers(), json={"user_id": user_id})
    session.raise_for_status()
    sid = session.json()["id"]
    token = client.post(f"{API}/sessions/{sid}/tokens", headers=_headers(), json={})
    token.raise_for_status()
    return token.json()["jwt"]


def main() -> None:
    local = sys.argv[1] if len(sys.argv) > 1 else "acceptance-a"
    # Clerk rejects reserved TLDs like .test, and dev instances treat a
    # +clerk_test address as a fixture account that skips email verification.
    email = f"{local}+clerk_test@example.com"
    with httpx.Client(timeout=30) as client:
        user_id = get_or_create_user(client, email)
        print(f"# user_id={user_id} email={email}", file=sys.stderr)
        print(mint(client, user_id))


if __name__ == "__main__":
    main()
