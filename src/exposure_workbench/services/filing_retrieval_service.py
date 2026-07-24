"""Filing retrieval (M5) — read side. Two orthogonal tools, not one with a fallback.

  search_passages()  -> FIND WHERE: semantic search across a company's indexed
                        filings, returning passages with full citation anchors.
  get_section()      -> READ WHOLE: fetch one Item verbatim.

Both exist deliberately. Search alone biases an agent toward reasoning from four
disconnected snippets; being able to pull the whole Item is the structural
answer to that, not a fallback.

"Not indexed" and "found nothing" are DIFFERENT facts and are reported
differently — conflating them is the most insidious kind of silent failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Filing, FilingChunk, FilingSection
from exposure_workbench.llm.client import embed_texts

logger = logging.getLogger(__name__)

MAX_K = 10


class NotIndexed(Exception):
    """The company has no indexed chunks — a data-readiness problem, NOT an empty
    result set. Callers must surface this distinctly from 'no matches'."""

    def __init__(self, company_id: str):
        super().__init__(f"No indexed filing chunks for company {company_id!r}")
        self.company_id = company_id


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    text: str
    score: float
    # citation anchor — everything needed to cite without another query
    company_id: str
    accession_number: str
    form_type: str | None
    filing_date: date | None
    item_code: str | None
    section_title: str | None
    char_start: int | None
    char_end: int | None
    source_url: str | None

    def citation(self) -> dict:
        return {
            "type": "chunk",
            "id": self.chunk_id,
            "accession": self.accession_number,
            "form_type": self.form_type,
            "filing_date": self.filing_date.isoformat() if self.filing_date else None,
            "item": self.item_code,
            "char_span": [self.char_start, self.char_end],
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class SectionView:
    section_id: str
    item_code: str | None
    title: str | None
    text: str
    accession_number: str
    form_type: str | None
    filing_date: date | None
    source_url: str | None


async def _has_index(db: AsyncSession, company_id: str) -> bool:
    r = await db.execute(select(FilingChunk.id).where(FilingChunk.company_id == company_id).limit(1))
    return r.scalar_one_or_none() is not None


async def search_passages(
    db: AsyncSession,
    company_id: str,
    query: str,
    k: int = 5,
    form_type: str | None = None,
    item_code: str | None = None,
    filed_after: date | None = None,
) -> list[Passage]:
    """Vector search across ALL indexed filings of one company (10-K + 10-Q together).

    Defaults to full coverage because questions like 'what risks were added?'
    are inherently cross-filing; filters narrow it when the caller wants that.
    """
    if not await _has_index(db, company_id):
        raise NotIndexed(company_id)

    k = max(1, min(int(k), MAX_K))
    vectors, _ = await embed_texts([query])
    qvec = vectors[0]

    stmt = (
        select(
            FilingChunk,
            Filing.accession_number,
            Filing.source_url,
            FilingSection.item_code,
            FilingSection.title,
            FilingChunk.embedding.cosine_distance(qvec).label("distance"),
        )
        .join(Filing, Filing.id == FilingChunk.filing_id)
        .outerjoin(FilingSection, FilingSection.id == FilingChunk.section_id)
        .where(FilingChunk.company_id == company_id)
    )
    if form_type:
        stmt = stmt.where(FilingChunk.form_type == form_type)
    if filed_after:
        stmt = stmt.where(FilingChunk.filing_date >= filed_after)
    if item_code:
        stmt = stmt.where(FilingSection.item_code.ilike(f"%{item_code}%"))
    stmt = stmt.order_by("distance").limit(k)

    rows = (await db.execute(stmt)).all()
    return [
        Passage(
            chunk_id=chunk.id,
            text=chunk.text,
            score=1.0 - float(distance),          # cosine similarity
            company_id=chunk.company_id,
            accession_number=accession,
            form_type=chunk.form_type,
            filing_date=chunk.filing_date,
            item_code=item,
            section_title=title,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            source_url=url,
        )
        for chunk, accession, url, item, title, distance in rows
    ]


async def get_section(
    db: AsyncSession,
    company_id: str,
    item_code: str,
    form_type: str | None = None,
) -> SectionView | None:
    """Read one Item verbatim from the company's most recent matching filing."""
    stmt = (
        select(FilingSection, Filing)
        .join(Filing, Filing.id == FilingSection.filing_id)
        .where(Filing.company_id == company_id, FilingSection.item_code.ilike(f"%{item_code}%"))
    )
    if form_type:
        stmt = stmt.where(Filing.form_type == form_type)
    stmt = stmt.order_by(Filing.filing_date.desc(), FilingSection.section_order)

    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    section, filing = row
    return SectionView(
        section_id=section.id,
        item_code=section.item_code,
        title=section.title,
        text=section.text or "",
        accession_number=filing.accession_number,
        form_type=filing.form_type,
        filing_date=filing.filing_date,
        source_url=filing.source_url,
    )
