"""The containment view and the margins panel do not mint (live: DB + API).

The half of the V13-S6 guarantee only a running system can show, on the same
grounds as tests/test_reconcile_reuse_live.py: the offline guards hold the
handler bodies away from every recording entry point, and the version of the
reconcile read that minted a row per request for a week passed both of its
offline checks. The ledger's contract is one row per calculation; a chart the
issuer page redraws on every visit must leave it exactly where it was.
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
TICKER = os.getenv("SMOKE_TICKER", "AAPL")


async def _rows() -> int:
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine)() as db:
            return (await db.execute(select(func.count()).select_from(CalcLedger))).scalar_one()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("path", [
    f"/api/issuers/{TICKER}/panel-series",
    f"/api/issuers/{TICKER}/containment?formula=total_debt",
])
async def test_reading_three_times_leaves_the_ledger_where_it_was(path):
    async with httpx.AsyncClient(timeout=30) as c:
        first = await c.get(f"{API}{path}")
        assert first.status_code == 200, first.text

        before = await _rows()
        for _ in range(3):
            r = await c.get(f"{API}{path}")
            assert r.status_code == 200
        after = await _rows()

    assert after == before, (
        f"three reads of {path} added {after - before} ledger row(s). A read "
        "that records is a page view counted as a calculation"
    )


async def test_the_panel_cites_the_series_the_recipe_computed():
    """The same calc_id on every read — the point of serving the manifest's own
    rows is that the chart's citation and the Financials tab's citation are the
    same ledger row."""
    async with httpx.AsyncClient(timeout=30) as c:
        a = (await c.get(f"{API}/api/issuers/{TICKER}/panel-series")).json()
        b = (await c.get(f"{API}/api/issuers/{TICKER}/panel-series")).json()
    if not a.get("series"):
        pytest.skip(f"{TICKER} has no chartable manifest rows on this database")
    assert {s["metric"]: s["calc_id"] for s in a["series"]} == \
           {s["metric"]: s["calc_id"] for s in b["series"]}
    fin = None
    async with httpx.AsyncClient(timeout=30) as c:
        fin = (await c.get(f"{API}/api/issuers/{TICKER}/financials")).json()
    by_label = {r["label"]: r.get("calc_id") for r in fin["calcs"]}
    for s in a["series"]:
        assert s["calc_id"] == by_label[s["metric"]], (
            "the panel and the Financials tab must cite the same row for the "
            "same series"
        )
