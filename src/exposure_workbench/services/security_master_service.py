"""Security master service (V2-D) — refresh the universe + typeahead search.

refresh() upserts the full listed universe and marks anything now absent as
'delisted' (never deletes — a held ticker's history must always resolve).
search() is the deterministic typeahead: exact ticker > ticker prefix > name
substring; it never auto-selects (the UI makes the user click).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import MarketPrice, SecurityMaster
from exposure_workbench.providers.security_master_provider import SecurityRowDTO, fetch_universe

_SEARCH_LIMIT = 10
_UPSERT_CHUNK = 1000
_MIN_UNIVERSE = 1000   # the real universe is ~13k; a truncated fetch must not mass-delist


async def refresh(db: AsyncSession, rows: list[SecurityRowDTO] | None = None) -> dict:
    """Full universe refresh. rows may be injected (tests); otherwise fetched
    live (fail-loud). Present tickers -> active, absent -> delisted (kept)."""
    fetched_live = rows is None
    rows = rows if rows is not None else fetch_universe()
    # sanity floor on the LIVE path: a truncated-but-parseable source would else
    # delist most of the universe. Injected rows (tests) skip the floor.
    if fetched_live and len(rows) < _MIN_UNIVERSE:
        raise ValueError(f"refusing to refresh from an implausibly small universe "
                         f"({len(rows)} < {_MIN_UNIVERSE}) — likely a truncated source")
    if not rows:
        raise ValueError("refresh called with an empty universe")
    now = datetime.now(timezone.utc)

    # 1) mark all currently-active stale; the upsert below revives the present ones.
    await db.execute(update(SecurityMaster).where(SecurityMaster.status == "active")
                     .values(status="delisted"))

    # 2) chunked upsert (Postgres 32767-param limit; 8 cols * 1000 < limit)
    payload = [{"ticker": r.ticker, "name": r.name, "exchange": r.exchange,
                "is_etf": r.is_etf, "cik": r.cik, "status": "active",
                "source": "nasdaqtrader+sec", "fetched_at": now} for r in rows]
    for i in range(0, len(payload), _UPSERT_CHUNK):
        chunk = payload[i:i + _UPSERT_CHUNK]
        stmt = pg_insert(SecurityMaster).values(chunk).on_conflict_do_update(
            index_elements=["ticker"],
            set_={"name": pg_insert(SecurityMaster).excluded.name,
                  "exchange": pg_insert(SecurityMaster).excluded.exchange,
                  "is_etf": pg_insert(SecurityMaster).excluded.is_etf,
                  "cik": pg_insert(SecurityMaster).excluded.cik,
                  "status": "active",
                  "source": pg_insert(SecurityMaster).excluded.source,
                  "fetched_at": pg_insert(SecurityMaster).excluded.fetched_at},
        )
        await db.execute(stmt)
    await db.commit()
    return {"active": len(rows)}


async def search(db: AsyncSession, q: str, limit: int = _SEARCH_LIMIT) -> list[dict]:
    ql = (q or "").strip()
    if not ql:
        return []
    qu = ql.upper()
    # escape LIKE metacharacters so a user typing % or _ matches literally
    esc = ql.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rank = case((SecurityMaster.ticker == qu, 0),
                (SecurityMaster.ticker.ilike(f"{esc}%", escape="\\"), 1),
                else_=2)
    stmt = (select(SecurityMaster)
            .where(SecurityMaster.status == "active",
                   or_(SecurityMaster.ticker.ilike(f"{esc}%", escape="\\"),
                       SecurityMaster.name.ilike(f"%{esc}%", escape="\\")))
            .order_by(rank, SecurityMaster.ticker)
            .limit(limit))
    rows = (await db.execute(stmt)).scalars().all()
    tickers = [r.ticker for r in rows]
    priced: set[str] = set()
    if tickers:
        priced = set((await db.execute(
            select(MarketPrice.ticker).where(MarketPrice.ticker.in_(tickers)).distinct()
        )).scalars().all())
    return [{"ticker": r.ticker, "name": r.name, "exchange": r.exchange,
             "is_etf": r.is_etf, "has_cik": r.cik is not None,
             "has_prices": r.ticker in priced} for r in rows]


async def is_in_universe(db: AsyncSession, ticker: str) -> bool:
    row = (await db.execute(
        select(SecurityMaster.ticker).where(SecurityMaster.ticker == ticker,
                                            SecurityMaster.status == "active")
    )).scalar_one_or_none()
    return row is not None


async def get(db: AsyncSession, ticker: str) -> SecurityMaster | None:
    return (await db.execute(
        select(SecurityMaster).where(SecurityMaster.ticker == ticker)
    )).scalar_one_or_none()
