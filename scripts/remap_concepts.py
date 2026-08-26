"""Re-normalise every stored fact under the current mapping version.

    python scripts/remap_concepts.py --dry-run
    python scripts/remap_concepts.py --apply

Not a backfill. V9-M1 SPLIT five metrics, so rows already carrying a value must
change: `us-gaap:LongTermDebt` was `long_term_debt` and is now
`long_term_debt_total`, which is a different name for a quantity that was always
this one. A NULL-only pass would leave exactly the rows the split was for.

The mapping is read from concept_mapping.normalize_concept and from nowhere
else. Re-implementing it in SQL would give the database a second opinion about
what a concept means, and the whole defect this repairs was two opinions about
one name.

Runs as the table owner: app_rls holds no UPDATE-through-RLS path for facts and
this is maintenance, not runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections import Counter

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)

from exposure_workbench.services.concept_mapping import MAPPING_VERSION, normalize_concept

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)


async def main(apply: bool) -> None:
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with mk() as db:
            rows = (await db.execute(text(
                "SELECT DISTINCT raw_concept, normalized_metric FROM financial_facts"
            ))).all()

        changes: list[tuple[str, str | None, str | None]] = []
        for raw, stored in rows:
            wanted = normalize_concept(raw)
            if wanted != stored:
                changes.append((raw, stored, wanted))

        tally = Counter((old, new) for _raw, old, new in changes)
        print(f"mapping version {MAPPING_VERSION}: {len(changes)} concept(s) change name\n")
        for (old, new), n in sorted(tally.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
            print(f"  {str(old):<38} -> {str(new):<38} ({n} concept(s))")

        if not changes:
            print("\nnothing to do.")
            return
        if not apply:
            print("\ndry run — pass --apply to write.")
            return

        # One statement per concept, so a partial failure leaves a state that
        # can be described rather than guessed at. All inside one transaction.
        async with mk() as db, db.begin():
            total = 0
            for raw, _old, new in changes:
                res = await db.execute(
                    text("UPDATE financial_facts SET normalized_metric = :m, "
                         "mapping_version = :v WHERE raw_concept = :c "
                         "AND normalized_metric IS DISTINCT FROM :m"),
                    {"m": new, "v": MAPPING_VERSION, "c": raw},
                )
                total += res.rowcount or 0
            print(f"\nupdated {total} fact rows to mapping {MAPPING_VERSION}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(apply=a.apply))
