"""External research service (M6) — persist search results as citable sources.

Collection and consumption are separated: search() persists results and returns
their source ids; the agent can only cite a src_ id that is actually in the DB.
The relevance score is stored as DATA, never used as a filter — a threshold would
silently drop evidence the audit trail could never show.

Web content is untrusted input. It is stored and later handed to the LLM only as
a quoted source field, never spliced into instructions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import ResearchSource
from exposure_workbench.providers.research_search_provider import ResearchSearchProvider
from exposure_workbench.utils.ids import new_source_id

logger = logging.getLogger(__name__)


class ResearchProviderUnavailable(RuntimeError):
    """No usable research provider (e.g. TAVILY_API_KEY missing) — fail loud."""


def default_provider() -> ResearchSearchProvider:
    """The service owns provider selection, so tools never import a provider.

    Raises ResearchProviderUnavailable (not a silent skip) when unconfigured.
    """
    from exposure_workbench.providers.tavily_research_search_provider import TavilyResearchSearchProvider

    try:
        return TavilyResearchSearchProvider()
    except RuntimeError as e:
        raise ResearchProviderUnavailable(str(e)) from e


async def search(
    db: AsyncSession,
    company_id: str,
    query: str,
    research_run_id: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """Search with the default provider and persist results. Callers (tools) need
    not know which provider is used."""
    return await search_and_persist(
        db, default_provider(), company_id, query,
        research_run_id=research_run_id, max_results=max_results,
    )


async def search_and_persist(
    db: AsyncSession,
    provider: ResearchSearchProvider,
    company_id: str,
    query: str,
    research_run_id: str | None = None,
    max_results: int = 5,
) -> list[dict]:
    """Run one search, persist every result (deduped by url within the run),
    return citable source records."""
    results = provider.search(query, max_results=max_results)

    existing_urls = set()
    if research_run_id:
        rows = await db.execute(
            select(ResearchSource.url).where(ResearchSource.research_run_id == research_run_id)
        )
        existing_urls = {u for (u,) in rows.all()}

    persisted: list[dict] = []
    for r in results:
        if r.url in existing_urls:
            continue
        existing_urls.add(r.url)
        src_id = new_source_id()
        db.add(
            ResearchSource(
                id=src_id,
                research_run_id=research_run_id,
                company_id=company_id,
                title=r.title,
                url=r.url,
                publisher_domain=r.publisher_domain,
                published_date=r.published_date,
                search_query=query,
                relevance_score=r.relevance_score,
                snippet=r.snippet,
                provider=provider.name,
            )
        )
        persisted.append({
            "type": "source", "id": src_id, "title": r.title, "url": r.url,
            "publisher": r.publisher_domain,
            "published_date": r.published_date.isoformat() if r.published_date else None,
            "snippet": r.snippet, "relevance_score": r.relevance_score,
        })
    await db.flush()
    logger.info("persisted %d new sources for query %r", len(persisted), query)
    return persisted


async def list_sources(db: AsyncSession, company_id: str, research_run_id: str | None = None) -> list[dict]:
    q = select(ResearchSource).where(ResearchSource.company_id == company_id)
    if research_run_id:
        q = q.where(ResearchSource.research_run_id == research_run_id)
    q = q.order_by(ResearchSource.retrieved_at.desc())
    rows = (await db.execute(q)).scalars().all()
    return [{
        "type": "source", "id": s.id, "title": s.title, "url": s.url,
        "publisher": s.publisher_domain,
        "published_date": s.published_date.isoformat() if s.published_date else None,
        "snippet": s.snippet, "search_query": s.search_query,
    } for s in rows]
