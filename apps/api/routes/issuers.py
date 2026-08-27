"""Issuer read routes (M11/M13) — the data behind the issuer workspace tabs.

Pure reads. The UI renders these; every number carries the id needed to drill
through /api/evidence/{id}.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import optional_user
from exposure_workbench.db.models import (
    CalcLedger, Company, Filing, FilingSection, IssuerBrief, IssuerExposure,
    ResearchRun, ResearchSource,
)
from exposure_workbench.db.session import get_db
from exposure_workbench.services import calc_service, company_service
from exposure_workbench.services import evidence_resolver_service as ev

router = APIRouter()


async def _company(db: AsyncSession, ticker: str) -> Company:
    try:
        return await company_service.get_by_ticker(db, ticker.upper())
    except company_service.CompanyNotFound:
        raise HTTPException(404, {"error": "unknown_ticker", "ticker": ticker.upper()})


# ── evidence resolver (the drill-through endpoint) ────────────────────────────────

@router.get("/evidence/{ref_id}", dependencies=[Depends(optional_user)])
async def get_evidence(ref_id: str, db: AsyncSession = Depends(get_db)):
    # optional_user sets the tenant so run_/alert_ evidence for the caller's own
    # runs resolves (public demo evidence resolves anonymously via is_public).
    try:
        return await ev.resolve(db, ref_id)
    except ev.EvidenceNotFound:
        raise HTTPException(404, f"no evidence for {ref_id}")


# ── companies list (for the portfolio -> investigate entry) ───────────────────────

@router.get("/companies", dependencies=[Depends(optional_user)])
async def list_companies(db: AsyncSession = Depends(get_db)):
    rows = await company_service.list_companies(db)
    return [{"ticker": c.ticker, "name": c.name, "sector": c.sector,
             "is_investigable": c.is_investigable} for c in rows]


# ── snapshot tab ──────────────────────────────────────────────────────────────────

@router.get("/issuers/{ticker}/snapshot", dependencies=[Depends(optional_user)])
async def snapshot(ticker: str, db: AsyncSession = Depends(get_db)):
    c = await _company(db, ticker)
    metrics = await calc_service.list_available_metrics(db, c.ticker)
    latest_filing = (await db.execute(
        select(Filing).where(Filing.company_id == c.id).order_by(Filing.filing_date.desc())
    )).scalars().first()
    exposure = (await db.execute(
        select(IssuerExposure).where(IssuerExposure.ticker == c.ticker).order_by(IssuerExposure.created_at.desc())
    )).scalars().first()
    return {
        "company": {"ticker": c.ticker, "name": c.name, "cik": c.cik, "exchange": c.exchange,
                    "sector": c.sector, "industry": c.industry, "is_investigable": c.is_investigable},
        "latest_filing": None if latest_filing is None else {
            "form_type": latest_filing.form_type, "filing_date": latest_filing.filing_date.isoformat(),
            "accession": latest_filing.accession_number, "source_url": latest_filing.source_url,
        },
        "portfolio_exposure": None if exposure is None else {
            "market_value": float(exposure.market_value) if exposure.market_value else None,
            "weight": float(exposure.weight) if exposure.weight else None,
            "daily_return": float(exposure.daily_return) if exposure.daily_return else None,
        },
        "available_metrics": metrics["metrics"],
    }


# ── financials tab (recipe ledger rows, each with a calc_id chip) ─────────────────

@router.get("/issuers/{ticker}/financials", dependencies=[Depends(optional_user)])
async def financials(ticker: str, db: AsyncSession = Depends(get_db)):
    """The baseline rows the latest recipe run produced, by label.

    V10-S3: read from the recipe's manifest row rather than by scanning the
    ledger for `invoked_by = 'recipe'` and keying on `params.series.metric`.
    The scan worked only because every v1 row carried the metric name in the
    same place; a v2 yoy row carries the id of the series it was taken over,
    which is a different id on every run, so "latest row per metric" had
    nothing stable to key on. The manifest names each label's row explicitly.
    An issuer whose readiness has not run since v2 has no manifest and gets an
    empty list with the reason — not the v1 rows under v2's name.
    """
    from exposure_workbench.services.recipe import OP_MANIFEST
    c = await _company(db, ticker)
    manifest = (await db.execute(
        select(CalcLedger).where(CalcLedger.company_id == c.ticker,
                                 CalcLedger.operation == OP_MANIFEST)
        .order_by(CalcLedger.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if manifest is None:
        return {"ticker": c.ticker, "calcs": [],
                "note": "no baseline computed by the current recipe yet — run readiness"}
    labels: dict = (manifest.result or {}).get("labels") or {}
    ids = [v for v in labels.values() if isinstance(v, str)]
    rows = {r.id: r for r in (await db.execute(
        select(CalcLedger).where(CalcLedger.id.in_(ids)))).scalars().all()} if ids else {}
    calcs = []
    for label, ref in labels.items():
        if isinstance(ref, str) and ref in rows:
            r = rows[ref]
            calcs.append({"label": label, "calc_id": r.id, "operation": r.operation,
                          "params": r.params, "result": r.result,
                          "primitive_version": r.primitive_version})
        else:
            calcs.append({"label": label, "calc_id": None, "operation": None, "params": {},
                          "result": None, "primitive_version": None,
                          "unavailable": (ref or {}).get("reason") if isinstance(ref, dict) else "missing"})
    return {"ticker": c.ticker, "calcs": calcs,
            "recipe_version": (manifest.params or {}).get("recipe_version"),
            "as_of": (manifest.params or {}).get("as_of")}


# ── filings tab ────────────────────────────────────────────────────────────────────

@router.get("/issuers/{ticker}/filings", dependencies=[Depends(optional_user)])
async def filings(ticker: str, db: AsyncSession = Depends(get_db)):
    c = await _company(db, ticker)
    rows = (await db.execute(
        select(Filing).where(Filing.company_id == c.id).order_by(Filing.filing_date.desc())
    )).scalars().all()
    out = []
    for f in rows:
        secs = (await db.execute(
            select(FilingSection.id, FilingSection.item_code, FilingSection.title)
            .where(FilingSection.filing_id == f.id).order_by(FilingSection.section_order)
        )).all()
        out.append({
            "accession": f.accession_number, "form_type": f.form_type,
            "filing_date": f.filing_date.isoformat(), "period_end": f.period_end.isoformat() if f.period_end else None,
            "source_url": f.source_url,
            "sections": [{"id": sid, "item_code": ic, "title": t} for sid, ic, t in secs],
        })
    return {"ticker": c.ticker, "filings": out}


@router.get("/filing-sections/{section_id}", dependencies=[Depends(optional_user)])
async def filing_section(section_id: str, db: AsyncSession = Depends(get_db)):
    sec = (await db.execute(select(FilingSection).where(FilingSection.id == section_id))).scalar_one_or_none()
    if sec is None:
        raise HTTPException(404, "section not found")
    return {"id": sec.id, "item_code": sec.item_code, "title": sec.title, "text": sec.text}


# ── research tab ───────────────────────────────────────────────────────────────────

@router.get("/issuers/{ticker}/research-sources", dependencies=[Depends(optional_user)])
async def research_sources(ticker: str, db: AsyncSession = Depends(get_db)):
    c = await _company(db, ticker)
    rows = (await db.execute(
        select(ResearchSource).where(ResearchSource.company_id == c.id)
        .order_by(ResearchSource.retrieved_at.desc())
    )).scalars().all()
    return {"ticker": c.ticker, "sources": [
        {"id": s.id, "title": s.title, "url": s.url, "publisher": s.publisher_domain,
         "published_date": s.published_date.isoformat() if s.published_date else None,
         "snippet": s.snippet, "search_query": s.search_query} for s in rows
    ]}


# ── latest brief for an issuer ─────────────────────────────────────────────────────

@router.get("/issuers/{ticker}/latest-brief", dependencies=[Depends(optional_user)])
async def latest_brief(ticker: str, db: AsyncSession = Depends(get_db)):
    c = await _company(db, ticker)
    brief = (await db.execute(
        select(IssuerBrief).where(IssuerBrief.company_id == c.id).order_by(IssuerBrief.created_at.desc())
    )).scalars().first()
    if brief is None:
        return {"ticker": c.ticker, "brief": None}
    return {"ticker": c.ticker, "brief": {
        "id": brief.id, "research_run_id": brief.research_run_id,
        "financial_summary": brief.financial_summary, "key_changes": brief.key_changes,
        "management_explanation": brief.management_explanation, "market_context": brief.market_context,
        "portfolio_implications": brief.portfolio_implications, "open_questions": brief.open_questions,
        "citations": brief.citations, "confidence_flags": brief.confidence_flags,
        "created_at": brief.created_at.isoformat() if brief.created_at else None,
    }}
