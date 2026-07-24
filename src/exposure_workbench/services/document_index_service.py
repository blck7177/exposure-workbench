"""Document index service (M5) — sections -> chunks + embeddings.

Write side of retrieval. Idempotency key is (filing_id, embedding_model): a
filing already indexed under the same model is skipped, so re-running a
readiness pass costs nothing and switching embedding models re-indexes cleanly.

Fail-loud: no API key -> EmbeddingUnavailable propagates and the step fails
visibly. There is no keyword-only degraded index.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Filing, FilingChunk, FilingSection
from exposure_workbench.llm.client import embed_texts
from exposure_workbench.services.section_chunker import chunk_section
from exposure_workbench.utils.ids import new_chunk_id

logger = logging.getLogger(__name__)

EMBED_BATCH = 64


async def is_indexed(db: AsyncSession, filing_id: str, embedding_model: str) -> bool:
    result = await db.execute(
        select(FilingChunk.id)
        .where(FilingChunk.filing_id == filing_id, FilingChunk.embedding_model == embedding_model)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def index_filing(db: AsyncSession, filing: Filing, embedding_model: str | None = None) -> int:
    """Chunk + embed every section of one filing. Returns chunks written."""
    from exposure_workbench.app_state.settings import get_settings

    model = embedding_model or get_settings().embedding_model

    if await is_indexed(db, filing.id, model):
        logger.info("filing %s already indexed under %s — skipping", filing.accession_number, model)
        return 0

    sections = (
        await db.execute(
            select(FilingSection)
            .where(FilingSection.filing_id == filing.id)
            .order_by(FilingSection.section_order)
        )
    ).scalars().all()
    if not sections:
        raise RuntimeError(
            f"filing {filing.accession_number} has no sections to index — run the text flow first"
        )

    # Build every chunk first so embedding happens in efficient batches.
    pending: list[tuple[FilingSection, object]] = []
    for section in sections:
        for chunk in chunk_section(section.text or ""):
            pending.append((section, chunk))
    if not pending:
        raise RuntimeError(f"filing {filing.accession_number} produced no chunks from its sections")

    written = 0
    for start in range(0, len(pending), EMBED_BATCH):
        batch = pending[start : start + EMBED_BATCH]
        vectors, used_model = await embed_texts([c.text for _, c in batch], model=model)
        for (section, chunk), vector in zip(batch, vectors):
            db.add(
                FilingChunk(
                    id=new_chunk_id(),
                    section_id=section.id,
                    filing_id=filing.id,
                    company_id=filing.company_id,
                    chunk_order=chunk.chunk_order,
                    text=chunk.text,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    embedding=vector,
                    embedding_model=used_model,
                    # denormalised retrieval filters (avoid joins at query time)
                    form_type=filing.form_type,
                    filing_date=filing.filing_date,
                    period_end=filing.period_end,
                )
            )
            written += 1
        await db.flush()

    logger.info("indexed %d chunks for filing %s", written, filing.accession_number)
    return written
