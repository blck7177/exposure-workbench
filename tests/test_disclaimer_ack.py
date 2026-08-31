"""The disclaimer acknowledgement — recorded once, served with /me (V13-S7 §9-②).

The mechanism the column exists for: a record of WHEN a person confirmed, that a
second click cannot move. These tests hold the route to that shape; the live
half (an actual signed-in round trip) is covered by the smoke of the deploy.
"""

from __future__ import annotations

import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _route_src() -> str:
    return (ROOT / "apps" / "api" / "routes" / "me.py").read_text()


def test_the_acknowledgement_keeps_the_first_timestamp():
    """COALESCE(existing, now()) — idempotent, and the record cannot be
    re-stamped. An UPDATE that wrote now() unconditionally would pass every
    happy-path test and quietly turn the record into `last clicked`."""
    src = _route_src()
    body = src[src.index("async def acknowledge_disclaimer"):]
    assert "func.coalesce(" in body and "disclaimer_acknowledged_at, func.now()" in body.replace("\n", " ").replace("            ", " ")


def test_me_serves_the_field_and_the_write_requires_a_user():
    src = _route_src()
    me_body = src[src.index("async def me("):src.index("class PoolOut")]
    assert "disclaimer_acknowledged_at" in me_body, "/me must say whether this person has acknowledged"
    ack = src[src.index('@router.post("/me/acknowledge-disclaimer")'):]
    assert "require_user" in ack[:ack.index("async def") + 400]


def test_the_column_exists_on_the_model_and_in_the_migration():
    """Both halves, so a model column with no migration (or the reverse) is a
    red test rather than a deploy-time surprise."""
    from exposure_workbench.db.models import User
    assert hasattr(User, "disclaimer_acknowledged_at")
    mig = (ROOT / "infra" / "migrations" / "v13_users_ack.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS disclaimer_acknowledged_at" in mig
