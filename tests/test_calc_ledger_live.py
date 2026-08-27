"""M3 calc service — ledger traceability invariants (live: needs DB + seeded facts).

Run with:  pytest -m live -k calc_ledger
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.analytics import series_ops as so
from exposure_workbench.db.models import CalcLedger
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import fundamentals_service as fs
from exposure_workbench.services import series_service as ss
from exposure_workbench.services import typed_calculator as tc

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _session():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_every_calc_writes_a_traceable_ledger_row():
    engine, mk = await _session()
    try:
        async with mk() as db:
            # `total_revenues`, not `revenue`: NVDA changed its tagging in 2022
            # from RevenueFromContractWithCustomerExcludingAssessedTax to
            # Revenues, and V9-M1 stopped treating those as one metric because
            # they are not (the top line may carry non-contract income — 5.2%
            # apart on XOM). NVDA's contract-revenue series is genuinely three
            # periods long; its top line is forty-three. These tests are about
            # the ledger, so they take the series that exists.
            series = await fs.get_flow(db, "NVDA", "total_revenues", months=3, last_n=8, invoked_by="test")
            out = await ss.series_stat(db, series["calc_id"], "yoy", invoked_by="test")
            await db.commit()
            assert out["calc_id"].startswith("calc_")

            row = (await db.execute(select(CalcLedger).where(CalcLedger.id == out["calc_id"]))).scalar_one()
            assert row.operation == "change.yoy"
            assert row.primitive_version == so.PRIMITIVE_VERSION
            assert row.invoked_by == "test"
            # provenance: a change is taken over a series, and the series row
            # is what references the facts — one hop, both citable.
            assert row.input_refs == [series["calc_id"]]
            src = (await db.execute(select(CalcLedger).where(CalcLedger.id == series["calc_id"]))).scalar_one()
            assert src.input_refs and all(r.startswith("fact_") for r in src.input_refs)
    finally:
        await engine.dispose()


async def test_margin_number_is_reproducible_from_the_same_facts():
    """The LLM can't do arithmetic — so the ledgered value must be exactly what
    the pure algebra yields from the cited facts, recomputed independently."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            gp = await fs.get_flow(db, "NVDA", "gross_profit", months=3, last_n=8, invoked_by="test")
            # See the note in the test above on why this is total_revenues.
            rev = await fs.get_flow(db, "NVDA", "total_revenues", months=3, last_n=8, invoked_by="test")
            out = await tc.calculate(db, "divide", gp["calc_id"], rev["calc_id"], invoked_by="test")
            await db.commit()

            # independent recompute from the two series' own points
            gp_pts = {p["end"]: p["value"] for p in gp["points"] if p.get("value") is not None}
            rev_pts = {p["end"]: p["value"] for p in rev["points"] if p.get("value") is not None}
            got = {p["end"]: p["value"] for p in out["points"]}
            for end in gp_pts.keys() & rev_pts.keys():
                assert got[end] == pytest.approx(gp_pts[end] / rev_pts[end])
            # NVDA gross margin is ~0.70-0.78 — a sanity band, not a hardcoded value
            latest = [p["value"] for p in out["points"] if p["value"] is not None][-1]
            assert 0.5 < latest < 0.9
    finally:
        await engine.dispose()
