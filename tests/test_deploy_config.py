"""V2-F — deployment configuration guards (offline: no DB, no network).

Every failure this file guards against is SILENT. A same-origin build that
quietly bakes localhost still builds, still starts, still passes a server-side
health check, and is broken for every visitor. A container published on 0.0.0.0
looks identical to one published on loopback until someone scans the host. There
is no runtime assertion that can catch either, so these read the configuration
files the way the deploy does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTTP_TS = ROOT / "apps" / "web" / "lib" / "http.ts"
DOCKERFILE_WEB = ROOT / "infra" / "Dockerfile.web"
COMPOSE = ROOT / "docker-compose.yml"
MAIN_PY = ROOT / "apps" / "api" / "main.py"
CADDY = ROOT / "infra" / "Caddyfile.example"
MIGRATIONS = ROOT / "infra" / "migrations"
PRODUCTION_MD = ROOT / "docs" / "PRODUCTION.md"


def test_api_base_treats_empty_string_as_same_origin():
    """`||` would make an empty NEXT_PUBLIC_API_URL fall back to localhost:8103 —
    in exactly the production build that is supposed to be same-origin. The page
    would then call a host that only exists on the build machine, with nothing in
    any server log to show for it."""
    src = HTTP_TS.read_text()
    assert re.search(r"NEXT_PUBLIC_API_URL\s*\?\?", src), (
        "API_BASE must use ?? so an empty string means same origin"
    )
    assert not re.search(r"NEXT_PUBLIC_API_URL\s*\|\|", src)


def test_web_image_defaults_to_same_origin():
    """A hardcoded ARG default means a bare `docker build` produces an image that
    only works on the machine that built it."""
    src = DOCKERFILE_WEB.read_text()
    assert re.search(r"^ARG NEXT_PUBLIC_API_URL=\s*$", src, re.MULTILINE), (
        "the ARG default must be empty; compose passes localhost for dev"
    )


def test_next_public_values_are_inlined_before_the_build():
    """NEXT_PUBLIC_* is baked into the client bundle by `npm run build`. If the
    ENV lines moved after it, changing the value would appear to do nothing."""
    src = DOCKERFILE_WEB.read_text()
    build_at = src.index("npm run build")
    for var in ("NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"):
        env_at = src.index(f"ENV {var}=")
        assert env_at < build_at, f"{var} is set after the build and would not be inlined"


@pytest.mark.parametrize("service_port", ["5432", "8000", "3000"])
def test_nothing_is_published_to_the_world(service_port: str):
    """Docker's published ports bypass ufw. Without the loopback prefix this host
    served Postgres — credentials exposure/exposure — to the public internet, and
    left the API reachable directly, which defeats same-origin CORS entirely."""
    for line in COMPOSE.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("- \"") or f":{service_port}\"" not in stripped:
            continue
        assert "127.0.0.1:" in stripped, f"published to all interfaces: {stripped}"


def test_the_two_production_values_are_overridable_from_env():
    """Both were hardcoded in compose, so a production value could not be set
    without editing the file that is under version control."""
    src = COMPOSE.read_text()
    assert "${NEXT_PUBLIC_API_URL-" in src, "must allow an explicitly EMPTY override"
    assert "${CORS_ORIGINS-" in src


def test_health_is_reachable_under_the_api_prefix():
    """Caddy routes only /api/* to this service, so a bare /health lands on the
    web app and 404s — during the very smoke test meant to prove the API is up."""
    assert '@app.get("/api/health")' in MAIN_PY.read_text()


def test_every_migration_is_named_in_the_deploy_doc():
    """There is no alembic here, so a migration runs because a human read this
    document and typed it. A file nobody names is a file nobody applies, and the
    failure surfaces as the new code 500ing on a column that does not exist —
    long after the deploy looked successful."""
    doc = PRODUCTION_MD.read_text()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        assert path.name in doc, f"{path.name} is not named in docs/PRODUCTION.md"


def test_schema_lands_before_the_code_that_reads_it():
    """Additive columns are only backward compatible in one direction: old code
    tolerates a new column, new code does not tolerate its absence. The doc used
    to bring the whole stack up first, so every additive migration had a window
    where the API was live against a schema it predated."""
    doc = PRODUCTION_MD.read_text()
    deploy = doc[doc.index("## Deploying"):]
    last_migration = max(deploy.index(p.name) for p in MIGRATIONS.glob("*.sql"))
    full_up = deploy.index("docker compose up -d\n")
    assert last_migration < full_up, (
        "the migrations must be applied before the full stack starts"
    )


def test_caddy_example_does_not_strip_the_api_prefix():
    """The routers are mounted under /api inside the app, so `uri strip_prefix
    /api` would 404 every endpoint while looking entirely reasonable."""
    directives = [ln for ln in CADDY.read_text().splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
    assert any("handle /api/*" in ln for ln in directives)
    assert not any("strip_prefix" in ln for ln in directives), (
        "strip_prefix may be discussed in a comment, never configured"
    )


def test_a_one_time_backfill_cannot_undo_a_deliberate_zero():
    """V3-R6. There is no alembic here: every migration file is re-applied by
    hand on every deploy, so a backfill has to say WHICH rows it is repairing.

    The tool_budget sweep did not. It was written to fix rows stored under the
    old reading of 0 ("unset" -> hand back the default) and it matched every 0
    for ever — including the one an operator sets at 3am to switch a runaway
    session off. The next deploy would clear it, and the kill switch the sweep
    exists to make meaningful would be the thing it undid."""
    sql = (MIGRATIONS / "v3_harness.sql").read_text()
    sweeps = re.findall(r"UPDATE agent_sessions SET tool_budget = NULL[^;]*;", sql)
    assert sweeps, "expected the tool_budget backfill to still be present"
    for stmt in sweeps:
        assert "started_at" in stmt, f"unbounded one-time backfill: {stmt}"
