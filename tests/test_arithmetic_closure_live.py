"""V25 — the closed arithmetic against the real desk (live: DB + seeded data)."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.services import compute_service as cmp
from exposure_workbench.services import price_analytics_service as pas
from exposure_workbench.services import series_service
from exposure_workbench.tools.registry import _session_ctx as _session_id

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_a_measure_over_its_last_periods_is_one_series_and_yoy_applies():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            tok = _session_id.set("sess_test")
            try:
                out = await cmp.compute(db, method="gross_margin", subject="MSFT",
                                        params={"months": 3, "last_n": 8})
                assert not out.get("error"), out
                assert out["unit_class"] == "RATIO" and len(out["points"]) == 8
                valued = [p for p in out["points"] if p.get("value") is not None]
                assert len(valued) >= 4 and all(0 < p["value"] < 1 for p in valued)
                assert all(p.get("start") for p in out["points"])
                yoy = await cmp.compute(db, op="yoy", operands=[out["calc_id"]])
                assert not yoy.get("error"), yoy
                assert yoy["unit_class"] == "ratio" and any(p.get("value") is not None for p in yoy["points"])
                avg = await cmp.compute(db, op="avg", operands=[out["calc_id"]])
                assert not avg.get("error") and 0 < avg["value"] < 1
            finally:
                _session_id.reset(tok)
            await db.rollback()
    finally:
        await engine.dispose()


async def test_the_panel_has_no_series_form():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            out = await cmp.compute(db, method="issuer.panel", subject="MSFT", params={"last_n": 4})
            assert out["error"] == "invalid_params"
    finally:
        await engine.dispose()


async def test_days_to_liquidate_from_the_book_and_the_tape():
    """The N03 question, in two calls: dollar ADV for the names, then each
    position over its own ADV — a COUNT of days, from the algebra."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            tok = _session_id.set("sess_test")
            try:
                adv = await cmp.compute(db, method="price.adv", subject="AAPL")
                assert not adv.get("error"), adv
                assert adv["adv_dollars"]["unit_class"] == "money_per_day"
                assert adv["adv_shares"]["unit_class"] == "count_per_day"
                from exposure_workbench.services import catalogue_service as cat
                desk = await cat.describe(db, None)
                run_id = desk["portfolios"][0]["run_id"]
                days = await cmp.compute(db, op="divide",
                                         operands=[f"{run_id}:issuer_exposures.AAPL.market_value",
                                                   adv["adv_dollars"]["calc_id"]],
                                         as_quantity="days_to_sell")
                assert not days.get("error"), days
                assert days["type"]["unit_class"] == "count" and 0 < days["value"] < 1
            finally:
                _session_id.reset(tok)
            await db.rollback()
    finally:
        await engine.dispose()
