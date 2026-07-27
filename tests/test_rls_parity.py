"""RLS / schema parity between infra/init.sql and infra/migrations (offline).

The two files are written by hand and must agree: init.sql is the fresh-database
truth, the migration is what a live volume actually gets. V2-C's generator is
gone, so nothing but a test enforces the pairing. These guard the specific
drift that has already cost this project a working feature:

- workflow_events is polymorphic over THREE parents. Missing the tasks branch
  silently disabled company_readiness end to end (0 events, 0 tasks ever).
- Both halves of that policy need every branch, because the ORM writes
  INSERT ... RETURNING and Postgres runs the SELECT policy over the new row.
- A view over an RLS table without security_invoker reads with the definer's
  privileges, i.e. straight past the tenant policies.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_INFRA = Path(__file__).resolve().parents[1] / "infra"
INIT_SQL = _INFRA / "init.sql"
MIGRATION_SQL = _INFRA / "migrations" / "v2_multiuser.sql"

# Every parent a workflow_events row can hang off, with the column the policy
# must compare against. Adding a task type that logs a timeline means adding a
# branch here and in both SQL files.
WORKFLOW_EVENT_PARENTS = {
    "exposure_runs": "r.id = workflow_events.run_id",
    "research_runs": "rr.id = workflow_events.run_id",
    "tasks": "t.id = workflow_events.run_id",
}

RLS_VIEWS = ("session_cost", "research_run_cost")


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _effective_policy(sql: str, table: str) -> str:
    """The policy that wins: files may redefine a policy in a later section
    (each preceded by its own DROP), so the LAST definition is the live one."""
    hits = re.findall(
        rf"CREATE POLICY tenant ON {table}\b(.*?);\s*$",
        sql,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert hits, f"no tenant policy for {table} in the file"
    return hits[-1]


def _halves(policy: str) -> tuple[str, str]:
    parts = re.split(r"\bWITH CHECK\b", policy, maxsplit=1)
    assert len(parts) == 2, "policy has no WITH CHECK half"
    return parts[0], parts[1]


@pytest.mark.parametrize("path", [INIT_SQL, MIGRATION_SQL], ids=["init", "migration"])
@pytest.mark.parametrize("parent", sorted(WORKFLOW_EVENT_PARENTS))
def test_workflow_events_policy_covers_every_parent_in_both_halves(path: Path, parent: str):
    """USING alone is not enough, and WITH CHECK alone is not enough — the
    failure text for a missing USING branch reads like a WITH CHECK failure."""
    using, with_check = _halves(_effective_policy(_sql(path), "workflow_events"))
    join = WORKFLOW_EVENT_PARENTS[parent]
    assert join in using, f"{path.name}: USING half is missing the {parent} branch"
    assert join in with_check, f"{path.name}: WITH CHECK half is missing the {parent} branch"


def test_tasks_branch_matches_the_owner_column_the_worker_writes():
    """company_readiness logs under run_id = task.id, and tasks carries the owner
    as owner_user_id (not owner_id like the five owner tables) — a copy-paste of
    the sibling branches would compare the wrong column and deny every write."""
    for path in (INIT_SQL, MIGRATION_SQL):
        policy = _effective_policy(_sql(path), "workflow_events")
        assert "t.owner_user_id = current_setting('app.user_id', true)" in policy, path.name


@pytest.mark.parametrize("view", RLS_VIEWS)
def test_cost_views_are_security_invoker(view: str):
    init = _sql(INIT_SQL)
    assert re.search(
        rf"CREATE OR REPLACE VIEW {view}\s+WITH \(security_invoker = true\)", init
    ), f"init.sql: {view} would read past RLS with the definer's privileges"
    migration = _sql(MIGRATION_SQL)
    assert re.search(
        rf"ALTER VIEW\s+{view}\s+SET \(security_invoker = true\)", migration
    ), f"migration: {view} is never flipped on live volumes"


def test_tasks_table_has_no_rls():
    """The tasks branch above is a plain lookup only because tasks is a shared
    table. Enabling RLS on it would make the branch self-referential and break
    readiness again — and the reaper (E1) batch-updates tasks with no tenant."""
    init = _sql(INIT_SQL)
    assert not re.search(r"ALTER TABLE tasks ENABLE ROW LEVEL SECURITY", init)
