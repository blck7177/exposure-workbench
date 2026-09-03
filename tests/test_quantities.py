"""V15-S2a — one run, one namer, every quantity unique and typed.

The gate used to build a quantity's full name at refusal time, out of its own
walk over the cited rows, and the model never saw it. Now services/quantities.py
names a quantity once for the table the model reads AND the set the gate
resolves against. What that buys is only real if the names are unique under one
ref (two figures under one name is one name for two facts) and every one of
them carries a unit (a number without a unit is a number the gate has to guess
about). Pinned on a real completed run because that is where the three
duplicates were found.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.analytics import resources, units
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import table as tb

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
RUN = "run_1d6e9e05bee6"


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# ── offline ───────────────────────────────────────────────────────────────────

def _calc(operation, result=None):
    return SimpleNamespace(operation=operation, result=result or {})


def test_a_calc_row_is_an_absence_a_series_or_a_scalar_by_its_operation():
    """The kind is what an assertion block's predicate reads: a trend needs a
    series, an absence needs a refusal. It is decided from the row, once."""
    assert qn.calc_kind(_calc("absence.not_reported")) == qn.KIND_ABSENCE
    assert qn.calc_kind(_calc("flow.series", {"points": [{"value": 1}]})) == qn.KIND_SERIES
    assert qn.calc_kind(_calc("change.yoy")) == qn.KIND_SERIES
    assert qn.calc_kind(_calc("stat.mean", {"points": [{"value": 1}]})) == qn.KIND_SERIES, (
        "a row that carries points is a series whatever it is called")
    assert qn.calc_kind(_calc("flow.window", {"value": 3.0})) == qn.KIND_SCALAR
    assert qn.calc_kind(_calc("portfolio.integration")) == qn.KIND_SCALAR


def test_quoted_keys_tags_digits_by_the_unit_the_text_puts_beside_them():
    keys = qn.quoted_keys("Revenue grew 16.3% to $94.9B over 58 observations, or 12 percent")
    assert keys == {"%:16.3", ":16.3", "$:94.9", ":94.9", ":58", "%:12", ":12"}
    assert qn.quoted_keys("") == set()


def test_unit_class_strings_agree_between_quantities_and_resources():
    """resources.py declares columns in units; quantities.py types what it
    reads off them. One string apart and every money column would type as a
    ratio for the gate."""
    assert (qn.MONEY, qn.RATIO, qn.COUNT) == (resources.MONEY, resources.RATIO, resources.COUNT)
    assert set(qn.RUN_TABLES) == {r.table for r in resources.RUN_CHILDREN} | {"count"}


def test_legacy_point_period_keys_are_a_frozen_read_end():
    """Writers use units.POINT_PERIOD_KEY — one key, one owner (V16). This
    tuple exists to read rows the three-producer era already wrote, and may
    not grow: a fourth key would be a fourth producer, the exact bug the
    single owner forbids. It dies with those rows."""
    assert qn._POINT_PERIOD_KEYS == ("period_end", "end", "as_of")
    assert qn._POINT_PERIOD_KEYS[0] == units.POINT_PERIOD_KEY


def test_a_facts_unit_is_judged_once_by_the_algebra():
    """quantities only TRANSLATES units.fact_unit's judgement — the bridge is
    total over the algebra's vocabulary and adds no class of its own, so a
    fact's unit cannot be judged a second time here (the old
    MONEY-if-USD-else-COUNT guess made EPS a count)."""
    assert set(qn._UNIT_CLASS_OF) == set(units.UNIT_CLASSES)
    assert qn._UNIT_CLASS_OF[units.MONEY_PER_SHARE] == qn.MONEY_PER_SHARE


# ── live ──────────────────────────────────────────────────────────────────────

@pytest.mark.live
async def test_every_label_of_a_real_run_is_unique_and_every_quantity_has_a_unit():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            r = await qn.of_ref(db, RUN)
            await db.rollback()
    finally:
        await engine.dispose()
    assert r.kind == "run"
    labels = [q.label for q in r.quantities]
    dupes = sorted({l for l in labels if labels.count(l) > 1})
    assert dupes == [], f"one name for two figures: {dupes}"
    # 235 before V20; 193 with the six withheld metrics, the stress table
    # (twelve losses) and the seven stress_loss limit-check rows (three
    # columns each, plus a count) off the table (analytics/withheld.py).
    assert len(labels) == 193, len(labels)
    assert {q.unit_class for q in r.quantities} <= {qn.MONEY, qn.RATIO, qn.COUNT}
    assert all(q.table in qn.RUN_TABLES for q in r.quantities), (
        sorted({q.table for q in r.quantities} - set(qn.RUN_TABLES)))


@pytest.mark.live
async def test_two_issuer_concentration_alerts_get_distinct_names_by_qualifier():
    """The three duplicates of 235: two alerts of one type on one run, told
    apart only by which issuer each is about (resources.qualifier_column)."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            r = await qn.of_ref(db, RUN)
            await db.rollback()
    finally:
        await engine.dispose()
    conc = sorted(q.label for q in r.quantities if q.label.startswith("risk_alerts.issuer_concentration"))
    assert conc, "the run has issuer-concentration alerts"
    assert all(":" in name for name in conc), conc
    entities = {name.split(":")[1].split(".")[0] for name in conc}
    assert len(entities) >= 2, conc
    assert len(conc) == len(set(conc))


@pytest.mark.live
async def test_the_whole_run_fits_on_the_table_without_narrowing():
    """The size cap is derived so one run arrives whole; if this fails, the cap
    and the run have drifted apart and scope starts silently dropping tables."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            declared, payload = await tb.build(db, [{"type": "run", "id": RUN, "scope": list(qn.RUN_TABLES)}])
            await db.rollback()
    finally:
        await engine.dispose()
    assert len(json.dumps(payload)) <= tb.TABLE_CHAR_LIMIT
    assert declared == [{"type": "run", "id": RUN, "scope": list(qn.RUN_TABLES)}], (
        "the declaration came back narrowed")
    assert "truncated" not in declared[0]
    shown = payload["quantities"][RUN]
    assert len(shown) == 193 - 32, "every quantity but the 32 collinear coefficients is shown"
    assert "factor_attributions.sum_of_contributions" in shown
    assert not any(name.startswith("factor_attributions.market.") for name in shown)
