#!/usr/bin/env python3
"""Derive metric_lineage for every prepared issuer, and print what the filings said.

    python scripts/derive_lineage.py --dry-run
    python scripts/derive_lineage.py --apply [--db URL]

The rule lives in services/lineage_service and nowhere else; this only calls it,
the way scripts/remap_concepts.py only calls normalize_concept. Re-implementing
the overlap test in SQL would give the database a second opinion about what one
line is, and two opinions about one name is the defect this repairs.

Runs as the table owner: metric_lineage is reference data about issuers, like
financial_facts, written by maintenance and read by every tenant.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exposure_workbench.db.models import Company            # noqa: E402
from exposure_workbench.services import lineage_service as ls   # noqa: E402


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit the derived rows")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=os.getenv("DATABASE_URL_LOCAL",
                    "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"))
    args = ap.parse_args(argv)
    if not (args.apply or args.dry_run):
        ap.error("give --apply or --dry-run")

    engine = create_async_engine(args.db)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    rows = 0
    try:
        async with mk() as db:
            companies = (await db.execute(select(Company.id, Company.ticker).order_by(Company.ticker))).all()
            print(f"{'issuer':<8}{'retired':<22}{'continues as':<32}{'ends':<12}{'overlap':>8}{'max diff':>10}  follows")
            for cid, ticker in companies:
                for lin in await ls.derive(db, cid):
                    rows += 1
                    diff = "-" if lin.overlap_max_rel_diff is None else f"{lin.overlap_max_rel_diff:.4%}"
                    print(f"{ticker:<8}{lin.from_metric:<22}{lin.to_metric:<32}"
                          f"{lin.from_last_period_end.isoformat():<12}{lin.overlap_periods:>8}{diff:>10}  "
                          f"{'yes' if lin.agrees else 'NO'}")
            if args.apply:
                await db.commit()
            else:
                await db.rollback()
    finally:
        await engine.dispose()
    print(f"\n{rows} lineage row(s) {'written' if args.apply else 'derived (rolled back)'} on "
          f"{args.db.rsplit('/', 1)[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
