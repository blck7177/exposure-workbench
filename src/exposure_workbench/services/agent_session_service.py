"""Agent session + budget bookkeeping (M10/M11).

Budget state lives in the DB (agent_sessions row), so enforcement is consistent
whether the tool call arrives via the in-process meta-agent, a worker's research
session, or an external MCP host. The wrapper reserves budget BEFORE running a
tool; a rejected call still records a trace step (that happens in the registry).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.db.models import AgentSession
from exposure_workbench.db.session import get_session_factory
from exposure_workbench.utils.ids import new_session_id


class BudgetExceeded(Exception):
    """A tool call would exceed the session's tool budget (fail-loud, not silent)."""

    def __init__(self, kind: str, used: int, limit: int):
        super().__init__(f"{kind} budget exhausted: {used}/{limit}")
        self.kind = kind
        self.used = used
        self.limit = limit


class TurnInFlight(Exception):
    """This session already has a turn running (V2-E2)."""

    def __init__(self, session_id: str):
        super().__init__(f"a turn is already in flight for session {session_id!r}")
        self.session_id = session_id


@dataclass(frozen=True)
class BudgetStatus:
    tools_used: int
    tool_budget: int
    external_searches: int
    external_budget: int


async def create_session(
    db: AsyncSession, kind: str = "meta", llm_model: str | None = None, owner_id: str | None = None,
) -> AgentSession:
    s = get_settings()
    session = AgentSession(
        id=new_session_id(),
        kind=kind,
        owner_id=owner_id,   # V2-A tenancy
        llm_model=llm_model or s.openai_model,
        tool_budget=s.session_tool_budget,
        tools_used=0,
        external_searches=0,
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(db: AsyncSession, session_id: str) -> AgentSession | None:
    return (await db.execute(select(AgentSession).where(AgentSession.id == session_id))).scalar_one_or_none()


# One in-flight turn per session (V2-E2). Server time on both sides: with more
# than one API replica a skewed client clock would either steal a live turn or
# strand a dead one. Nothing renews the lease — a turn whose process died frees
# itself once turn_lease_seconds have passed.
_CLAIM_TURN_SQL = text("""
UPDATE agent_sessions
   SET turn_started_at = now()
 WHERE id = :session_id
   AND (turn_started_at IS NULL
        OR turn_started_at < now() - make_interval(secs => :lease_secs))
RETURNING turn_started_at
""")


async def claim_turn(db: AsyncSession, session_id: str):
    """Take this session's single turn slot. Returns the stamp written, or None
    if a turn is already in flight.

    The stamp is the fence token: pass it back to release_turn so a turn that has
    been superseded cannot free its replacement's slot on the way out.

    Runs on the CALLER's session so it can share a transaction with the quota
    charge — over-quota then rolls the claim back with it, which is why there is
    no "release on the rejection path" special case anywhere.

    That transaction must be a SHORT one of its own, never the request-scoped
    db: get_db holds its transaction until the route returns, so an uncommitted
    claim would keep a row lock for the whole turn while reserve() — on a
    different connection, once per tool call — waits on it. Postgres would not
    report a deadlock (one side is waiting on application logic, not a lock), so
    the request would simply hang forever.

    Cross-user calls get False rather than a 403: agent_sessions' policy is FOR
    ALL, so another tenant's row is invisible to the UPDATE as well as to SELECT.
    Separating that from a genuine conflict is what the route's 404 precheck is
    for; without it, "not yours" and "busy" collapse into one 0-row answer.
    """
    row = (await db.execute(
        _CLAIM_TURN_SQL,
        {"session_id": session_id, "lease_secs": get_settings().turn_lease_seconds},
    )).first()
    return row[0] if row is not None else None


async def release_turn(session_id: str, claimed_at=None) -> None:
    """Free the turn slot. Opens its own session and commits immediately.

    Called from a finally, which is the whole point: the request-scoped session
    rolls back on the error paths, and those are exactly the ones that must still
    release. Never raises — a failure here costs at most turn_lease_seconds of
    availability for one session, and letting it escape would mask the original
    error that sent us into the finally.
    """
    try:
        factory = get_session_factory()
        async with factory() as db, db.begin():
            # Fenced on the stamp we claimed. A turn whose lease expired has
            # already been superseded, and an unfenced release would clear the
            # REPLACEMENT's slot on its way out — letting a third turn start
            # while the second is still running, which is the one invariant this
            # whole mechanism exists to hold. Same reasoning as the fence on
            # complete_task/fail_task in task_service.
            stmt = update(AgentSession).where(AgentSession.id == session_id)
            if claimed_at is not None:
                stmt = stmt.where(AgentSession.turn_started_at == claimed_at)
            await db.execute(stmt.values(turn_started_at=None))
    except Exception:   # noqa: BLE001 — see docstring; expiry is the backstop
        pass


async def reserve(db: AsyncSession, session_id: str, *, is_external_search: bool) -> BudgetStatus:
    """Atomically reserve one tool call (and one external search if applicable).

    Uses a conditional UPDATE so concurrent calls can't both slip past the last
    unit of budget. Raises BudgetExceeded without mutating state when over limit.
    """
    settings = get_settings()
    session = await get_session(db, session_id)
    if session is None:
        raise ValueError(f"unknown session {session_id!r}")

    tool_limit = session.tool_budget or settings.session_tool_budget
    ext_limit = settings.external_search_budget

    if session.tools_used >= tool_limit:
        raise BudgetExceeded("tool", session.tools_used, tool_limit)
    if is_external_search and session.external_searches >= ext_limit:
        raise BudgetExceeded("external_search", session.external_searches, ext_limit)

    ext_inc = 1 if is_external_search else 0
    result = await db.execute(
        update(AgentSession)
        .where(
            AgentSession.id == session_id,
            AgentSession.tools_used < tool_limit,
            (AgentSession.external_searches < ext_limit) if is_external_search else (AgentSession.id == session_id),
        )
        .values(
            tools_used=AgentSession.tools_used + 1,
            external_searches=AgentSession.external_searches + ext_inc,
        )
        .returning(AgentSession.tools_used, AgentSession.external_searches)
    )
    row = result.first()
    if row is None:
        # Lost the race for the last unit.
        raise BudgetExceeded("tool", tool_limit, tool_limit)
    return BudgetStatus(row[0], tool_limit, row[1], ext_limit)
