"""Company identity service (M1) — the single source of truth for ticker -> company.

Read path only (this module). It NEVER touches the network and NEVER writes:
"not found" is a data problem solved on the write path (seed, or the
resolve_company workflow step), not patched here.

  get_by_ticker(...)        -> Company | raises CompanyNotFound
  require_investigable(...)  -> Company | raises CompanyNotFound / NotInvestigable

The two are separate on purpose: the UI needs the row even for non-investigable
tickers (to grey out the Investigate button), while workflows/tools that only
operate on issuers call require_investigable.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company


class CompanyNotFound(Exception):
    def __init__(self, ticker: str):
        super().__init__(f"No company for ticker {ticker!r}")
        self.ticker = ticker


class NotInvestigable(Exception):
    def __init__(self, ticker: str):
        super().__init__(f"Ticker {ticker!r} is not investigable (e.g. an ETF)")
        self.ticker = ticker


async def get_by_ticker(db: AsyncSession, ticker: str) -> Company:
    """Look up a company by ticker. Raises CompanyNotFound if absent."""
    result = await db.execute(select(Company).where(Company.ticker == ticker))
    company = result.scalar_one_or_none()
    if company is None:
        raise CompanyNotFound(ticker)
    return company


async def require_investigable(db: AsyncSession, ticker: str) -> Company:
    """Look up a company that must be investigable. Raises if absent or not investigable."""
    company = await get_by_ticker(db, ticker)
    if not company.is_investigable:
        raise NotInvestigable(ticker)
    return company


async def list_companies(db: AsyncSession, investigable_only: bool = False) -> list[Company]:
    q = select(Company).order_by(Company.ticker)
    if investigable_only:
        q = q.where(Company.is_investigable.is_(True))
    result = await db.execute(q)
    return list(result.scalars().all())
