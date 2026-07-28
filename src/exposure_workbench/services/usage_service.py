"""Daily quota (V2-E3) — the one primitive that bounds what a visitor can spend.

The unit is a USER ACTION: one chat turn, one research run, one exposure run.
Not tokens, not tool calls. That choice is what lets the whole thing hang off two
charge points instead of a wrapper: exposure, readiness and research each have a
REST route AND a meta-agent delegation tool, and only `create_task` sits under
both. Per-session budgets (tool calls, external searches) live in
agent_session_service and bound one conversation; these bound one day. The two
are orthogonal and must not be merged.

Every action is charged twice in the SAME transaction — the user's pool, then
the shared '_global' backstop. Either one over limit rolls the whole thing back,
so no counter moves and there is nothing to refund. That is the entire reason
the design has no compensation logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.db.models import UsageDaily
from exposure_workbench.utils.dates import today_utc

# The shared backstop shares the counter table; it is simply a reserved user id.
# It must never be a real Clerk id — those are 'user_'-prefixed, so a leading
# underscore is unambiguous.
GLOBAL_SCOPE = "_global"

# kind -> (per-user settings attribute, global settings attribute).
# No default: an action whose kind is absent raises KeyError rather than passing
# through uncharged. Adding a pool means adding a row here and two settings.
POOLS: dict[str, tuple[str, str]] = {
    "chat_turn": ("daily_chat_turns", "global_daily_chat_turns"),
    "research_run": ("daily_research_runs", "global_daily_research_runs"),
    "readiness": ("daily_readiness", "global_daily_readiness"),
    "exposure_run": ("daily_exposure_runs", "global_daily_exposure_runs"),
    "market_sync": ("daily_market_syncs", "global_daily_market_syncs"),
}


class QuotaExceeded(Exception):
    """Raised without mutating anything. Carries the whole account so the caller
    can show the user their actual numbers rather than a bare 'try later'."""

    def __init__(self, kind: str, scope: str, used: int, limit: int):
        self.kind = kind
        self.scope = scope          # 'user' | 'global'
        self.used = used
        self.limit = limit
        self.resets_at = next_reset_at()
        super().__init__(
            f"daily {kind} quota reached for {scope} ({used}/{limit}); resets at {self.resets_at}"
        )

    def as_dict(self) -> dict:
        """The structured shape both the HTTP body and the delegation tools use.

        A GLOBAL refusal reports no numbers. `used` there is every user's activity
        added together, and this dict is returned verbatim to whoever tripped it —
        which would hand an outsider a daily census of how busy the platform is,
        and a clean signal for when it has been denied to everyone. /api/me/usage
        already keeps the backstop private; this is the same rule.
        """
        body = {
            "error": "quota_exceeded",
            "kind": self.kind,
            "scope": self.scope,
            "resets_at": self.resets_at,
        }
        if self.scope != "global":
            body["used"] = self.used
            body["limit"] = self.limit
        else:
            body["detail"] = "the shared daily limit for this action is exhausted; try again tomorrow"
        return body


def next_reset_at() -> str:
    """Midnight UTC after the current UTC day — the moment `day` rolls over."""
    tomorrow = today_utc() + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=timezone.utc).isoformat()


def limits_for(kind: str) -> tuple[int, int]:
    """(per-user, global) for one kind. KeyError on an unregistered kind."""
    user_attr, global_attr = POOLS[kind]
    settings = get_settings()
    return getattr(settings, user_attr), getattr(settings, global_attr)


# Conditional upsert, the same shape as agent_session_service.reserve: the WHERE
# on the DO UPDATE means two concurrent requests cannot both take the last unit.
# 0 rows back = at the limit (either the row already sat at it, or we lost the
# race), and in both cases nothing was written.
_CHARGE_SQL = text("""
INSERT INTO usage_daily (user_id, day, kind, used)
VALUES (:user_id, :day, :kind, 1)
ON CONFLICT (user_id, day, kind) DO UPDATE
    SET used = usage_daily.used + 1
    WHERE usage_daily.used < :limit
RETURNING used
""")


async def _charge_one(db: AsyncSession, user_id: str, kind: str, limit: int, scope: str,
                      day: date) -> int:
    # A non-positive limit disables the pool outright. The SQL alone cannot express
    # that: the WHERE guards only the DO UPDATE branch, so the very first action of
    # a day takes the plain INSERT path and slips through whatever the limit says.
    # Handled here so 0 works as a kill switch — the thing you reach for when a
    # public link is being abused and you need it off in one deploy.
    if limit <= 0:
        raise QuotaExceeded(kind, scope, 0, limit)

    row = (await db.execute(
        _CHARGE_SQL, {"user_id": user_id, "day": day, "kind": kind, "limit": limit}
    )).first()
    if row is None:
        used = await get_used(db, user_id, kind, day)
        raise QuotaExceeded(kind, scope, used, limit)
    return row[0]


async def charge(db: AsyncSession, user_id: str | None, kind: str) -> None:
    """Charge one action against the user's pool and the global backstop.

    Both charges share the caller's transaction: if the second raises, the first
    is rolled back with it, so the counters can never drift apart and no refund
    path is needed. Callers must therefore not commit between them.

    A None user_id raises rather than passing through — an uncharged action is
    exactly the hole this exists to close. System paths (the worker, seeds) do
    not call this at all.
    """
    if not user_id:
        raise ValueError(f"charge({kind!r}) needs a user_id; refusing to let an action through uncounted")
    if user_id == GLOBAL_SCOPE:
        raise ValueError(f"{GLOBAL_SCOPE!r} is the reserved backstop row, not a user")

    user_limit, global_limit = limits_for(kind)
    day = today_utc()
    await _charge_one(db, user_id, kind, user_limit, "user", day)
    await _charge_one(db, GLOBAL_SCOPE, kind, global_limit, "global", day)


async def get_used(db: AsyncSession, user_id: str, kind: str, day: date | None = None) -> int:
    row = (await db.execute(
        select(UsageDaily.used).where(
            UsageDaily.user_id == user_id,
            UsageDaily.day == (day or today_utc()),
            UsageDaily.kind == kind,
        )
    )).scalar_one_or_none()
    return int(row or 0)


@dataclass(frozen=True)
class PoolStatus:
    kind: str
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


async def summary_for(db: AsyncSession, user_id: str) -> list[PoolStatus]:
    """Every pool for one user, today. Reads the table directly — deliberately no
    view: V2-E0 had just finished fixing two views that read past RLS because
    they defaulted to the definer's privileges, and adding another would reopen
    exactly that hole."""
    day = today_utc()
    rows = (await db.execute(
        select(UsageDaily.kind, UsageDaily.used).where(
            UsageDaily.user_id == user_id,   # semantic, not security: this table has no RLS
            UsageDaily.day == day,
        )
    )).all()
    used_by_kind = {k: u for k, u in rows}
    return [
        PoolStatus(kind=kind, used=int(used_by_kind.get(kind, 0)), limit=limits_for(kind)[0])
        for kind in POOLS
    ]
