"""ResearchSearchProvider boundary (M6) — external web research.

DTOs only; the concrete client (Tavily) is consumed in the implementation. The
LLM never sees raw web content except as a persisted, cited source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class SearchResultDTO:
    title: str | None
    url: str
    snippet: str | None
    publisher_domain: str | None = None
    published_date: date | None = None
    relevance_score: float | None = None


class ResearchSearchProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int = 5, days: int | None = None) -> list[SearchResultDTO]:
        """`days`, when given, restricts results to news published within that many days."""
        ...
