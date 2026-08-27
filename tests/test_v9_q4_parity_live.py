"""V9-A6 — the general rule reproduces the special case, on the whole corpus (live).

Run with:  pytest -m live -k q4_parity

`period_ladder.derive_q4` computes Q4 = annual − (Q1+Q2+Q3) and is the one place
in this codebase that already knew flows subtract across intervals. The interval
engine says the same thing without the case: Q4 is simply the window from the
third quarter's end to the year's end, and the search finds whatever path the
filings support — often FY − 9M, a single subtraction the old code could not
express because it had thrown the nine-month fact away.

If the two disagree anywhere in the corpus, the engine is wrong or the special
case was. Either way it is not a detail to discover later, so it is checked
against every (issuer, metric) pair that has any derived Q4 at all.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.analytics import interval_algebra as ia
from exposure_workbench.analytics import period_ladder as pl

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)

# Half a basis point of the annual figure. The two routes use different facts —
# FY − 9M against FY − (Q1+Q2+Q3) — so they meet only to the precision the
# filings themselves agree to.
REL_TOLERANCE = 5e-5


async def _corpus():
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            rows = (await db.execute(text(
                "SELECT c.ticker, f.normalized_metric AS metric, f.id, f.period_start, "
                "       f.period_end, f.value, f.source_accession, fl.filing_date "
                "  FROM financial_facts f "
                "  JOIN companies c ON c.id = f.company_id "
                "  LEFT JOIN filings fl ON fl.id = f.filing_id "
                " WHERE f.normalized_metric IS NOT NULL AND f.dimensions_hash = '' "
                "   AND f.value IS NOT NULL AND f.period_start IS NOT NULL"
            ))).mappings().all()
    finally:
        await engine.dispose()
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r["ticker"], r["metric"]), []).append(r)
    return grouped


async def test_the_engine_reproduces_every_derived_q4_in_the_corpus():
    grouped = await _corpus()
    checked = disagreed = 0
    problems: list[str] = []

    for (ticker, metric), rows in sorted(grouped.items()):
        facts = [pl.FactPoint(fact_id=r["id"], period_end=r["period_end"], value=float(r["value"]),
                              period_start=r["period_start"], source_accession=r["source_accession"],
                              filing_date=r["filing_date"]) for r in rows]
        quarterly = pl.build_ladder(facts, metric, pl.QUARTERLY)
        annual = pl.build_ladder(facts, metric, pl.ANNUAL)
        with_q4 = pl.derive_q4(quarterly, annual)

        flows = [ia.FlowFact(fact_id=r["id"], period_start=r["period_start"],
                             period_end=r["period_end"], value=float(r["value"]),
                             filing_date=r["filing_date"],
                             source_accession=r["source_accession"]) for r in rows]

        for p in with_q4.points:
            if not p.quality_flags.get("derived_q4"):
                continue
            checked += 1
            got = ia.derive(flows, p.period_start, p.period_end)
            if isinstance(got, ia.Unreachable):
                disagreed += 1
                problems.append(f"{ticker} {metric} {p.period_end}: engine says {got.reason}")
                continue
            scale = max(abs(p.value), 1.0)
            if abs(got.value - p.value) / scale > REL_TOLERANCE:
                disagreed += 1
                problems.append(
                    f"{ticker} {metric} {p.period_end}: ladder {p.value:,.0f} vs "
                    f"engine {got.value:,.0f} via [{got.formula}]")

    assert checked > 0, "no derived Q4 in the corpus — this test proved nothing"
    assert not problems, (
        f"{disagreed} of {checked} derived Q4 values disagree between the special "
        f"case and the general rule:\n  " + "\n  ".join(problems[:12]))
    print(f"\n{checked} derived Q4 values reproduced by the interval engine")
