"""Refresh the security_master universe (V2-D).

Fetches the full listed US universe (NASDAQ Trader + SEC CIK) and upserts it;
tickers now absent are marked delisted (never deleted). Run standalone:

    python -m scripts.refresh_security_master

Idempotent — safe to re-run (e.g. weekly). New IPOs appear on the next refresh.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# refresh runs as the owner role (security_master has no RLS; owner has all privs)
_URL = os.getenv("DATABASE_URL_LOCAL", os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"))


async def main() -> None:
    from exposure_workbench.services import security_master_service as sm
    engine = create_async_engine(_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            result = await sm.refresh(db)
        print(f"security_master refreshed: {result['active']} active securities")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
