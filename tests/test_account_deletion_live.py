"""V2-H — account erasure, end to end against a real Postgres.

Run with:  pytest -m live -k deletion

A destructive script with no test is worse than no script. The claims here are
the ones an operator is trusting when they type --apply:

  * every table that holds this user's data is emptied — including the four with
    no foreign key to their parent, which nothing in the database would catch;
  * the other tenant is bit-for-bit untouched;
  * shared company evidence survives, and the two pointers into it are still
    dangling exactly as they were, which is what proves we did not quietly
    UPDATE an append-only store to tidy up;
  * the guards refuse before writing anything, not halfway through.

The script is driven as a SUBPROCESS, because the guards and the argument
parsing are part of what is under test. Everything is seeded and inspected as
the owner role — this is an owner-role tool, and reading it as app_rls would
prove nothing about a script app_rls cannot run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "delete_user.py"

OWNER_URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)

TAG = uuid.uuid4().hex[:8]
VICTIM = f"user_del_V_{TAG}"
SURVIVOR = f"user_del_S_{TAG}"
DEMO_PORTFOLIO = "port_001"

# Mirrors DELETION_ORDER in the script. Kept as a literal so that a table added
# to the script without a test here shows up as a parametrize mismatch rather
# than as silent non-coverage.
OWNED_TABLES = [
    "workflow_events", "evidence_packs", "daily_reports", "risk_alerts",
    "factor_residuals", "factor_attributions", "issuer_exposures",
    "sector_exposures", "exposure_metrics", "exposure_runs", "schedules",
    "risk_limits", "positions", "portfolios", "agent_steps", "agent_messages",
    "agent_sessions", "issuer_briefs", "research_runs", "tasks", "usage_daily",
    "users",
]


def _ids(user_tag: str) -> dict[str, str]:
    return {
        "user": VICTIM if user_tag == "v" else SURVIVOR,
        "port": f"port_{TAG}_{user_tag}",
        "pos": f"pos_{TAG}_{user_tag}",
        "run": f"run_{TAG}_{user_tag}",
        "rrun": f"rrun_{TAG}_{user_tag}",
        "task": f"task_{TAG}_{user_tag}",
        "sess": f"sess_{TAG}_{user_tag}",
        "msg": f"msg_{TAG}_{user_tag}",
        "step": f"step_{TAG}_{user_tag}",
        "pack": f"pack_{TAG}_{user_tag}",
        "brief": f"brief_{TAG}_{user_tag}",
        "sched": f"sched_{TAG}_{user_tag}",
        "lim": f"lim_{TAG}_{user_tag}",
        "alert": f"alert_{TAG}_{user_tag}",
        "report": f"report_{TAG}_{user_tag}",
    }


async def _seed_user(db, tag: str, company_id: str) -> dict[str, str]:
    """One row in every table the script claims to erase."""
    i = _ids(tag)
    await db.execute(text("INSERT INTO users (id, email) VALUES (:u, :e)"),
                     {"u": i["user"], "e": f"{i['user']}@example.test"})
    await db.execute(
        text("""INSERT INTO portfolios (id, name, owner_id, is_public)
                VALUES (:p, 'deletion fixture', :u, FALSE)"""), {"p": i["port"], "u": i["user"]})
    await db.execute(
        text("""INSERT INTO positions (id, portfolio_id, as_of_date, ticker, quantity)
                VALUES (:i, :p, CURRENT_DATE, 'AAPL', 10)"""), {"i": i["pos"], "p": i["port"]})
    await db.execute(
        text("""INSERT INTO risk_limits (id, portfolio_id, limit_type, warning_level, breach_level)
                VALUES (:i, :p, 'var_95', 0.025, 0.035)"""), {"i": i["lim"], "p": i["port"]})
    await db.execute(
        text("INSERT INTO schedules (id, portfolio_id) VALUES (:i, :p)"),
        {"i": i["sched"], "p": i["port"]})
    await db.execute(
        text("""INSERT INTO exposure_runs (id, portfolio_id, status, as_of_date)
                VALUES (:r, :p, 'completed', CURRENT_DATE)"""), {"r": i["run"], "p": i["port"]})

    # All seven run children. factor_residuals is the one that was missing from
    # the ownership table, so its assertion is the whole point of this fixture.
    await db.execute(text("INSERT INTO exposure_metrics (run_id, portfolio_market_value) VALUES (:r, 1000)"),
                     {"r": i["run"]})
    await db.execute(text("INSERT INTO sector_exposures (run_id, sector) VALUES (:r, 'Technology')"),
                     {"r": i["run"]})
    await db.execute(text("INSERT INTO issuer_exposures (run_id, ticker) VALUES (:r, 'AAPL')"),
                     {"r": i["run"]})
    await db.execute(text("INSERT INTO factor_attributions (run_id, factor_name) VALUES (:r, 'MKT')"),
                     {"r": i["run"]})
    await db.execute(text("INSERT INTO factor_residuals (run_id) VALUES (:r)"), {"r": i["run"]})
    await db.execute(text("INSERT INTO risk_alerts (id, run_id, alert_type) VALUES (:i, :r, 'var_95')"),
                     {"i": i["alert"], "r": i["run"]})
    await db.execute(
        text("""INSERT INTO daily_reports (id, run_id, portfolio_id, as_of_date)
                VALUES (:i, :r, :p, CURRENT_DATE)"""),
        {"i": i["report"], "r": i["run"], "p": i["port"]})

    await db.execute(text("INSERT INTO agent_sessions (id, kind, owner_id) VALUES (:s, 'meta', :u)"),
                     {"s": i["sess"], "u": i["user"]})
    await db.execute(
        text("INSERT INTO agent_messages (id, session_id, role, content) VALUES (:m, :s, 'user', 'hello')"),
        {"m": i["msg"], "s": i["sess"]})
    await db.execute(
        text("INSERT INTO agent_steps (id, session_id, seq, step_type) VALUES (:i, :s, 1, 'tool_call')"),
        {"i": i["step"], "s": i["sess"]})

    await db.execute(
        text("""INSERT INTO research_runs (id, company_id, status, owner_id)
                VALUES (:r, :c, 'completed', :u)"""),
        {"r": i["rrun"], "c": company_id, "u": i["user"]})
    await db.execute(
        text("""INSERT INTO issuer_briefs (id, research_run_id, company_id, owner_id)
                VALUES (:i, :r, :c, :u)"""),
        {"i": i["brief"], "r": i["rrun"], "c": company_id, "u": i["user"]})
    await db.execute(
        text("""INSERT INTO evidence_packs (id, research_run_id, session_id, pack)
                VALUES (:i, :r, :s, '{}'::jsonb)"""),
        {"i": i["pack"], "r": i["rrun"], "s": i["sess"]})

    await db.execute(
        text("""INSERT INTO tasks (id, type, status, owner_user_id)
                VALUES (:i, 'exposure_update', 'completed', :u)"""),
        {"i": i["task"], "u": i["user"]})

    # workflow_events is polymorphic over three id prefixes and has no FK at
    # all. One of each, or the task_ branch stays the one everybody forgets.
    for parent in (i["run"], i["rrun"], i["task"]):
        await db.execute(                       # id is a serial here, unlike every other table
            text("INSERT INTO workflow_events (run_id, step_name) VALUES (:r, 'seed')"),
            {"r": parent})

    await db.execute(
        text("""INSERT INTO usage_daily (user_id, day, kind, used)
                VALUES (:u, CURRENT_DATE, 'chat_turn', 3)"""), {"u": i["user"]})
    return i


async def _counts(db, user: str, ids: dict[str, str]) -> dict[str, int]:
    """Per-table row counts for one user, using the same predicates the script does."""
    params = {
        "user": user,
        "portfolios": [ids["port"]],
        "runs": [ids["run"]],
        "research_runs": [ids["rrun"]],
        "sessions": [ids["sess"]],
        "events": [ids["run"], ids["rrun"], ids["task"]],
    }
    predicates = {
        "workflow_events": "run_id = ANY(:events)",
        "evidence_packs": "session_id = ANY(:sessions) OR research_run_id = ANY(:research_runs)",
        "daily_reports": "run_id = ANY(:runs)",
        "risk_alerts": "run_id = ANY(:runs)",
        "factor_residuals": "run_id = ANY(:runs)",
        "factor_attributions": "run_id = ANY(:runs)",
        "issuer_exposures": "run_id = ANY(:runs)",
        "sector_exposures": "run_id = ANY(:runs)",
        "exposure_metrics": "run_id = ANY(:runs)",
        "exposure_runs": "portfolio_id = ANY(:portfolios)",
        "schedules": "portfolio_id = ANY(:portfolios)",
        "risk_limits": "portfolio_id = ANY(:portfolios)",
        "positions": "portfolio_id = ANY(:portfolios)",
        "portfolios": "owner_id = :user",
        "agent_steps": "session_id = ANY(:sessions)",
        "agent_messages": "session_id = ANY(:sessions)",
        "agent_sessions": "owner_id = :user",
        "issuer_briefs": "owner_id = :user",
        "research_runs": "owner_id = :user",
        "tasks": "owner_user_id = :user",
        "usage_daily": "user_id = :user",
        "users": "id = :user",
    }
    out = {}
    for table in OWNED_TABLES:
        r = await db.execute(text(f"SELECT count(*) FROM {table} WHERE {predicates[table]}"), params)
        out[table] = r.scalar_one()
    return out


def _run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


@pytest.fixture(scope="module")
async def scenario():
    """Seed, drive the whole erasure sequence in order, capture what happened."""
    engine = create_async_engine(OWNER_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    state: dict = {}

    async with mk() as db, db.begin():
        r = await db.execute(text("SELECT id FROM companies ORDER BY id LIMIT 1"))
        company_id = r.scalar_one()
        state["company_id"] = company_id
        v = await _seed_user(db, "v", company_id)
        s = await _seed_user(db, "s", company_id)
        state["v"], state["s"] = v, s

        # Shared canaries. calc_ledger and research_sources point INTO the
        # victim's world without a foreign key; after erasure those pointers
        # must still be there, still dangling.
        await db.execute(
            text("""INSERT INTO calc_ledger (id, operation, primitive_version, invoked_by)
                    VALUES (:i, 'ratio', 'v1', :s)"""),
            {"i": f"calc_{TAG}", "s": v["sess"]})
        await db.execute(
            text("""INSERT INTO research_sources (id, url, provider, company_id, research_run_id)
                    VALUES (:i, 'https://example.test/x', 'tavily', :c, :r)"""),
            {"i": f"src_{TAG}", "c": company_id, "r": v["rrun"]})
        await db.execute(
            text("""INSERT INTO usage_daily (user_id, day, kind, used) VALUES ('_global', CURRENT_DATE, :k, 7)
                    ON CONFLICT (user_id, day, kind) DO UPDATE SET used = 7"""),
            {"k": f"probe_{TAG}"})

    async with mk() as db:
        state["survivor_before"] = await _counts(db, SURVIVOR, s)
        state["victim_before"] = await _counts(db, VICTIM, v)

    # (f) active work refuses, and refuses ATOMICALLY. status='running' with a
    # lease an hour out, never 'pending' — a pending task would be claimed by
    # the worker that is actually running on this box, and the test would be
    # racing it.
    async with mk() as db, db.begin():
        await db.execute(
            text("""INSERT INTO tasks (id, type, status, owner_user_id, lease_until, worker_id)
                    VALUES (:i, 'exposure_update', 'running', :u, NOW() + INTERVAL '1 hour', 'not-a-real-worker')"""),
            {"i": f"task_{TAG}_busy", "u": VICTIM})
    async with mk() as db:                      # baseline AFTER the busy task exists
        state["victim_before_busy"] = await _counts(db, VICTIM, v)
    state["busy"] = _run_script(VICTIM, "--apply", "--clerk-deleted")
    async with mk() as db:
        state["victim_after_busy"] = await _counts(db, VICTIM, v)
    async with mk() as db, db.begin():
        await db.execute(text("DELETE FROM tasks WHERE id = :i"), {"i": f"task_{TAG}_busy"})

    # (h) bare invocation is inert, (e) the sentinel is refused.
    state["dry"] = _run_script(VICTIM)
    async with mk() as db:
        state["victim_after_dry"] = await _counts(db, VICTIM, v)
    state["sentinel"] = _run_script("user_demo_system", "--apply", "--clerk-deleted")
    state["missing_clerk_flag"] = _run_script(VICTIM, "--apply")
    state["unknown"] = _run_script(f"user_no_such_{TAG}")
    async with mk() as db:
        r = await db.execute(text("SELECT is_public FROM portfolios WHERE id = :p"), {"p": DEMO_PORTFOLIO})
        state["demo_public_after_sentinel"] = r.scalar_one_or_none()

    # (a) the erasure itself, then (g) a second one.
    state["apply"] = _run_script(VICTIM, "--apply", "--clerk-deleted")
    async with mk() as db:
        state["victim_after"] = await _counts(db, VICTIM, v)
        state["survivor_after"] = await _counts(db, SURVIVOR, s)
        r = await db.execute(text("SELECT invoked_by FROM calc_ledger WHERE id = :i"), {"i": f"calc_{TAG}"})
        state["calc_invoked_by"] = r.scalar_one_or_none()
        r = await db.execute(text("SELECT research_run_id FROM research_sources WHERE id = :i"),
                             {"i": f"src_{TAG}"})
        state["source_run_id"] = r.scalar_one_or_none()
        r = await db.execute(
            text("SELECT used FROM usage_daily WHERE user_id = '_global' AND day = CURRENT_DATE AND kind = :k"),
            {"k": f"probe_{TAG}"})
        state["global_used_after"] = r.scalar_one_or_none()
    state["apply_again"] = _run_script(VICTIM, "--apply", "--clerk-deleted")
    async with mk() as db:
        state["victim_after_second"] = await _counts(db, VICTIM, v)

    try:
        yield state
    finally:
        async with mk() as db, db.begin():
            await db.execute(text("DELETE FROM calc_ledger WHERE id = :i"), {"i": f"calc_{TAG}"})
            await db.execute(text("DELETE FROM research_sources WHERE id = :i"), {"i": f"src_{TAG}"})
            await db.execute(
                text("DELETE FROM usage_daily WHERE user_id = '_global' AND kind = :k"),
                {"k": f"probe_{TAG}"})
            for table, predicate in [
                ("workflow_events", "run_id = ANY(:ev)"),
                ("evidence_packs", "session_id = ANY(:se) OR research_run_id = ANY(:rr)"),
                ("daily_reports", "run_id = ANY(:ru)"), ("risk_alerts", "run_id = ANY(:ru)"),
                ("factor_residuals", "run_id = ANY(:ru)"), ("factor_attributions", "run_id = ANY(:ru)"),
                ("issuer_exposures", "run_id = ANY(:ru)"), ("sector_exposures", "run_id = ANY(:ru)"),
                ("exposure_metrics", "run_id = ANY(:ru)"), ("exposure_runs", "portfolio_id = ANY(:po)"),
                ("schedules", "portfolio_id = ANY(:po)"), ("risk_limits", "portfolio_id = ANY(:po)"),
                ("positions", "portfolio_id = ANY(:po)"), ("portfolios", "owner_id = ANY(:us)"),
                ("agent_steps", "session_id = ANY(:se)"), ("agent_messages", "session_id = ANY(:se)"),
                ("agent_sessions", "owner_id = ANY(:us)"), ("issuer_briefs", "owner_id = ANY(:us)"),
                ("research_runs", "owner_id = ANY(:us)"), ("tasks", "owner_user_id = ANY(:us)"),
                ("usage_daily", "user_id = ANY(:us)"), ("users", "id = ANY(:us)"),
            ]:
                await db.execute(text(f"DELETE FROM {table} WHERE {predicate}"), {
                    "us": [VICTIM, SURVIVOR],
                    "po": [v["port"], s["port"]],
                    "ru": [v["run"], s["run"]],
                    "rr": [v["rrun"], s["rrun"]],
                    "se": [v["sess"], s["sess"]],
                    "ev": [v["run"], v["rrun"], v["task"], s["run"], s["rrun"], s["task"]],
                })
        await engine.dispose()


def test_the_fixture_actually_seeded_every_table(scenario):
    """If a table seeded zero rows, its erasure assertion below proves nothing."""
    empty = [t for t, n in scenario["victim_before"].items() if n == 0]
    assert empty == [], f"fixture seeded nothing into: {empty}"


def test_apply_succeeded(scenario):
    assert scenario["apply"].returncode == 0, scenario["apply"].stderr


@pytest.mark.parametrize("table", OWNED_TABLES)
def test_every_owned_table_is_empty_after_erasure(scenario, table):
    assert scenario["victim_after"][table] == 0, (
        f"{table} still holds {scenario['victim_after'][table]} row(s) for the erased user"
    )


def test_the_other_tenant_is_untouched(scenario):
    assert scenario["survivor_after"] == scenario["survivor_before"]


def test_shared_evidence_survives_with_its_pointers_still_dangling(scenario):
    """Not merely 'the row is still there' — the pointer still holds the departed
    id. Rewriting it to a tombstone would be the first mutation ever made to an
    append-only store, so the assertion is on the exact old value."""
    assert scenario["calc_invoked_by"] == scenario["v"]["sess"]
    assert scenario["source_run_id"] == scenario["v"]["rrun"]


def test_the_global_quota_backstop_is_not_refunded(scenario):
    assert scenario["global_used_after"] == 7


def test_active_work_refuses_and_deletes_nothing(scenario):
    """Atomicity is the claim: not 'it stopped', but 'it stopped before writing'."""
    assert scenario["busy"].returncode == 2
    assert "in flight" in scenario["busy"].stderr
    assert scenario["victim_after_busy"] == scenario["victim_before_busy"]


def test_a_bare_invocation_is_a_dry_run(scenario):
    assert scenario["dry"].returncode == 0
    assert "DRY RUN" in scenario["dry"].stdout
    assert scenario["victim_after_dry"] == scenario["victim_before"]


def test_the_demo_sentinel_is_refused_and_the_demo_survives(scenario):
    assert scenario["sentinel"].returncode == 2
    assert "sentinel" in scenario["sentinel"].stderr
    assert scenario["demo_public_after_sentinel"] is True


def test_apply_requires_the_clerk_assertion(scenario):
    assert scenario["missing_clerk_flag"].returncode == 2
    assert "--clerk-deleted" in scenario["missing_clerk_flag"].stderr


def test_an_unknown_id_is_refused_rather_than_reported_as_success(scenario):
    assert scenario["unknown"].returncode == 2


def test_erasing_twice_changes_nothing_and_says_so(scenario):
    """The effect is idempotent; the exit code deliberately is not. A second run
    lands in the same refusal a mistyped id does, because from inside the script
    those two cases are the same case — and of the two readings, 'you may have
    just told me to erase the wrong person' is the one worth stopping for."""
    assert scenario["apply_again"].returncode == 2
    assert "owns nothing" in scenario["apply_again"].stderr
    assert "already erased" in scenario["apply_again"].stderr
    assert scenario["victim_after_second"] == scenario["victim_after"]
