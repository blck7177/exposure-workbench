"""V9-A5 — the calculator refuses what the citation gate cannot see (live).

Run with:  pytest -m live -k typed_calculator

Handing an agent raw data and four arithmetic operators is the obvious design,
and it is one operator short of safe. A bare calculator will happily compute
82.700 + 8.310 = 91.010 for AAPL's debt: every input is a real filed number,
every step is real arithmetic, the ledger row is genuine and the citation gate
passes it. The answer is wrong by the current maturities, counted twice.

That failure is invisible to provenance because nothing about it is malformed.
What makes it catchable is the TYPE of each operand — what it is a quantity OF,
at what instant or over what interval — and types are exactly what a bare
calculator throws away.

So every id carries its type, the type travels through the ledger to the next
call, and four combinations are refused:

  * two balances from different dates                       (R2)
  * two flows over overlapping intervals, added             (R1)
  * a total added to something it contains                  (R3)
  * money added to a ratio                                  (existing unit rule)

Everything else is allowed. The rules do not narrow what an agent may analyse;
they remove the one region where a wrong answer looks exactly like a right one.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import CalcLedger
from exposure_workbench.services import fundamentals_service as fs
from exposure_workbench.services import typed_calculator as tc

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _aapl_debt_ids(db):
    """The three AAPL balances at 2026-03-28 that make the double-count."""
    bs = await fs.get_balance_sheet(db, "AAPL", at="2026-03-28")
    b = bs["balances"]
    return (b["long_term_debt_total"]["fact_id"],
            b["current_portion_long_term_debt"]["fact_id"],
            b["commercial_paper"]["fact_id"])


async def test_the_double_count_is_refused_by_type_not_by_a_rule_about_debt():
    """The refusal names the containment, so the agent can act on it — take the
    total, or take the components, but not one of each."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            total, current, _cp = await _aapl_debt_ids(db)
            got = await tc.calculate(db, "add", total, current)
    finally:
        await engine.dispose()

    assert got["error"] == "overlapping_quantities"
    assert "value" not in got
    assert "long_term_debt_total" in got["detail"] and "current_portion" in got["detail"]


async def test_the_composition_that_is_correct_goes_through():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            total, _cur, cp = await _aapl_debt_ids(db)
            got = await tc.calculate(db, "add", total, cp)
            await db.commit()
    finally:
        await engine.dispose()

    assert got["value"] == pytest.approx(84.697e9, rel=1e-9)
    assert got["type"]["basis"]["instant"] == "2026-03-28"
    assert got["calc_id"].startswith("calc_")


async def test_two_balances_from_different_dates_are_refused():
    """GOOGL's shape, as arithmetic. Its long_term_debt_total stops at
    2025-12-31 and its noncurrent balance runs to 2026-06-30; adding them is
    addition across time, and the result describes no company-moment."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            old = await fs.get_balance_sheet(db, "GOOGL", at="2025-12-31")
            new = await fs.get_balance_sheet(db, "GOOGL")
            a = old["balances"]["long_term_debt_total"]["fact_id"]
            b = new["balances"]["cash_and_equivalents"]["fact_id"]
            got = await tc.calculate(db, "add", a, b)
    finally:
        await engine.dispose()

    assert got["error"] == "different_instants"
    assert "2025-12-31" in got["detail"] and "2026-06-30" in got["detail"]


async def test_two_flows_over_overlapping_windows_cannot_be_added():
    """A half-year and the quarter inside it are both real filings. Added, the
    first quarter counts twice — the interval version of the debt double-count."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            h1 = await fs.get_flow(db, "AAPL", "operating_cash_flow",
                                   start="2025-09-28", end="2026-03-28")
            q1 = await fs.get_flow(db, "AAPL", "operating_cash_flow",
                                   start="2025-09-28", end="2025-12-27")
            await db.commit()
            got = await tc.calculate(db, "add", h1["calc_id"], q1["calc_id"])
    finally:
        await engine.dispose()

    assert got["error"] == "overlapping_intervals"


async def test_subtracting_overlapping_windows_is_allowed_because_that_is_derivation():
    """H1 − Q1 = Q2. Subtraction of a contained interval is how a window is
    derived at all, so the rule that stops addition must not stop this."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            h1 = await fs.get_flow(db, "AAPL", "operating_cash_flow",
                                   start="2025-09-28", end="2026-03-28")
            q1 = await fs.get_flow(db, "AAPL", "operating_cash_flow",
                                   start="2025-09-28", end="2025-12-27")
            await db.commit()
            got = await tc.calculate(db, "subtract", h1["calc_id"], q1["calc_id"])
            await db.commit()
    finally:
        await engine.dispose()

    assert got["value"] == pytest.approx(28.702e9, rel=1e-6)
    assert got["type"]["basis"]["interval"] == ["2025-12-28", "2026-03-28"]


async def test_adding_adjacent_quarters_is_allowed_and_joins_the_window():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            q3 = await fs.get_flow(db, "MSFT", "operating_cash_flow",
                                   start="2025-10-01", end="2025-12-31")
            q4 = await fs.get_flow(db, "MSFT", "operating_cash_flow",
                                   start="2026-01-01", end="2026-03-31")
            await db.commit()
            got = await tc.calculate(db, "add", q3["calc_id"], q4["calc_id"])
            await db.commit()
    finally:
        await engine.dispose()

    assert got["type"]["basis"]["interval"] == ["2025-10-01", "2026-03-31"]


async def test_a_balance_over_a_flow_is_a_legitimate_ratio_and_keeps_both_bases():
    """Leverage is a stock over a flow. The rule is not "one basis per number",
    it is "say which"."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            bs = await fs.get_balance_sheet(db, "AAPL", at="2026-03-28")
            debt = bs["balances"]["long_term_debt_total"]["fact_id"]
            ocf = await fs.get_flow(db, "AAPL", "operating_cash_flow", months=12)
            await db.commit()
            got = await tc.calculate(db, "divide", debt, ocf["calc_id"])
            await db.commit()
    finally:
        await engine.dispose()

    assert got["value"] == pytest.approx(82.700e9 / 140.222e9, rel=1e-6)
    assert got["type"]["unit_class"] == "ratio"
    assert "2026-03-28" in got["type"]["basis"]["mixed"]
    assert "2025-03-30..2026-03-28" in got["type"]["basis"]["mixed"]


async def test_the_type_survives_two_hops():
    """A calc built from a calc must still know what it is, or the guard only
    protects the first step."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            total, _cur, cp = await _aapl_debt_ids(db)
            step1 = await tc.calculate(db, "add", total, cp)
            await db.commit()
            bs = await fs.get_balance_sheet(db, "AAPL", at="2026-03-28")
            cash = bs["balances"]["cash_and_equivalents"]["fact_id"]
            step2 = await tc.calculate(db, "subtract", step1["calc_id"], cash)
            await db.commit()
            row = await db.get(CalcLedger, step2["calc_id"])
    finally:
        await engine.dispose()

    assert step2["value"] == pytest.approx(84.697e9 - 45.572e9, rel=1e-9)
    assert step2["type"]["basis"]["instant"] == "2026-03-28"
    assert row.params["operand_types"], "the ledger does not carry what it combined"


async def test_a_calc_from_before_types_existed_is_refused_not_assumed():
    """Old ledger rows carry no type. Treating an unknown type as compatible
    would put the guard's own blind spot in the one place nobody would look."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            legacy = (await db.execute(text(
                "SELECT id FROM calc_ledger WHERE params->'result_type' IS NULL "
                "AND operation NOT IN ('derive.interval') LIMIT 1"))).scalar_one_or_none()
            if legacy is None:
                pytest.skip("no pre-typing calc rows in this database")
            bs = await fs.get_balance_sheet(db, "AAPL", at="2026-03-28")
            cash = bs["balances"]["cash_and_equivalents"]["fact_id"]
            got = await tc.calculate(db, "add", legacy, cash)
    finally:
        await engine.dispose()

    assert got["error"] == "untyped_operand"


# ── V11-T: a constant with a unit ─────────────────────────────────────────────

async def test_scale_records_the_multiplication_the_panel_used_to_do_in_python():
    """days_inventory prints 143.67; the ledger has to hold 143.67, not 0.3936.

    Until V11 the x365 happened in the caller and no row recorded it, so the
    panel published a figure its own calc_id could not support and the gate
    refused it — measured three times in the agent battery.
    """
    engine, mk = await _mk()
    try:
        async with mk() as db:
            total, current, _cp = await _aapl_debt_ids(db)
            ratio = await tc.calculate(db, "divide", current, total)
            scaled = await tc.scale(db, ratio["calc_id"], 365.0,
                                    unit_class=tc.COUNT, quantity="days_inventory")
            await db.commit()
            row = (await db.execute(
                select(CalcLedger).where(CalcLedger.id == scaled["calc_id"])
            )).scalar_one()
    finally:
        await engine.dispose()

    assert scaled["value"] == ratio["value"] * 365.0
    assert row.operation == "calc.scalar.scale"
    assert row.params["factor"] == 365.0
    assert row.input_refs == [ratio["calc_id"]]
    assert row.params["result_type"]["unit_class"] == "count"
    # The scaled row keeps the ratio's basis: multiplying by a constant does not
    # move a quantity in time.
    assert row.params["result_type"]["basis"] == ratio["type"]["basis"]


async def test_scale_refuses_an_id_it_cannot_type():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await tc.scale(db, "calc_does_not_exist", 365.0, unit_class=tc.COUNT)
    finally:
        await engine.dispose()
    assert got.get("error")
