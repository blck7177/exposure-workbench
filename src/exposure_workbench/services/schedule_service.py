"""Schedule service — the system's clock for recurring portfolio work (V13 §9-④A).

The scheduler does the SMALLEST possible thing inside the worker's poll loop:
notice that an instant has passed, advance the row, and enqueue a
`scheduled_update` task. Everything slow or fallible — the price sync, the run
mint — happens inside that task, under the normal lease machinery, so a hung
provider call costs one leased task and not the loop that processes everyone
else's work.

WHY THIS SERVICE CONNECTS AS THE OWNER ROLE. Every other read in the system runs
as app_rls with a tenant GUC, and `schedules` carries the same tenant policy as
the tables around it — which is exactly right for the API path (a user manages
their own schedules) and exactly wrong for a clock. The scheduler spans every
tenant by definition, and it cannot learn a schedule's tenant without first
seeing the row: the policy joins portfolios.owner_id, which is behind the same
policy. The reaper already lives this way — it scans `tasks` across all tenants
— the only difference being that `tasks` carries no RLS while `schedules` does,
so the clock needs the owner engine the operational scripts use. The tenant
discipline is preserved where it matters: the minted task row carries
owner_user_id, the worker restores that tenant (V2-A), and every user-visible
write — the portfolio read, the quota charge, the run row — happens inside the
handler under RLS as that user.

WHY tick() DOES NOT GO THROUGH task_service.create_task. create_task is a charge
point, and TASK_TYPE_QUOTA_KIND's deliberate KeyError forced this sentence to be
written: the user pays for the night's work exactly once, at the
exposure_update mint inside the handler — the same charge the API door levies.
Billing the wrapper as well would charge one 06:30 run twice; exempting it from
quota entirely while routing it through the charge point would need a fallback
in create_task. The direct enqueue keeps the exemption visible right here, and
test_quota.py / test_schedule_service.py pin it from both sides.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.db.models import Portfolio, Schedule, Task
from exposure_workbench.utils.ids import new_task_id

logger = logging.getLogger(__name__)

# What a scheduler-started run is called. Minted here, at the only door that can
# truthfully say it (V13-S1) — the enqueue payload carries a copy for the audit
# trail, and the handler re-mints the constant rather than reading that copy.
TRIGGERED_BY_SCHEDULER = "scheduled"


# ─── the clock ────────────────────────────────────────────────────────────────

def next_fire(cron_expression: str, tz: str, after: datetime) -> datetime:
    """The first instant after `after` that `cron_expression` names in `tz`,
    as an aware UTC datetime.

    The computation happens in the schedule's own zone and only the RESULT is
    converted, because "30 6 * * 1-5" means 06:30 in New York all year — two
    different UTC instants depending on the season, and croniter can only honour
    the DST transition if it is handed the local wall clock.
    """
    if after.tzinfo is None:
        # A naive datetime would be read in whatever zone the caller's clock
        # happens to be, which is precisely the drift this function exists to
        # make impossible.
        raise ValueError("next_fire requires an aware datetime")
    local_after = after.astimezone(ZoneInfo(tz))
    fire = croniter(cron_expression, local_after).get_next(datetime)
    return fire.astimezone(timezone.utc)


# ─── the claim ────────────────────────────────────────────────────────────────

def _due_stmt(now: datetime):
    """Rows the tick may touch: active, and either due or never armed. Module
    level so the lock clause is pinned by test_schedule_service the way
    _REAP_SQL is — SKIP LOCKED is what lets three worker processes tick in the
    same second and produce one claim plus two empty results."""
    return (
        select(Schedule)
        .where(
            Schedule.is_active.is_(True),
            or_(Schedule.next_run_at.is_(None), Schedule.next_run_at <= now),
        )
        .with_for_update(skip_locked=True)
    )


async def due_schedules(db: AsyncSession) -> list[Schedule]:
    """Claim every due schedule and advance it, in the caller's transaction.

    Two behaviours here are semantics, not bookkeeping:

    A row whose next_run_at is NULL is ARMED (given its first fire instant),
    never fired — a schedule created at 03:00 for "06:30 weekdays" waits for
    06:30, it does not run because the next tick happened to see it.

    next_run_at always advances from NOW, never walked forward from where it
    fell behind: a worker down over a long weekend owes the book one fresh run,
    not one stale run per missed 06:30. The claim's `now` is this process's
    clock rather than the server's — unlike the lease fence, nothing here is
    stolen by skew; a skewed worker fires the same schedule a few seconds off,
    and the row lock plus the advance keep it single-fire regardless.
    """
    now = datetime.now(timezone.utc)
    rows = (await db.execute(_due_stmt(now))).scalars().all()
    due: list[Schedule] = []
    for s in rows:
        if s.next_run_at is None:
            s.next_run_at = next_fire(s.cron_expression, s.timezone, now)
            continue
        s.last_run_at = now
        s.next_run_at = next_fire(s.cron_expression, s.timezone, now)
        due.append(s)
    await db.flush()
    return due


async def tick(db_factory=None) -> int:
    """One scheduler pass: claim, advance, enqueue. Returns how many tasks were
    minted. Claim and enqueue share one transaction on purpose — if the enqueue
    fails, next_run_at has not advanced either, and the next tick simply tries
    the same fire again instead of losing it.
    """
    factory = db_factory if db_factory is not None else _scheduler_session_factory()
    async with factory() as db:
        due = await due_schedules(db)
        for s in due:
            owner = (
                await db.execute(
                    select(Portfolio.owner_id).where(Portfolio.id == s.portfolio_id)
                )
            ).scalar_one_or_none()
            if owner is None:
                # Post-V2-C every portfolio has an owner, so this is a broken
                # row, not a case. Failing the whole tick (and re-trying every
                # poll) is the loud version; minting a task no tenant could run
                # would fail quieter and further from the cause.
                raise ValueError(
                    f"schedule {s.id}: portfolio {s.portfolio_id} has no owner"
                )
            db.add(
                Task(
                    id=new_task_id(),
                    type="scheduled_update",
                    status="pending",
                    owner_user_id=owner,  # V2-A: the worker restores this tenant
                    payload={
                        "schedule_id": s.id,
                        "portfolio_id": s.portfolio_id,
                        "owner_user_id": owner,
                        "triggered_by": TRIGGERED_BY_SCHEDULER,
                    },
                )
            )
            logger.info(
                "schedule %s fired for portfolio %s (next %s)",
                s.id, s.portfolio_id, s.next_run_at,
            )
        await db.commit()
    return len(due)


# ─── the freshness helper ─────────────────────────────────────────────────────

async def next_update_for(db: AsyncSession, portfolio_id: str) -> datetime | None:
    """The soonest armed fire among the portfolio's active schedules, for the
    freshness chip — None when nothing is armed. Runs on the caller's ordinary
    tenant session: a user asking about their own book sees their own rows."""
    return (
        await db.execute(
            select(Schedule.next_run_at)
            .where(
                Schedule.portfolio_id == portfolio_id,
                Schedule.is_active.is_(True),
                Schedule.next_run_at.is_not(None),
            )
            .order_by(Schedule.next_run_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


# ─── the owner engine ─────────────────────────────────────────────────────────

_scheduler_factory = None


def _scheduler_session_factory():
    """Session factory on settings.database_url — the owner role, not app_rls.

    Lazy and cached: built on the first real tick, so the offline suite (which
    always hands tick() a fake factory) never opens a connection. Small pool —
    a tick is one short transaction every poll interval. The WHY of the role
    choice is the module docstring's second paragraph.
    """
    global _scheduler_factory
    if _scheduler_factory is None:
        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
        )
        _scheduler_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
    return _scheduler_factory
