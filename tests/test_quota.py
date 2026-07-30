"""E3 — daily quota wiring invariants (offline: no DB, no network).

The counter itself is a conditional upsert, so its branches are verified against
a real database in test_quota_live.py. What matters here is the wiring that a
future change is most likely to break silently: an action that reaches a charge
point with no pool behind it would become free, which is the exact hole the
quota exists to close. Every gap below fails loudly instead.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from exposure_workbench.app_state.settings import Settings
from exposure_workbench.services import task_service, usage_service


def test_every_task_type_maps_to_a_pool():
    """create_task is one of only two charge points; a type missing from the map
    must raise KeyError there rather than enqueue work for free."""
    from tests.test_task_lease import DISPATCHABLE
    assert set(task_service.TASK_TYPE_QUOTA_KIND) == DISPATCHABLE


def test_every_mapped_kind_is_a_registered_pool():
    for task_type, kind in task_service.TASK_TYPE_QUOTA_KIND.items():
        assert kind in usage_service.POOLS, f"{task_type} maps to unknown pool {kind!r}"


@pytest.mark.parametrize(
    "kind", ["chat_turn", "portfolio_create", "position_upload", "agent_session"]
)
def test_inline_pools_are_not_also_reachable_from_a_task_type(kind):
    """These four are charged at their own sites, not through create_task,
    because they create rows inline instead of enqueuing work. Wiring any of
    them to a task type as well would charge the action twice."""
    assert kind in usage_service.POOLS
    assert kind not in task_service.TASK_TYPE_QUOTA_KIND.values()


def test_unknown_task_type_raises_rather_than_passing_through_free():
    with pytest.raises(KeyError):
        task_service.TASK_TYPE_QUOTA_KIND["some_new_task_type"]


def test_every_pool_has_both_a_user_and_a_global_limit():
    s = Settings()
    for kind, (user_attr, global_attr) in usage_service.POOLS.items():
        assert hasattr(s, user_attr), f"{kind}: missing {user_attr}"
        assert hasattr(s, global_attr), f"{kind}: missing {global_attr}"
        assert getattr(s, global_attr) >= getattr(s, user_attr), (
            f"{kind}: the shared backstop must not be tighter than one user's share"
        )


def test_pool_defaults_match_the_published_plan():
    """Pinned because these are the numbers a public visitor actually gets."""
    s = Settings()
    assert (s.daily_chat_turns, s.daily_research_runs, s.daily_readiness,
            s.daily_exposure_runs, s.daily_market_syncs) == (10, 3, 10, 20, 10)
    assert (s.global_daily_chat_turns, s.global_daily_research_runs, s.global_daily_readiness,
            s.global_daily_exposure_runs, s.global_daily_market_syncs) == (200, 30, 100, 200, 50)
    assert (s.daily_portfolio_creates, s.daily_position_uploads,
            s.daily_agent_sessions) == (5, 10, 5)
    assert (s.global_daily_portfolio_creates, s.global_daily_position_uploads,
            s.global_daily_agent_sessions) == (100, 100, 100)
    assert s.turn_lease_seconds == 900


def test_every_pool_is_pinned_by_the_test_above():
    """The pin is a literal tuple, so it does not fail when a pool is ADDED — it
    just stops covering it. This is the guard on the guard: a new pool ships with
    its numbers unasserted unless someone extends the tuple."""
    pinned = {
        "chat_turn", "research_run", "readiness", "exposure_run", "market_sync",
        "portfolio_create", "position_upload", "agent_session",
    }
    assert set(usage_service.POOLS) == pinned, (
        "a pool was added or removed without updating test_pool_defaults_match_the_published_plan"
    )


async def test_charge_refuses_an_anonymous_action():
    """A None user_id is the one case that must never silently pass: an uncounted
    action is precisely what the quota exists to prevent."""
    with pytest.raises(ValueError):
        await usage_service.charge(None, None, "chat_turn")  # type: ignore[arg-type]


async def test_charge_refuses_the_reserved_backstop_id():
    with pytest.raises(ValueError):
        await usage_service.charge(None, usage_service.GLOBAL_SCOPE, "chat_turn")  # type: ignore[arg-type]


def test_global_scope_cannot_collide_with_a_clerk_id():
    """Clerk ids are 'user_'-prefixed; the backstop row must be unmistakably not one."""
    assert not usage_service.GLOBAL_SCOPE.startswith("user_")


def test_limits_for_unknown_kind_raises():
    with pytest.raises(KeyError):
        usage_service.limits_for("not_a_pool")


def test_next_reset_is_the_next_utc_midnight():
    reset = datetime.fromisoformat(usage_service.next_reset_at())
    now = datetime.now(timezone.utc)
    assert reset.utcoffset() == timedelta(0), "quota days are UTC, so the reset must be too"
    assert (reset.hour, reset.minute, reset.second) == (0, 0, 0)
    assert now < reset <= now + timedelta(days=1), "the next midnight is always within 24h"


def test_quota_exceeded_carries_the_whole_account():
    e = usage_service.QuotaExceeded("research_run", "user", 3, 3)
    d = e.as_dict()
    assert d["error"] == "quota_exceeded"
    assert (d["kind"], d["scope"], d["used"], d["limit"]) == ("research_run", "user", 3, 3)
    assert d["resets_at"], "the user needs to know when it comes back"


def test_charge_sql_only_increments_below_the_limit():
    """The WHERE on the DO UPDATE is the whole concurrency story — without it two
    requests could both take the last unit."""
    sql = str(usage_service._CHARGE_SQL)
    assert "ON CONFLICT (user_id, day, kind) DO UPDATE" in sql
    assert "WHERE usage_daily.used < :limit" in sql
    assert "RETURNING used" in sql


@pytest.mark.parametrize("kind", sorted(usage_service.POOLS))
def test_a_zero_limit_is_a_working_kill_switch(kind):
    """The SQL alone cannot express this: the WHERE clause guards only the DO
    UPDATE branch, so the first action of a day takes the plain INSERT path and
    slips through whatever the limit says. Setting a pool to 0 is what you reach
    for when a public link is being abused, so it has to actually stop things.

    Parametrized over every pool, not just chat_turn: the fix lives in the shared
    _charge_one, so this asserts that a new pool inherits it rather than that
    someone remembered to re-apply it."""
    import asyncio
    for limit in (0, -1):
        with pytest.raises(usage_service.QuotaExceeded) as e:
            asyncio.run(usage_service._charge_one(None, "user_x", kind, limit, "user",
                                                  __import__("datetime").date(2026, 7, 28)))
        assert e.value.limit == limit
        assert e.value.used == 0


def test_market_sync_is_bounded_so_one_unit_cannot_buy_the_afternoon():
    from apps.api.routes import market_data
    assert market_data.MAX_SYNC_TICKERS <= 100
    assert market_data.MAX_LOOKBACK_DAYS <= 365 * 10
    fields = market_data.SyncRequest.model_fields
    assert any(getattr(m, "max_length", None) == market_data.MAX_SYNC_TICKERS
               for m in fields["tickers"].metadata), "ticker list must carry a cap"
