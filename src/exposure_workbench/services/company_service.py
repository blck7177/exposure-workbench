"""Company identity service (M1) — the single source of truth for ticker -> company.

  get_by_ticker(...)        -> Company | raises CompanyNotFound
  require_investigable(...) -> Company | raises CompanyNotFound / NotInvestigable
  admit(...)                -> Company | raises the same three, having written a row

The first two are the read path: the UI needs the row even for a
non-investigable ticker (to grey out the Investigate button), while tools and
workflows that only operate on issuers call require_investigable.

WHY admit EXISTS (V17). Until now `companies` had exactly one writer — the seed
script's hand-verified list of eight issuers — so every question about any other
listed name answered `unknown_ticker`, forever. Meanwhile the book side accepted
the whole listed universe: a reader could upload a portfolio of forty names,
watch the exposure run price and regress all of them, click one, and be told the
desk had never heard of it. Admission closes that gap, and it is deliberately
the ONLY new writer.

It is a decision over LOCAL data and touches no network. The listed universe
(`security_master`, refreshed as a whole) says what exists, what it is called
and whether it files with the SEC; this function reads that and writes the row.
Everything that costs money or time — EDGAR, XBRL, embeddings, prices — stays
in the readiness workflow behind a queue and a quota, which is also where a CIK
that turns out to be wrong fails loudly. The three refusals below are the three
ways a ticker can fail to be an issuer, and each says which.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company, SecurityMaster
from exposure_workbench.services import security_master_service as sms
from exposure_workbench.utils import cik as cik_util

# companies.ticker is VARCHAR(16) where security_master.ticker is VARCHAR(20).
# A longer listing symbol is refused by name rather than truncated into a row
# that resolves to the wrong security.
_MAX_TICKER = 16


class CompanyNotFound(Exception):
    def __init__(self, ticker: str):
        super().__init__(f"No company for ticker {ticker!r}")
        self.ticker = ticker


class NotInvestigable(Exception):
    def __init__(self, ticker: str, reason: str = "e.g. an ETF"):
        super().__init__(f"Ticker {ticker!r} is not investigable ({reason})")
        self.ticker = ticker
        self.reason = reason


class NotAnSecFiler(Exception):
    """Listed, but with no CIK: nothing this desk analyses can be built for it.

    Separate from NotInvestigable because the answer to a reader is different —
    an ETF has no financial statements to read, while a name with no CIK has
    them somewhere this desk cannot reach.
    """

    def __init__(self, ticker: str):
        super().__init__(f"Ticker {ticker!r} has no SEC CIK in the listed universe")
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


async def admissibility(db: AsyncSession, ticker: str) -> SecurityMaster:
    """The decision `admit` makes, without the write.

    Split out because two callers need the same verdict for different reasons
    and a second copy of the rules drifted immediately: the issuer route, asked
    for a ticker it holds no row for, needs to say WHICH silence this is, and it
    first answered "not prepared yet" for everything in the listed universe —
    which offered the reader a Prepare button on SPY, an action that could only
    refuse when clicked. A promise the next call cannot keep is worse than the
    refusal it replaced.

    Returns the universe row an admission would build from. Raises
    CompanyNotFound (not listed), NotInvestigable (an ETF, or a symbol too long
    to be an issuer here) or NotAnSecFiler (listed, no CIK).
    """
    tk = ticker.strip().upper()
    listed = await sms.get(db, tk)
    if listed is None or listed.status != "active":
        # Not "unknown to us": not in the listed universe at all. The universe
        # is refreshed whole and marks departures delisted, so this is a real
        # answer about the world and not a gap in our coverage.
        raise CompanyNotFound(tk)
    if listed.is_etf:
        raise NotInvestigable(tk, "an ETF files no 10-K or 10-Q")
    if len(tk) > _MAX_TICKER:
        raise NotInvestigable(tk, f"a symbol longer than {_MAX_TICKER} characters")
    if cik_util.canonical(listed.cik) is None:
        raise NotAnSecFiler(tk)
    return listed


async def admit(db: AsyncSession, ticker: str) -> Company:
    """The company row for `ticker`, creating it from the listed universe if absent.

    Idempotent and safe to race: the row is keyed by ticker, and a concurrent
    admission of the same name is resolved by re-reading rather than by raising.
    The id keeps the seed's convention (`co_<lowercase ticker>`) so a name that
    was seeded and a name that was admitted are indistinguishable afterwards —
    admission is how the table grows, not a second kind of row.

    Raises whatever `admissibility` raises; an existing row is returned as it
    stands, so a ticker somebody deliberately marked not investigable is never
    quietly promoted by a later admission.
    """
    tk = ticker.strip().upper()
    try:
        return await require_investigable(db, tk)
    except CompanyNotFound:
        pass

    listed = await admissibility(db, tk)
    await db.execute(
        pg_insert(Company)
        .values(id=f"co_{tk.lower()}", ticker=tk, name=listed.name or tk,
                cik=cik_util.canonical(listed.cik), exchange=listed.exchange,
                is_investigable=True, resolved_by="security_master")
        .on_conflict_do_nothing(index_elements=["ticker"])
    )
    await db.flush()
    # Re-read rather than return what was built: under a race the row that won
    # is the one every other reader will see, and the caller must hold that one.
    return await require_investigable(db, tk)


async def list_companies(db: AsyncSession, investigable_only: bool = False) -> list[Company]:
    q = select(Company).order_by(Company.ticker)
    if investigable_only:
        q = q.where(Company.is_investigable.is_(True))
    result = await db.execute(q)
    return list(result.scalars().all())
