"""V9-A4 — every containment edge still holds in the corpus (live).

Run with:  pytest -m live -k containment_live

The edge table is data, and data that nothing checks is an opinion. Each edge
claims one thing — a child balance never exceeds its parent at the same instant
— and that claim is falsifiable against every filing this database holds.

It is the edges that make R3 enforceable, so an edge quietly ceasing to hold is
not a documentation problem: `cover` would start returning overlapping terms and
the resulting total would be wrong with perfect provenance. This goes red first.

It also re-derives the observation counts stored beside each edge, so a count
that drifts as data is ingested is visible rather than stale.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.analytics import containment as ct

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)

# A child may exceed its parent by this much and still be the same claim:
# balances are rounded to the reported unit and a parent may be stated net of a
# discount its components are not. Measured on the corpus, the largest genuine
# excess is 0.0%; this is headroom, not a fitted number.
TOLERANCE = 5e-3


async def _instants():
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            rows = (await db.execute(text(
                "SELECT c.ticker, f.normalized_metric AS m, f.period_end AS pe, f.value AS v "
                "  FROM financial_facts f JOIN companies c ON c.id = f.company_id "
                " WHERE f.dimensions_hash = '' AND f.period_start IS NULL "
                "   AND f.value IS NOT NULL AND f.normalized_metric IS NOT NULL"
            ))).mappings().all()
    finally:
        await engine.dispose()
    at: dict[tuple[str, object], dict[str, float]] = {}
    for r in rows:
        at.setdefault((r["ticker"], r["pe"]), {})[r["m"]] = float(r["v"])
    return at


async def test_no_child_balance_exceeds_its_parent():
    at = await _instants()
    violations: list[str] = []
    counts: dict[tuple[str, str], int] = {}

    for parent, child, _declared in ct.EDGES:
        for (ticker, pe), vals in at.items():
            if parent not in vals or child not in vals:
                continue
            counts[(parent, child)] = counts.get((parent, child), 0) + 1
            p, c = vals[parent], vals[child]
            if (c - p) / max(abs(p), 1.0) > TOLERANCE:
                violations.append(
                    f"{ticker} {pe}: {child} {c:,.0f} > {parent} {p:,.0f} "
                    f"({(c - p) / max(abs(p), 1.0) * 100:.2f}%)")

    assert not violations, (
        f"{len(violations)} filings contradict a containment edge. cover() would "
        f"return overlapping terms and the total would be wrong with perfect "
        f"provenance:\n  " + "\n  ".join(violations[:10]))

    unobserved = [f"{p} > {c}" for p, c, _n in ct.EDGES if not counts.get((p, c))]
    assert not unobserved, (
        f"edges declared with an observation count that no filing supports: {unobserved}")


async def test_the_observation_counts_beside_each_edge_are_current():
    """The count is the evidence the edge was admitted on. Stale evidence reads
    as stronger than it is."""
    at = await _instants()
    drifted: list[str] = []
    for parent, child, declared in ct.EDGES:
        seen = sum(1 for vals in at.values() if parent in vals and child in vals)
        if seen != declared:
            drifted.append(f"{parent} > {child}: declared {declared}, corpus now {seen}")
    assert not drifted, (
        "containment.EDGES counts are out of date — update them with the new "
        "numbers after confirming the edges still hold:\n  " + "\n  ".join(drifted))
