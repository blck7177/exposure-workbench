"""A read of a reconciliation does not mint a ledger row (live: DB + running API).

This is the half of the D5 guarantee that only a running system can show. The
offline guards hold the two ends' key sets against each other and pin that the
read uses the non-recording entry point; neither can see whether the row count
actually stays put, and the version of this that shipped passed both of its
offline checks while minting a row per request for a week.

The ledger's contract is one row per calculation, and it is what makes a number
citable. `25,119 calculations this desk has performed` has to mean that, not
`how many times a browser asked`.
"""

from __future__ import annotations

import os

import httpx
import pytest
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import CalcLedger

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
API = os.getenv("SMOKE_API_URL", f"http://127.0.0.1:{os.getenv('API_HOST_PORT', '8103')}")
RUN = os.getenv("SMOKE_RUN_ID", "run_95ebe31c5e51")


async def _rows() -> int:
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine)() as db:
            return (await db.execute(select(func.count()).select_from(CalcLedger))).scalar_one()
    finally:
        await engine.dispose()


async def test_reading_a_reconciliation_twice_leaves_the_ledger_where_it_was():
    async with httpx.AsyncClient(timeout=30) as c:
        first = await c.get(f"{API}/api/exposure-runs/{RUN}/reconcile")
        assert first.status_code == 200, first.text
        if "calc_id" not in first.json():
            pytest.skip(f"{RUN} is not reconcilable on this database")

        before = await _rows()
        for _ in range(3):
            r = await c.get(f"{API}/api/exposure-runs/{RUN}/reconcile")
            assert r.status_code == 200
        after = await _rows()

    assert after == before, (
        f"three reads added {after - before} ledger row(s). A read that records is a "
        "page view counted as a calculation"
    )


async def test_the_read_cites_the_calculation_that_was_performed():
    """Not a fresh id each time — the point of reusing the row is that a chart's
    citation and an answer's citation are the same row."""
    async with httpx.AsyncClient(timeout=30) as c:
        a = (await c.get(f"{API}/api/exposure-runs/{RUN}/reconcile")).json()
        b = (await c.get(f"{API}/api/exposure-runs/{RUN}/reconcile")).json()
    if "calc_id" not in a:
        pytest.skip(f"{RUN} is not reconcilable on this database")
    assert a["calc_id"] == b["calc_id"]
    assert a["identity_positions"] == b["identity_positions"], (
        "the figures are recomputed on every read and must be identical"
    )
