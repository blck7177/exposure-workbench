"""V9-M3 — every new metric has the period basis it claims (live).

Run with:  pytest -m live -k metric_basis

A balance and a flow are both numbers and the database will store either under
any name. What tells them apart is `period_start`: NULL for an instant (a
balance at a date), present for a duration (a charge over a window). Getting one
wrong does not fail loudly — it produces a series that compares a stock against
a flow, and this project has paid for that once already: comparing YoY by list
position instead of by date reported a 2808% move on a sparse series.

So the basis is asserted against the real corpus, per metric, at the moment the
mapping is introduced rather than the first time somebody quotes one.
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

INSTANT = (
    "total_assets", "total_liabilities", "stockholders_equity",
    "stockholders_equity_including_noncontrolling", "noncontrolling_interest",
    "accounts_receivable", "inventory", "accounts_payable", "commercial_paper",
    "operating_lease_liability_total", "operating_lease_liability_current",
    "operating_lease_liability_noncurrent",
    "long_term_debt_total", "long_term_debt_noncurrent",
    "current_portion_long_term_debt", "debt_current_total", "short_term_borrowings",
    "cash_and_equivalents", "cash_and_restricted_cash",
)
DURATION = (
    "interest_expense", "interest_paid", "income_tax_expense",
    "depreciation_amortization", "depreciation", "amortization_of_intangibles",
    "net_income", "net_income_including_noncontrolling", "total_revenues",
)


async def _rows(metric: str):
    engine = create_async_engine(URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return (await db.execute(text(
                "SELECT count(*) AS n, "
                "       count(*) FILTER (WHERE period_start IS NULL) AS instant, "
                "       count(DISTINCT unit) AS units, min(unit) AS unit "
                "  FROM financial_facts "
                " WHERE normalized_metric = :m AND dimensions_hash = '' AND value IS NOT NULL"
            ), {"m": metric})).mappings().one()
    finally:
        await engine.dispose()


@pytest.mark.parametrize("metric", INSTANT)
async def test_a_balance_is_stored_as_an_instant(metric):
    r = await _rows(metric)
    assert r["n"] > 0, f"{metric} mapped but backfilled nothing"
    assert r["instant"] == r["n"], (
        f"{metric} has {r['n'] - r['instant']} rows with a period_start — a balance "
        f"sheet line stored as a flow would be summed across quarters"
    )


@pytest.mark.parametrize("metric", DURATION)
async def test_a_flow_is_stored_as_a_duration(metric):
    r = await _rows(metric)
    assert r["n"] > 0, f"{metric} mapped but backfilled nothing"
    assert r["instant"] == 0, (
        f"{metric} has {r['instant']} rows with no period_start — a charge stored as "
        f"a balance would be quoted as if it were a level"
    )


@pytest.mark.parametrize("metric", INSTANT + DURATION)
async def test_every_new_metric_is_in_one_unit(metric):
    """Facts are stored in absolute units with no scaling anywhere, and the unit
    column is the only magnitude-bearing field. A metric holding two units would
    be a series that changes scale mid-way."""
    r = await _rows(metric)
    assert r["units"] == 1 and r["unit"] == "USD", f"{metric}: {r['units']} units ({r['unit']})"
