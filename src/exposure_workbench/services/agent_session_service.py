"""Agent session + budget bookkeeping (M10/M11).

Budget state lives in the DB (agent_sessions row), so enforcement is consistent
whether the tool call arrives via the in-process meta-agent, a worker's research
session, or an external MCP host. The wrapper reserves budget BEFORE running a
tool; a rejected call still records a trace step (that happens in the registry).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.db.models import AgentSession
from exposure_workbench.utils.ids import new_session_id


class BudgetExceeded(Exception):
    """A tool call would exceed the session's tool budget (fail-loud, not silent)."""

    def __init__(self, kind: str, used: int, limit: int):
        super().__init__(f"{kind} budget exhausted: {used}/{limit}")
        self.kind = kind
        self.used = used
        self.limit = limit


@dataclass(frozen=True)
class BudgetStatus:
    tools_used: int
    tool_budget: int
    external_searches: int
    external_budget: int


async def create_session(db: AsyncSession, kind: str = "meta", llm_model: str | None = None) -> AgentSession:
    s = get_settings()
    session = AgentSession(
        id=new_session_id(),
        kind=kind,
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
