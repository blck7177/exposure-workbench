"""Erase one user's data. Owner role only, operator-invoked, never an API.

WHAT THIS DOES NOT TOUCH, and why nobody should "fix" it: every shared-layer
table survives untouched — companies, filings, filing_documents, filing_sections,
filing_chunks, financial_facts, market_prices, factor_prices, security_master,
research_sources and calc_ledger. That is company-level evidence, append-only and
depended on by every other tenant; deleting a companies row would cascade seven
ways into other people's data. Two pointers into it are deliberately left
dangling: calc_ledger.invoked_by keeps the departed session id and
research_sources.research_run_id keeps the departed run id. Neither column has a
foreign key, dangling ids already exist on the live volume, and an append-only
evidence store is not rewritten to tidy a pointer.

Why a script and not a route: IMPLEMENTATION_PLAN_V2 section 0.2 bans deletion
flows in the *application* — routes, agent tools, UI buttons — and app_rls holds
no DELETE grant, which is that ban hardened at the permission layer. Erasure is
an operational act carried out as the table owner. It cannot be reached from the
running system at all, which is the point.

Idempotent in EFFECT — every statement is a DELETE ... WHERE, so nothing can be
double-deleted — but deliberately NOT in exit code. Running it twice ends in the
"owns nothing" refusal, exit 2, because that case is indistinguishable from a
mistyped id and the safe reading of the two has to win. See
_guard_matched_something before changing it back.

Clerk is the identity system of record and this script does not touch it. Delete
the Clerk user FIRST: while it exists, a single sign-in re-upserts the users row
under the same id and the erasure silently undoes itself. --apply therefore
requires --clerk-deleted, which is an assertion by the operator, not a check.

Usage:
    python scripts/delete_user.py user_xxx                        # dry run (default)
    python scripts/delete_user.py user_xxx --apply --clerk-deleted
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg2

DB_URL = os.getenv(
    "DATABASE_URL_LOCAL_SYNC",
    os.getenv("DATABASE_URL_SYNC", "postgresql+psycopg2://exposure:exposure@localhost:5433/exposure_workbench"),
)
DB_DSN = DB_URL.replace("postgresql+psycopg2://", "postgresql://")

OWNER_ROLE = "exposure"

# Refused unconditionally. user_demo_system owns port_001 and the public briefs;
# erasing it takes down /, /issuer/NVDA and the demo brief in one command.
# '_global' is the cross-tenant quota backstop row, not a person — deleting it
# silently refunds the platform-wide limit.
SENTINELS = frozenset({"user_demo_system", "_global"})

# Deletion order. Derived from live pg_constraint, not from the ORM: models.py
# declares a foreign key on workflow_events.run_id that the database does not
# have. Rows covered by ON DELETE CASCADE are still listed and still deleted
# explicitly — the operator needs a per-table count and a cascade reports
# nothing, and the explicit list is what the offline order test can check. After
# this runs, a cascade should have removed zero additional rows.
#
# Every predicate is equality against the user id or against a captured id set.
# No statement may use IS NULL: ownerless rows exist (sessions and tasks created
# by system paths) and they belong to nobody, so they must not be swept up here.
DELETION_ORDER: list[tuple[str, str]] = [
    ("workflow_events", "run_id = ANY(%(events)s)"),          # no FK; polymorphic over three id prefixes
    ("evidence_packs", "session_id = ANY(%(sessions)s) OR research_run_id = ANY(%(research_runs)s)"),
    ("daily_reports", "run_id = ANY(%(runs)s)"),              # filter the FK column, not the RLS policy's portfolio_id
    ("risk_alerts", "run_id = ANY(%(runs)s)"),
    ("factor_residuals", "run_id = ANY(%(runs)s)"),
    ("factor_attributions", "run_id = ANY(%(runs)s)"),
    ("issuer_exposures", "run_id = ANY(%(runs)s)"),
    ("sector_exposures", "run_id = ANY(%(runs)s)"),
    ("exposure_metrics", "run_id = ANY(%(runs)s)"),
    ("exposure_runs", "portfolio_id = ANY(%(portfolios)s)"),  # FK to portfolios is NO ACTION — must precede portfolios
    ("schedules", "portfolio_id = ANY(%(portfolios)s)"),      # FK to portfolios is NO ACTION — must precede portfolios
    ("risk_limits", "portfolio_id = ANY(%(portfolios)s)"),
    ("positions", "portfolio_id = ANY(%(portfolios)s)"),
    ("portfolios", "owner_id = %(user)s"),
    ("agent_steps", "session_id = ANY(%(sessions)s)"),
    ("agent_messages", "session_id = ANY(%(sessions)s)"),
    ("agent_sessions", "owner_id = %(user)s"),
    ("issuer_briefs", "owner_id = %(user)s"),                 # free-standing: research_run_id carries no FK
    ("research_runs", "owner_id = %(user)s"),
    ("tasks", "owner_user_id = %(user)s"),                    # payload can hold the user's own ticker list
    ("usage_daily", "user_id = %(user)s"),                    # never '_global'
    ("users", "id = %(user)s"),                               # last; nothing references users
]

OWNER_COLUMNS = [
    ("portfolios", "owner_id"),
    ("agent_sessions", "owner_id"),
    ("research_runs", "owner_id"),
    ("issuer_briefs", "owner_id"),
    ("tasks", "owner_user_id"),
    ("usage_daily", "user_id"),
]


class Refused(Exception):
    """A guard rejected the whole invocation. Nothing was deleted."""


def _collect(cur, user: str) -> dict[str, list[str]]:
    """Capture every id set BEFORE deleting anything.

    Four of the tables below have no foreign key to their logical parent, so
    once the parent row is gone they are unreachable and their rows would be
    orphaned forever — app_rls cannot delete them and no route exposes them.
    """
    cur.execute("SELECT id FROM portfolios WHERE owner_id = %s", (user,))
    portfolios = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT id FROM exposure_runs WHERE portfolio_id = ANY(%s)", (portfolios,))
    runs = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT id FROM research_runs WHERE owner_id = %s", (user,))
    research_runs = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT id FROM agent_sessions WHERE owner_id = %s", (user,))
    sessions = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT id FROM tasks WHERE owner_user_id = %s", (user,))
    tasks = [r[0] for r in cur.fetchall()]

    return {
        "user": user,
        "portfolios": portfolios,
        "runs": runs,
        "research_runs": research_runs,
        "sessions": sessions,
        "tasks": tasks,
        # workflow_events.run_id is polymorphic: an exposure run, a research run
        # or — for company_readiness — the task id itself. All three prefixes.
        "events": runs + research_runs + tasks,
    }


def _guard_sentinel(user: str) -> None:
    if user in SENTINELS:
        raise Refused(
            f"{user!r} is a system sentinel, not a person. "
            "Erasing user_demo_system takes down port_001, the public briefs and the "
            "anonymous demo surface; '_global' is the cross-tenant quota backstop."
        )


def _guard_matched_something(cur, user: str) -> None:
    cur.execute("SELECT 1 FROM users WHERE id = %s", (user,))
    if cur.fetchone():
        return
    for table, column in OWNER_COLUMNS:
        cur.execute(f"SELECT 1 FROM {table} WHERE {column} = %s LIMIT 1", (user,))
        if cur.fetchone():
            return
    raise Refused(
        f"{user!r} matches no row in users and owns nothing — either it is "
        "mistyped, or it was already erased.\n"
        "Those two are indistinguishable from here, and only one of them can set "
        "the exit code. Refusing is the safer of the two: a mistyped id that "
        "reported 'erased, 0 rows' is how an operator comes to believe they "
        "deleted an account they did not touch. Re-running after a successful "
        "erasure lands here too, and that is correct — the effect is already "
        "idempotent (every statement is a DELETE ... WHERE); it is only the exit "
        "code that says 'there was nothing here'."
    )


def _guard_no_active_work(cur, ids: dict[str, list[str]]) -> None:
    """A live worker holds that tenant's context and would write rows back after
    the commit, recreating exactly what we just erased."""
    problems: list[str] = []

    # The column is `type`, not `task_type` — the ORM attribute and the column
    # do not share a name here.
    cur.execute(
        "SELECT id, type, status FROM tasks "
        "WHERE owner_user_id = %(user)s AND status IN ('pending', 'running')",
        ids,
    )
    problems += [f"task {r[0]} ({r[1]}) is {r[2]}" for r in cur.fetchall()]

    cur.execute(
        "SELECT id, status FROM exposure_runs "
        "WHERE portfolio_id = ANY(%(portfolios)s) AND status IN ('pending', 'running')",
        ids,
    )
    problems += [f"exposure run {r[0]} is {r[1]}" for r in cur.fetchall()]

    cur.execute(
        "SELECT id, status FROM research_runs "
        "WHERE owner_id = %(user)s AND status IN ('pending', 'running')",
        ids,
    )
    problems += [f"research run {r[0]} is {r[1]}" for r in cur.fetchall()]

    if problems:
        raise Refused(
            "work is still in flight for this user; wait for it to finish or fail it:\n  "
            + "\n  ".join(problems)
        )


def _manifest(cur, ids: dict[str, list[str]]) -> list[tuple[str, int]]:
    counts = []
    for table, predicate in DELETION_ORDER:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {predicate}", ids)
        counts.append((table, cur.fetchone()[0]))
    return counts


def _delete(cur, ids: dict[str, list[str]]) -> list[tuple[str, int]]:
    deleted = []
    for table, predicate in DELETION_ORDER:
        cur.execute(f"DELETE FROM {table} WHERE {predicate}", ids)
        deleted.append((table, cur.rowcount))
    return deleted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Erase one user's data (owner role, operator only).")
    ap.add_argument("user_id", help="the Clerk user id, e.g. user_2abc...")
    ap.add_argument("--apply", action="store_true", help="actually delete; default is a dry run")
    ap.add_argument(
        "--clerk-deleted",
        action="store_true",
        help="assert the Clerk user is already gone; required with --apply",
    )
    args = ap.parse_args(argv)
    user = args.user_id

    if args.apply and not args.clerk_deleted:
        print(
            "refused: --apply requires --clerk-deleted.\n"
            "Delete the user in Clerk first — while it exists, one sign-in re-upserts\n"
            "the users row under the same id and this erasure undoes itself.",
            file=sys.stderr,
        )
        return 2

    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user")
            role = cur.fetchone()[0]
            if role != OWNER_ROLE:
                print(
                    f"refused: connected as {role!r}, need the table owner {OWNER_ROLE!r}. "
                    "app_rls holds no DELETE grant by design.",
                    file=sys.stderr,
                )
                return 2

            try:
                _guard_sentinel(user)
                _guard_matched_something(cur, user)
                ids = _collect(cur, user)
                _guard_no_active_work(cur, ids)
            except Refused as e:
                print(f"refused: {e}", file=sys.stderr)
                conn.rollback()
                return 2

            if not args.apply:
                print(f"DRY RUN — {user}. Nothing will be written.\n")
                total = 0
                for table, n in _manifest(cur, ids):
                    print(f"  {table:<22} {n:>6}")
                    total += n
                print(f"  {'':<22} {'-' * 6}\n  {'total':<22} {total:>6}")
                print("\nRe-run with --apply --clerk-deleted to erase.")
                conn.rollback()
                return 0

            deleted = _delete(cur, ids)
        conn.commit()
    finally:
        conn.close()

    print(f"ERASED — {user}\n")
    total = 0
    for table, n in deleted:
        print(f"  {table:<22} {n:>6}")
        total += n
    print(f"  {'':<22} {'-' * 6}\n  {'total':<22} {total:>6}")
    print("\nShared company evidence was not touched, by design — see this file's docstring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
