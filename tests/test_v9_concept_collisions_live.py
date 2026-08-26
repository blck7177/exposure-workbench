"""V9-M1 — no metric is two quantities, checked against the real corpus (live).

Run with:  pytest -m live -k concept_collisions

The mapping table lets several raw concepts mean one metric. That is safe only
while the concepts really are synonyms, and nothing was checking. They were not:
`LongTermDebt` and `LongTermDebtNoncurrent` differ by the current maturities,
`ProfitLoss` and `NetIncomeLoss` by the noncontrolling interests, the two cash
concepts by restricted cash — and `period_ladder._pick_latest` resolves
restatements, not scopes, so which one reached the answer depended on filing
order. 24 (issuer, metric) pairs were affected; the worst disagreed by 17,596%.

Five metrics were split. Two — pretax_income and cost_of_revenue — were left
multi-concept because every issuer reporting two of them reports the same
number, and this test is the whole reason that bet is allowed to stand. It goes
red the day an issuer files two concepts under one metric with different values,
which is the day the bet stops being safe.

It also covers the split ones, so a merge cannot be reintroduced quietly.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)

# Consolidated facts only. A dimensioned fact carries the same concept and a
# smaller value by design, and load_fact_series already filters on this.
_SQL = text("""
SELECT c.ticker, f.normalized_metric AS metric, f.period_end,
       count(DISTINCT f.raw_concept) AS concepts,
       string_agg(DISTINCT replace(f.raw_concept, 'us-gaap:', ''), ' | ') AS which,
       min(f.value) AS lo, max(f.value) AS hi
  FROM financial_facts f JOIN companies c ON c.id = f.company_id
 WHERE f.normalized_metric IS NOT NULL
   AND f.dimensions_hash = ''
   AND f.value IS NOT NULL
 GROUP BY 1, 2, 3
HAVING count(DISTINCT f.raw_concept) > 1 AND min(f.value) <> max(f.value)
 ORDER BY 1, 2, 3
""")


async def test_no_metric_is_two_quantities_in_the_live_corpus():
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            rows = (await db.execute(_SQL)).mappings().all()
    finally:
        await engine.dispose()

    if rows:
        worst = sorted(
            rows,
            key=lambda r: abs(float(r["hi"]) - float(r["lo"])) / max(abs(float(r["lo"])), 1e-9),
            reverse=True,
        )[:5]
        detail = "\n".join(
            f"  {r['ticker']} {r['metric']} {r['period_end']}: "
            f"{float(r['lo']):,.0f} vs {float(r['hi']):,.0f}  [{r['which']}]"
            for r in worst
        )
        pytest.fail(
            f"{len(rows)} (issuer, metric, period) rows where one metric holds two "
            f"different values from two concepts. Whichever was filed last wins, "
            f"arbitrarily. Split the metric — see docs/spikes/V9_FORMULA_BASIS.md §3.\n"
            f"worst:\n{detail}"
        )
