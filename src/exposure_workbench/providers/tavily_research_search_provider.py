"""Tavily implementation of ResearchSearchProvider (M6).

Tavily objects are consumed here; callers get SearchResultDTO. Fail-loud: a
missing TAVILY_API_KEY raises at construction, not deep inside a research step.
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import urlparse

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.providers.research_search_provider import SearchResultDTO

logger = logging.getLogger(__name__)


def _domain(url: str) -> str | None:
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith("www.") else host or None
    except Exception:
        return None


def _parse_date(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


class TavilyResearchSearchProvider:
    name = "tavily"

    def __init__(self) -> None:
        key = (get_settings().tavily_api_key or "").strip()
        if not key:
            raise RuntimeError("TAVILY_API_KEY is not set — external research cannot run.")
        from tavily import TavilyClient

        self._client = TavilyClient(api_key=key)

    def search(self, query: str, max_results: int = 5, days: int | None = None) -> list[SearchResultDTO]:
        # A day window is Tavily's news topic: "the past week" is `days=7` on
        # the request, not a phrase in the query the engine may or may not read.
        kwargs = {"topic": "news", "days": int(days)} if days else {}
        resp = self._client.search(query=query, max_results=max_results, **kwargs)
        out: list[SearchResultDTO] = []
        for r in resp.get("results", []):
            url = r.get("url")
            if not url:
                continue
            out.append(
                SearchResultDTO(
                    title=r.get("title"),
                    url=url,
                    snippet=r.get("content"),
                    publisher_domain=_domain(url),
                    published_date=_parse_date(r.get("published_date")),
                    relevance_score=r.get("score"),
                )
            )
        return out
