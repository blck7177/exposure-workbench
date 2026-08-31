"""E1 — lease/requeue classification invariants (offline: no DB, no network).

The reaper's decision itself is a single SQL statement, so its three branches are
verified against a real database in test_task_lease_live.py. What CAN be checked
without a database is the thing most likely to rot: that every task type the
worker can dispatch has an explicitly stated policy for what happens when its
lease expires. Adding a fifth task type and forgetting to classify it is the
failure this file exists to catch — silence there means a task that either
replays into an IntegrityError or strands a run in 'running' forever.
"""

from __future__ import annotations

import pytest

from apps.worker import worker
from exposure_workbench.app_state.settings import Settings
from exposure_workbench.services import task_service

# Every type the worker's dispatch chain resolves. Kept here rather than imported
# because _get_handler is a lazy if/elif (deliberately, to dodge circular
# imports), so there is no runtime list to read.
DISPATCHABLE = {
    "exposure_update",
    "market_data_sync",
    "company_readiness",
    "issuer_research",
    "scheduled_update",
}

# Failed on expiry like the non-replayable types, but with NO run row of its own
# to settle: the run scheduled_update exists to mint belongs to the
# exposure_update task it creates, which carries its own lease. Stated as a set,
# not folded into _RUN_FAILERS, so the next type cannot hide behind it — being
# runless is a claim about the persistence code, and this one is measured: the
# handler writes nothing under its own task id.
FAILED_RUNLESS_ON_EXPIRY = {"scheduled_update"}


@pytest.mark.parametrize("task_type", sorted(DISPATCHABLE))
def test_dispatch_resolves_every_type_we_classify(task_type: str):
    """If this list drifts from the worker, every other test here is vacuous."""
    assert worker._get_handler(task_type) is not None


def test_unknown_task_type_resolves_to_no_handler():
    assert worker._get_handler("not_a_real_type") is None


def test_every_dispatchable_type_has_a_lease_expiry_policy():
    """Requeue it, or fail it and settle its run — every type must pick a side.

    A type in neither set would be failed by the reaper with its run left in
    'running' forever, which is the stuck-run class E1 exists to remove.
    """
    classified = (set(task_service.REQUEUEABLE_TYPES) | set(worker._RUN_FAILERS)
                  | FAILED_RUNLESS_ON_EXPIRY)
    assert DISPATCHABLE - classified == set(), (
        f"unclassified task types: {DISPATCHABLE - classified}"
    )


def test_requeueable_types_never_also_fail_a_run():
    """The two sets are opposite answers to the same question; overlap is a bug."""
    overlap = set(task_service.REQUEUEABLE_TYPES) & set(worker._RUN_FAILERS)
    assert overlap == set(), f"types both requeued and run-failed: {overlap}"


def test_classification_sets_contain_no_unknown_types():
    assert set(task_service.REQUEUEABLE_TYPES) <= DISPATCHABLE
    assert set(worker._RUN_FAILERS) <= DISPATCHABLE
    assert FAILED_RUNLESS_ON_EXPIRY <= DISPATCHABLE
    assert FAILED_RUNLESS_ON_EXPIRY.isdisjoint(task_service.REQUEUEABLE_TYPES)
    assert FAILED_RUNLESS_ON_EXPIRY.isdisjoint(worker._RUN_FAILERS)


def test_non_idempotent_types_are_not_replayable():
    """Pinned deliberately: these two are the ones that cost money or corrupt data
    on replay. A future 'optimisation' that adds either to the whitelist should
    have to delete this test and explain itself."""
    assert "exposure_update" not in task_service.REQUEUEABLE_TYPES
    assert "issuer_research" not in task_service.REQUEUEABLE_TYPES
    # Replaying scheduled_update re-runs its mint: a second run row and a second
    # quota charge for the same 06:30.
    assert "scheduled_update" not in task_service.REQUEUEABLE_TYPES


def test_reap_decides_expiry_on_the_server_clock():
    """Multi-replica safety: a worker with a skewed clock must not be able to
    steal a live task or strand a dead one, so both the comparison and the
    timestamps are the database's now(), never a bound client value."""
    sql = str(task_service._REAP_SQL)
    assert "lease_until < now()" in sql
    assert "completed_at  = CASE WHEN e.requeue THEN NULL               ELSE now() END" in sql
    assert ":expiry_ts" not in sql and ":now" not in sql


def test_reap_takes_row_locks_so_two_reapers_cannot_double_settle():
    assert "FOR UPDATE SKIP LOCKED" in str(task_service._REAP_SQL)


def test_lease_settings_defaults():
    s = Settings()
    assert s.task_lease_seconds == 1800
    assert s.task_max_retries == 3
