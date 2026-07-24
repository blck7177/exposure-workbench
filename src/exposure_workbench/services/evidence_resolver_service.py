"""Evidence resolver (M11) — one endpoint resolves any evidence id.

Every citable id (fact_/calc_/chunk_/src_/alert_) resolves through here to a
uniform envelope {type, body, provenance, upstream}. The UI's citation chip,
evidence drawer, brief rendering and agent monitor all call this one resolver, so
drill-through is one component, not per-page fetch logic. `upstream` lets the
drawer keep drilling (a calc -> its input facts -> the filing).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import (
    CalcLedger,
    Company,
    Filing,
    FilingChunk,
    FilingSection,
    FinancialFact,
    ResearchSource,
    RiskAlert,
)


class EvidenceNotFound(Exception):
    def __init__(self, ref_id: str):
        super().__init__(f"no evidence for id {ref_id!r}")
        self.ref_id = ref_id


async def _fact(db: AsyncSession, fid: str) -> dict | None:
    row = (await db.execute(select(FinancialFact).where(FinancialFact.id == fid))).scalar_one_or_none()
    if row is None:
        return None
    accession = None
    if row.filing_id:
        accession = (await db.execute(select(Filing.accession_number).where(Filing.id == row.filing_id))).scalar_one_or_none()
    return {
        "type": "fact", "id": fid,
        "body": {
            "raw_concept": row.raw_concept, "normalized_metric": row.normalized_metric,
            "value": float(row.value) if row.value is not None else None, "unit": row.unit,
            "period_start": row.period_start.isoformat() if row.period_start else None,
            "period_end": row.period_end.isoformat() if row.period_end else None,
        },
        "provenance": {
            "source_accession": row.source_accession or accession,
            "provider": row.provider, "mapping_version": row.mapping_version,
            "quality_flags": row.quality_flags,
        },
        "upstream": [],
    }


async def _calc(db: AsyncSession, cid: str) -> dict | None:
    row = (await db.execute(select(CalcLedger).where(CalcLedger.id == cid))).scalar_one_or_none()
    if row is None:
        return None
    return {
        "type": "calc", "id": cid,
        "body": {"operation": row.operation, "params": row.params, "result": row.result},
        "provenance": {"primitive_version": row.primitive_version, "invoked_by": row.invoked_by,
                       "created_at": row.created_at.isoformat() if row.created_at else None},
        # upstream = the fact/calc ids this calculation consumed (keep drilling)
        "upstream": [{"type": "fact" if r.startswith("fact_") else "calc" if r.startswith("calc_") else "ref", "id": r}
                     for r in (row.input_refs or []) if isinstance(r, str)],
    }


async def _chunk(db: AsyncSession, chid: str) -> dict | None:
    row = (await db.execute(select(FilingChunk).where(FilingChunk.id == chid))).scalar_one_or_none()
    if row is None:
        return None
    filing = (await db.execute(select(Filing).where(Filing.id == row.filing_id))).scalar_one_or_none()
    item = title = None
    if row.section_id:
        sec = (await db.execute(select(FilingSection).where(FilingSection.id == row.section_id))).scalar_one_or_none()
        if sec:
            item, title = sec.item_code, sec.title
    return {
        "type": "chunk", "id": chid,
        "body": {"text": row.text, "item": item, "section_title": title,
                 "char_span": [row.char_start, row.char_end]},
        "provenance": {
            "accession": filing.accession_number if filing else None,
            "form_type": row.form_type,
            "filing_date": row.filing_date.isoformat() if row.filing_date else None,
            "source_url": filing.source_url if filing else None,
        },
        "upstream": [],
    }


async def _source(db: AsyncSession, sid: str) -> dict | None:
    row = (await db.execute(select(ResearchSource).where(ResearchSource.id == sid))).scalar_one_or_none()
    if row is None:
        return None
    return {
        "type": "source", "id": sid,
        "body": {"title": row.title, "snippet": row.snippet, "search_query": row.search_query},
        "provenance": {"url": row.url, "publisher": row.publisher_domain,
                       "published_date": row.published_date.isoformat() if row.published_date else None,
                       "provider": row.provider,
                       "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None},
        "upstream": [],
    }


async def _alert(db: AsyncSession, aid: str) -> dict | None:
    row = (await db.execute(select(RiskAlert).where(RiskAlert.id == aid))).scalar_one_or_none()
    if row is None:
        return None
    return {
        "type": "alert", "id": aid,
        "body": {"alert_type": row.alert_type, "severity": row.severity, "message": row.message,
                 "entity_id": row.entity_id,
                 "utilization": float(row.utilization) if row.utilization is not None else None},
        "provenance": {"run_id": row.run_id},
        "upstream": [],
    }


_RESOLVERS = {
    "fact_": _fact,
    "calc_": _calc,
    "chunk_": _chunk,
    "src_": _source,
    "alert_": _alert,
}


async def resolve(db: AsyncSession, ref_id: str) -> dict:
    for prefix, fn in _RESOLVERS.items():
        if ref_id.startswith(prefix):
            result = await fn(db, ref_id)
            if result is None:
                raise EvidenceNotFound(ref_id)
            return result
    raise EvidenceNotFound(ref_id)
