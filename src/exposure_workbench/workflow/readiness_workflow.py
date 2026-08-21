"""Company readiness workflow (M8, capability A) — make an issuer's data ready.

All mechanical, all idempotent: resolve identity, ingest filings + facts, index
them, refresh prices, compute the baseline recipe. Re-running is cheap (each step
skips work already done). This is a SEPARATE task type from issuer_research, so
answering a quick question can trigger readiness without a full research run.

Fail-loud: any step failure aborts the run visibly. Prices can be skipped only by
explicit request (skip_market_refresh), recorded as 'skipped', never silently.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company, Filing
from exposure_workbench.providers.edgartools_filing_provider import EdgarToolsFilingProvider
from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider
from exposure_workbench.services import company_service
from exposure_workbench.services import document_index_service as dix
from exposure_workbench.services import filing_ingestion_service as fis
from exposure_workbench.services import market_data_ingestion_service as mds
from exposure_workbench.services import recipe
from exposure_workbench.workflow.step_context import mark_skipped, step

logger = logging.getLogger(__name__)

_FACTS_SINCE_DAYS = 365 * 6      # ~6 fiscal years of history


async def run_readiness(
    db: AsyncSession,
    run_id: str,
    ticker: str,
    skip_market_refresh: bool = False,
) -> dict:
    """Execute the readiness steps for one issuer. Raises on failure (fail-loud)."""
    ticker = ticker.upper()
    filing_provider = EdgarToolsFilingProvider()
    # ONE clock reading for the whole run. The price refresh and the recipe's
    # return windows have to agree on what "now" is, or the recipe measures a
    # window whose last day was never ingested — and a run that straddles
    # midnight would use two different days for the two steps.
    as_of = date.today()

    # 1) resolve + enrich company identity (EDGAR is the write-path authority)
    async with step(db, run_id, "resolve_company", f"Resolving {ticker} via EDGAR"):
        company = await company_service.require_investigable(db, ticker)
        dto = filing_provider.resolve_company(ticker)
        if dto.cik and company.cik and dto.cik != company.cik:
            raise RuntimeError(f"CIK mismatch for {ticker}: seed={company.cik} edgar={dto.cik}")
        company.cik = company.cik or dto.cik
        company.industry = dto.industry or company.industry
        company.sector = company.sector or dto.sic
        company.resolved_by = "edgartools"
        await db.flush()
        await db.commit()
        company_id = company.id

    # 2) filings metadata + 3) text sections (one transaction per filing)
    async with step(db, run_id, "ingest_filings", f"Ingesting 10-K/10-Q for {ticker}"):
        filings = await fis.ingest_filings_metadata(db, company_id, company.cik, filing_provider)
        await db.commit()
        for f in filings:
            fresh = (await db.execute(select(Filing).where(Filing.id == f.id))).scalar_one()
            await fis.ingest_filing_text(db, fresh, filing_provider)
            await db.commit()

    # 4) XBRL facts
    async with step(db, run_id, "extract_facts", f"Extracting XBRL facts for {ticker}"):
        since = as_of - timedelta(days=_FACTS_SINCE_DAYS)
        n_facts = await fis.ingest_financial_facts(db, company_id, company.cik, filing_provider, since=since)
        await db.commit()

    # 5) index filings (embeddings)
    async with step(db, run_id, "index_filings", f"Indexing filings for {ticker}"):
        filing_rows = (await db.execute(select(Filing).where(Filing.company_id == company_id))).scalars().all()
        n_chunks = 0
        for f in filing_rows:
            fresh = (await db.execute(select(Filing).where(Filing.id == f.id))).scalar_one()
            n_chunks += await dix.index_filing(db, fresh)
            await db.commit()

    # 6) refresh market data (skippable by explicit request)
    if skip_market_refresh:
        await mark_skipped(db, run_id, "refresh_market_data", "skipped by request")
    else:
        async with step(db, run_id, "refresh_market_data", f"Refreshing prices for {ticker} + SPY"):
            provider = YFinanceMarketDataProvider()
            start = as_of - timedelta(days=400)
            await mds.ingest_market_prices(db, [ticker, "SPY"], start, as_of, provider)
            await db.commit()

    # 7) baseline recipe (ledgered)
    async with step(db, run_id, "standard_recipe", f"Computing baseline metrics for {ticker}"):
        await recipe.run_standard_recipe(db, ticker, as_of=as_of, invoked_by="recipe")
        await db.commit()

    return {"ticker": ticker, "company_id": company_id, "facts": n_facts, "chunks": n_chunks}
