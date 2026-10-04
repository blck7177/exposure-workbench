"""`analyze` against a database restored from the battery snapshot (EXPOSURE_DEV_DATABASE_URL,
an asyncpg URL to a scratch copy; skipped when unset). Nothing is committed."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from exposure_workbench.services import analysis_execution as ax, method_index as mi, scope as scope_svc

URL = os.environ.get("EXPOSURE_DEV_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="EXPOSURE_DEV_DATABASE_URL not set")


@pytest.fixture
async def db():
    eng = create_async_engine(URL)
    mk = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    async with mk() as session:
        yield session
        await session.rollback()
    await eng.dispose()


async def test_q07_as_one_analysis(db):
    view = await ax.analyze(db, scope={"book": "port_001", "sector": "Technology", "expected_count": 5},
                            requests=[{"measure": "cash_conversion", "compare": "previous_ttm", "rank": True},
                                      {"measure": "book.weight", "compare": "previous_run", "rank": True}],
                            allowed_measures=set(mi.measures_for(None)), invoked_by="test")
    assert view["coverage"] == {"subjects": 3, "subjects_complete": 3, "cells": 18, "scope_status": "mismatch"}
    cells = {(r["subject"], k): c for r in view["rows"] for k, c in r["cells"].items()}
    assert cells[("AAPL", "cash_conversion")]["display"] == "114.4%" and cells[("AAPL", "cash_conversion@baseline")]["display"] == "112.6%"
    assert cells[("AAPL", "cash_conversion.change")]["display"] == "+1.79 pp"
    assert cells[("NVDA", "cash_conversion.change")]["display"] == "-19.3 pp"
    assert cells[("AAPL", "book.weight.change")]["display"] == "+0.47 pp"
    assert cells[("AAPL", "cash_conversion")]["period"] == "2025-03-30..2026-03-28"
    assert cells[("AAPL", "cash_conversion@baseline")]["period"] == "2024-03-31..2025-03-29"
    assert [o["subject"] for o in view["ranks"]["cash_conversion"]["order"]] == ["MSFT", "AAPL", "NVDA"]
    assert [o["subject"] for o in view["ranks"]["cash_conversion.change"]["order"]] == ["AAPL", "MSFT", "NVDA"]
    assert [o["subject"] for o in view["ranks"]["book.weight.change"]["order"]] == ["AAPL", "MSFT", "NVDA"]
    assert view["limitations"][0].startswith("scope: 5 subjects were expected, 3 resolved")
    facts = view["_facts"]
    assert len(facts) == 18 and all(f["params"]["view"] == view["view"] for f in facts)
    change = next(f for f in facts if f["measure"] == "cash_conversion.absolute_change" and f["subject"] == "NVDA")
    assert change["params"]["semantic"]["kind"] == "absolute_change"
    assert change["params"]["semantic"]["baseline_period"] == {"start": "2024-07-29", "end": "2025-07-27"}


async def test_an_unknown_measure_and_a_wrong_compare_are_refused_before_anything_is_read(db):
    allowed = set(mi.measures_for(None))
    assert (await ax.analyze(db, scope={"subjects": ["AAPL"]}, requests=[{"measure": "cash_conversions"}], allowed_measures=allowed))["error"] == "unknown_measure"
    assert (await ax.analyze(db, scope={"subjects": ["AAPL"]}, requests=[{"measure": "book.weight", "compare": "previous_ttm"}], allowed_measures=allowed))["error"] == "compare_not_applicable"
    assert (await ax.analyze(db, scope={"subjects": []}, requests=[{"measure": "cash_conversion"}], allowed_measures=allowed))["error"] == "scope_unresolved"


async def test_the_scope_binds_from_the_book(db):
    sc = await scope_svc.bind(db, {"book": "port_001", "sector": "technology", "expected_count": 3})
    assert sc.subjects and sc.status == "resolved" and all(sc.sectors[t] == "Technology" for t in sc.subjects)
    assert (await scope_svc.bind(db, {"book": "port_001", "sector": "Pharma"}))["error"] == "scope_unresolved"
    cat = await scope_svc.catalogue(db)
    assert cat["books"][0]["runs"]["latest"]["id"].startswith("run_") and "AAPL" in cat["issuers_on_desk"]
