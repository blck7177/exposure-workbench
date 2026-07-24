"""Filing ingestion (M2) — provider DTOs -> filings / financial_facts.

M2 only MOVES and MAPS data. Any aggregation or ratio (total_debt, FCF, margins)
is a calculation and belongs to M3.

Two orthogonal sub-flows share the `filings` anchor but succeed/fail independently:
  M2a text flow  -> filings / filing_documents / filing_sections   (P3)
  M2b fact flow  -> financial_facts                                (here)

Idempotency:
  * filings         — accession_number is unique; existing accession is skipped.
  * financial_facts — upsert on (company, concept, period_end, dims, accession);
                      a restatement arrives under a different accession and is
                      therefore appended as a NEW row, never overwriting history.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Filing, FinancialFact
from exposure_workbench.providers.filing_provider import FactDTO, FilingMeta, FilingProvider
from exposure_workbench.services.concept_mapping import MAPPING_VERSION, normalize_concept
from exposure_workbench.utils.ids import new_fact_id, new_filing_id

logger = logging.getLogger(__name__)

MVP_FORMS = ["10-K", "10-Q"]

# financial_facts rows bind ~17 params each; Postgres caps a statement at 32767.
_INSERT_CHUNK_ROWS = 1000


def _chunked(rows: list[dict], size: int):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


class NoFilingsFound(RuntimeError):
    def __init__(self, cik: str, forms: list[str]):
        super().__init__(f"EDGAR returned no {forms} filings for CIK {cik!r}")


def dimensions_hash(dimensions: dict | None) -> str:
    """Stable hash so dimensioned facts don't collide on the unique key."""
    if not dimensions:
        return ""
    blob = json.dumps(dimensions, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def build_fact_rows(
    facts: list[FactDTO],
    company_id: str,
    provider_name: str,
    filing_id_by_accession: dict[str, str] | None = None,
) -> list[dict]:
    """Pure DTO -> row mapping. Unmapped concepts are kept with metric=None."""
    by_acc = filing_id_by_accession or {}
    rows: list[dict] = []
    for f in facts:
        quality: dict[str, object] = {}
        if f.is_restated:
            quality["restated"] = True
        if f.data_quality:
            quality["data_quality"] = f.data_quality
        rows.append(
            {
                "id": new_fact_id(),
                # linked only when that filing was itself ingested; source_accession
                # always records provenance regardless.
                "filing_id": by_acc.get(f.source_accession or ""),
                "company_id": company_id,
                "raw_concept": f.raw_concept,
                "normalized_metric": normalize_concept(f.raw_concept),
                "statement_type": f.statement_type,
                "period_start": f.period_start,
                "period_end": f.period_end,
                "fiscal_year": f.fiscal_year,
                "fiscal_quarter": f.fiscal_quarter,
                "value": f.value,
                "unit": f.unit,
                "dimensions": f.dimensions or {},
                "dimensions_hash": dimensions_hash(f.dimensions),
                "provider": provider_name,
                "quality_flags": quality,
                "mapping_version": MAPPING_VERSION,
                "source_accession": f.source_accession,
            }
        )
    return rows


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    """Collapse exact key duplicates within one batch (ON CONFLICT cannot fire
    twice for the same key inside a single statement)."""
    seen: dict[tuple, dict] = {}
    for r in rows:
        key = (r["company_id"], r["raw_concept"], r["period_end"], r["dimensions_hash"], r["source_accession"])
        seen[key] = r
    return list(seen.values())


async def ingest_filings_metadata(
    db: AsyncSession,
    company_id: str,
    cik: str,
    provider: FilingProvider,
    forms: list[str] | None = None,
) -> list[Filing]:
    """Discover + persist the latest 10-K/10-Q metadata. Existing accessions are skipped."""
    forms = forms or MVP_FORMS
    metas: list[FilingMeta] = provider.latest_filings(cik, forms)
    if not metas:
        raise NoFilingsFound(cik, forms)

    persisted: list[Filing] = []
    for m in metas:
        existing = await db.execute(
            select(Filing).where(Filing.accession_number == m.accession_number)
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            persisted.append(row)
            continue
        filing = Filing(
            id=new_filing_id(),
            company_id=company_id,
            accession_number=m.accession_number,
            form_type=m.form_type,
            filing_date=m.filing_date,
            accepted_at=m.accepted_at,
            period_end=m.period_end,
            fiscal_year=m.fiscal_year,
            fiscal_quarter=m.fiscal_quarter,
            source_url=m.source_url,
            is_amendment=m.is_amendment,
            provider=provider.name,
        )
        db.add(filing)
        persisted.append(filing)
    await db.flush()
    return persisted


async def ingest_financial_facts(
    db: AsyncSession,
    company_id: str,
    cik: str,
    provider: FilingProvider,
    since: date | None = None,
) -> int:
    """Fetch XBRL facts and upsert them. One batch = one transaction."""
    facts = provider.fetch_company_facts(cik, since=since)
    if not facts:
        logger.warning("no XBRL facts returned for CIK %s since %s", cik, since)
        return 0

    # Link facts to filings we actually ingested (others keep source_accession only).
    known = await db.execute(select(Filing.accession_number, Filing.id).where(Filing.company_id == company_id))
    by_acc = {acc: fid for acc, fid in known.all()}

    rows = _dedupe_rows(build_fact_rows(facts, company_id, provider.name, by_acc))

    # Postgres caps a statement at 32767 bind parameters; chunk to stay under it.
    # All chunks share the caller's transaction, so the batch stays atomic.
    for chunk in _chunked(rows, _INSERT_CHUNK_ROWS):
        stmt = pg_insert(FinancialFact).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["company_id", "raw_concept", "period_end", "dimensions_hash", "source_accession"],
            set_={
                "value": stmt.excluded.value,
                "normalized_metric": stmt.excluded.normalized_metric,
                "mapping_version": stmt.excluded.mapping_version,
                "quality_flags": stmt.excluded.quality_flags,
            },
        )
        await db.execute(stmt)
    logger.info("ingested %d facts for company %s", len(rows), company_id)
    return len(rows)
