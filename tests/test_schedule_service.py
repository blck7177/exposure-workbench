"""V13 §9-④A — the scheduler's clock and its claim discipline (offline: no DB).

Two halves, two failure classes:

The CLOCK half pins next_fire against instants on both sides of a DST boundary,
because "06:30 in New York" is two different UTC instants depending on the
season. A scheduler that stores UTC but computes fires naively drifts an hour
twice a year — into the pre-open on one side, an hour after the sync mattered on
the other — and nothing else in the system would notice.

The CLAIM half pins that claiming a due row ADVANCES next_run_at in the same
transaction, so three worker processes ticking in the same second mint one task,
not three. The row-lock part of that guarantee is a single SQL clause, so it is
pinned against the statement the service actually builds (the same way
test_task_lease pins _REAP_SQL); the advance/initialise semantics are checked
against an in-memory session that answers the service's own statements.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from exposure_workbench.db.models import Schedule, Task
from exposure_workbench.services import schedule_service

NY = "America/New_York"
WEEKDAYS_0630 = "30 6 * * 1-5"


# ── the clock ─────────────────────────────────────────────────────────────────

def test_next_fire_returns_an_aware_utc_instant():
    after = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)  # Thursday
    fire = schedule_service.next_fire(WEEKDAYS_0630, NY, after)
    assert fire.tzinfo is not None and fire.utcoffset() == timedelta(0)
    # Friday 2026-03-06, 06:30 EST (UTC-5) — the winter side of the boundary.
    assert fire == datetime(2026, 3, 6, 11, 30, tzinfo=timezone.utc)


def test_next_fire_crosses_spring_forward():
    """2026-03-08 02:00 EST → 03:00 EDT. Friday's fire is 11:30Z; Monday's,
    computed across the transition, must be 10:30Z — same wall clock, new
    offset. A scheduler doing UTC arithmetic would say 11:30Z and be an hour
    late for the rest of the summer."""
    after = datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc)  # Friday, post-fire
    fire = schedule_service.next_fire(WEEKDAYS_0630, NY, after)
    assert fire == datetime(2026, 3, 9, 10, 30, tzinfo=timezone.utc)


def test_next_fire_crosses_fall_back():
    """2026-11-01 02:00 EDT → 01:00 EST: the mirror image, pinned on both
    sides so the assertion pair cannot pass by accident of season."""
    before = schedule_service.next_fire(
        WEEKDAYS_0630, NY, datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc))
    after = schedule_service.next_fire(
        WEEKDAYS_0630, NY, datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc))
    assert before == datetime(2026, 10, 30, 10, 30, tzinfo=timezone.utc)  # EDT
    assert after == datetime(2026, 11, 2, 11, 30, tzinfo=timezone.utc)    # EST


def test_next_fire_refuses_a_naive_after():
    """A naive datetime would be silently read in whatever zone croniter
    guesses, which is exactly the drift the aware contract exists to prevent."""
    with pytest.raises(ValueError):
        schedule_service.next_fire(WEEKDAYS_0630, NY, datetime(2026, 3, 5, 12, 0))


# ── the claim statement itself ────────────────────────────────────────────────

def test_claim_statement_takes_row_locks_and_skips_held_ones():
    """Three workers tick concurrently; SKIP LOCKED is what turns 'three claims'
    into 'one claim and two empty results'. Pinned on the compiled statement so
    a refactor cannot quietly drop the clause while the in-memory tests below
    keep passing."""
    stmt = schedule_service._due_stmt(datetime.now(timezone.utc))
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "is_active" in sql and "next_run_at" in sql


# ── in-memory session that answers the service's own statements ───────────────

class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Answers the three statements schedule_service issues, by shape.

    The due-claim predicate is re-evaluated in Python from the statement's own
    bound parameters (not a copy of `now` kept by the test), so the rows this
    fake hands back are the rows the real WHERE clause would select.
    """

    def __init__(self, schedules=(), owners=None):
        self.schedules = list(schedules)
        self.owners = owners or {}          # portfolio_id -> owner_id
        self.added: list[Task] = []
        self.commits = 0

    # factory protocol: schedule_service.tick(db_factory) calls factory() and
    # enters the result.
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        if "FROM schedules" in sql and "FOR UPDATE" in sql:
            params = stmt.compile(dialect=postgresql.dialect()).params
            bound_now = next(v for v in params.values() if isinstance(v, datetime))
            due = [s for s in self.schedules
                   if s.is_active and (s.next_run_at is None or s.next_run_at <= bound_now)]
            return FakeResult(due)
        if "FROM schedules" in sql:          # next_update_for
            vals = sorted(
                (s.next_run_at for s in self.schedules
                 if s.is_active and s.next_run_at is not None),
            )
            return FakeResult(vals[:1])
        if "FROM portfolios" in sql:         # owner lookup inside tick
            pid = next(v for v in stmt.compile(dialect=postgresql.dialect()).params.values()
                       if isinstance(v, str))
            owner = self.owners.get(pid)
            return FakeResult([owner] if owner is not None else [])
        raise AssertionError(f"unexpected statement: {sql}")

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


def factory_for(session: FakeSession):
    return lambda: session


def active(next_run_at, *, sid="sched_1", pid="port_1", cron=WEEKDAYS_0630, tz=NY):
    return Schedule(id=sid, portfolio_id=pid, task_type="exposure_update",
                    cron_expression=cron, timezone=tz, is_active=True,
                    next_run_at=next_run_at)


# ── claim semantics ───────────────────────────────────────────────────────────

async def test_fresh_row_is_armed_not_fired():
    """A row created at 03:00 with next_run_at NULL must wait for its first
    scheduled instant, not fire the moment the next tick sees it."""
    row = active(None)
    db = FakeSession([row])
    due = await schedule_service.due_schedules(db)
    assert due == []
    assert row.next_run_at is not None
    assert row.next_run_at > datetime.now(timezone.utc)
    assert row.last_run_at is None            # arming is not running


async def test_claim_advances_so_a_second_tick_claims_nothing():
    row = active(datetime.now(timezone.utc) - timedelta(minutes=1))
    db = FakeSession([row])
    first = await schedule_service.due_schedules(db)
    assert first == [row]
    assert row.last_run_at is not None
    assert row.next_run_at > datetime.now(timezone.utc)
    second = await schedule_service.due_schedules(db)
    assert second == []


async def test_missed_fires_collapse_into_one():
    """A worker down over a long weekend owes the book ONE fresh run, not one
    per missed 06:30 — next_run_at is computed from now, never walked forward
    from where it fell behind."""
    row = active(datetime.now(timezone.utc) - timedelta(days=3))
    db = FakeSession([row])
    due = await schedule_service.due_schedules(db)
    assert len(due) == 1
    expected = schedule_service.next_fire(WEEKDAYS_0630, NY, datetime.now(timezone.utc))
    assert abs((row.next_run_at - expected).total_seconds()) < 120
    assert await schedule_service.due_schedules(db) == []


# ── tick: what gets enqueued ──────────────────────────────────────────────────

async def test_tick_enqueues_one_scheduled_update_task_per_due_row():
    row = active(datetime.now(timezone.utc) - timedelta(minutes=1))
    db = FakeSession([row], owners={"port_1": "user_owner"})
    n = await schedule_service.tick(factory_for(db))
    assert n == 1 and db.commits == 1
    (task,) = db.added
    assert isinstance(task, Task)
    assert task.type == "scheduled_update"
    # The column is what the worker restores the tenant from (V2-A); the payload
    # copy is the audit trail the handler re-derives rather than trusts.
    assert task.owner_user_id == "user_owner"
    assert task.payload == {
        "schedule_id": "sched_1",
        "portfolio_id": "port_1",
        "owner_user_id": "user_owner",
        "triggered_by": "scheduled",
    }


async def test_tick_enqueues_nothing_when_nothing_is_due():
    row = active(datetime.now(timezone.utc) + timedelta(hours=6))
    db = FakeSession([row], owners={"port_1": "user_owner"})
    assert await schedule_service.tick(factory_for(db)) == 0
    assert db.added == []


def test_tick_does_not_route_through_create_task():
    """Deliberate, and pinned so it cannot be 'fixed': create_task is a charge
    point, and the user pays for the night's work once — at the exposure_update
    mint inside the handler. Routing the wrapper through create_task would
    either bill the same run twice or force a pool entry for work no user
    action enqueues. test_quota.py carries the matching exemption."""
    src = inspect.getsource(schedule_service)
    # The module docstring is allowed to NAME create_task while explaining this
    # exemption; what must not exist is a call.
    assert "create_task(" not in src


# ── the freshness helper ──────────────────────────────────────────────────────

async def test_next_update_for_returns_the_soonest_active_fire():
    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    later = datetime.now(timezone.utc) + timedelta(hours=9)
    db = FakeSession([
        active(later, sid="s1"),
        active(soon, sid="s2"),
        Schedule(id="s3", portfolio_id="port_1", task_type="exposure_update",
                 cron_expression=WEEKDAYS_0630, timezone=NY,
                 is_active=False, next_run_at=datetime.now(timezone.utc)),
    ])
    assert await schedule_service.next_update_for(db, "port_1") == soon


async def test_next_update_for_is_none_when_nothing_is_armed():
    db = FakeSession([active(None)])
    assert await schedule_service.next_update_for(db, "port_1") is None
