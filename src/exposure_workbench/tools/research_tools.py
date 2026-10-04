"""External research: the web search behind the `web_search` primitive (M6).

Inside a research run the sources belong to the run; in a chat turn there is no run
and `research_run_id` stays NULL — the row is keyed by the company either way, and
the src_ id goes on the session's table through the same declaration. A ticker the
desk has not met is admitted from the listed universe first (company_service.admit);
an ETF or a name with no CIK is refused with its reason, because a source row is
issuer-scoped and there is no issuer to hang it on.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import ResearchRun
from exposure_workbench.services import research_search_service as rss
from exposure_workbench.tools.registry import current_session_id

logger = logging.getLogger(__name__)


async def _run_for_session(db: AsyncSession, session_id: str) -> ResearchRun | None:
    return (
        await db.execute(select(ResearchRun).where(ResearchRun.agent_session_id == session_id))
    ).scalar_one_or_none()


async def _search_external_research(db: AsyncSession, ticker: str, query: str, reason: str,
                                    days: int | None = None) -> dict:
    """Persists results and returns citable src_ ids."""
    from exposure_workbench.services import company_service
    tk = ticker.upper()
    try:
        company = await company_service.admit(db, tk)
    except company_service.CompanyNotFound:
        return {"error": "company_not_found", "ticker": tk,
                "detail": "not a listed symbol in this desk's universe"}
    except (company_service.NotInvestigable, company_service.NotAnSecFiler) as e:
        return {"error": "not_investigable", "ticker": tk, "detail": str(e)}
    run = await _run_for_session(db, current_session_id())
    composed = rss.compose_query(company.name, tk, query)
    try:
        sources = await rss.search(db, company.id, composed, research_run_id=run.id if run else None,
                                   days=days)
    except rss.ResearchProviderUnavailable as e:
        return {"error": "provider_unavailable", "detail": str(e)}
    return {"ticker": tk, "query": composed, "days": days, "reason": reason, "sources": sources}
