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

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _session():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_every_calc_writes_a_traceable_ledger_row():
    engine, mk = await _session()
    try:
        async with mk() as db:
            spec = cs.SeriesSpec("NVDA", "revenue", period_type="quarterly", last_n=8)
            out = await cs.change(db, spec, "yoy", invoked_by="test")
            await db.commit()
            assert out["calc_id"].startswith("calc_")

            row = (await db.execute(select(CalcLedger).where(CalcLedger.id == out["calc_id"]))).scalar_one()
            assert row.operation == "change.yoy"
            assert row.primitive_version == so.PRIMITIVE_VERSION
            assert row.invoked_by == "test"
            # provenance: references real fact ids the number was computed from
            assert row.input_refs and all(r.startswith("fact_") for r in row.input_refs)
    finally:
        await engine.dispose()


async def test_margin_number_is_reproducible_from_the_same_facts():
    """The LLM can't do arithmetic — so the ledgered value must be exactly what
    the pure algebra yields from the cited facts, recomputed independently."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            gp = cs.SeriesSpec("NVDA", "gross_profit", period_type="quarterly", last_n=8)
            rev = cs.SeriesSpec("NVDA", "revenue", period_type="quarterly", last_n=8)
            out = await cs.combine(db, gp, rev, "divide", invoked_by="test")
            await db.commit()

            # independent recompute from the raw series
            gp_pts, _ = await cs.load_fact_series(db, gp)
            rev_pts, _ = await cs.load_fact_series(db, rev)
            expected = so.combine_series(gp_pts, rev_pts, "divide")
            got = {p["period_end"]: p["value"] for p in out["points"]}
            for p in expected.points:
                if p.value is not None:
                    assert got[p.period_end.isoformat()] == pytest.approx(p.value)
            # NVDA gross margin is ~0.70-0.78 — a sanity band, not a hardcoded value
            latest = [p["value"] for p in out["points"] if p["value"] is not None][-1]
            assert 0.5 < latest < 0.9
    finally:
        await engine.dispose()
