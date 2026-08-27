"""V9-A2/A3 — the two read primitives, against the real corpus (live).

Run with:  pytest -m live -k fundamentals_service

These are the whole surface an agent needs for report analysis: a flow over a
window it chooses, and a balance sheet at one instant. Everything else it can
compose. What they must not do is the two things the corpus already proved
dangerous:

  * serve a window shorter than the one asked for under the same name, and
  * take one balance from one date and another from a different one.

The second is not hypothetical. GOOGL's last reported long_term_debt_total is
2025-12-31 at 49.085bn while its noncurrent balance runs to 2026-06-30 at
98.165bn; reading "the latest of each" gives a total smaller than its own
component.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import CalcLedger
from exposure_workbench.services import fundamentals_service as fs

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# ── A2: get_flow ──────────────────────────────────────────────────────────────

async def test_the_trailing_year_no_single_filing_reports():
    """The pin. AAPL files cash flow cumulatively from the year's start, so no
    fact covers the twelve months to March 2026 — three of them do, two added
    and one subtracted."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fs.get_flow(db, "AAPL", "operating_cash_flow", months=12)
            await db.commit()
    finally:
        await engine.dispose()

    assert got["value"] == pytest.approx(140.222e9, rel=1e-9)
    assert got["period"] == {"start": "2025-03-30", "end": "2026-03-28"}
    assert len(got["terms"]) == 3
    assert sorted(t["sign"] for t in got["terms"]) == [-1, 1, 1]
    assert got["calc_id"].startswith("calc_")


async def test_the_derivation_is_written_down_where_a_reader_can_check_it():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fs.get_flow(db, "AAPL", "operating_cash_flow", months=12)
            await db.commit()
            row = await db.get(CalcLedger, got["calc_id"])
            assert row is not None
            # every fact that went in, and which way it went in
            assert sorted(row.input_refs) == sorted(t["fact_id"] for t in got["terms"])
            assert row.params["terms"], "the signs are not recoverable from the ledger"
            assert row.params["period"] == got["period"]
    finally:
        await engine.dispose()


async def test_a_window_that_cannot_be_derived_is_refused_not_shortened():
    """MSFT's D&A is not reported at all (V9-M1b: 5 of 8 issuers report it), so
    there is nothing to shorten TO. The refusal names the metric rather than
    returning a smaller period."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fs.get_flow(db, "MSFT", "depreciation_amortization", months=12)
    finally:
        await engine.dispose()
    assert got.get("error")
    assert "value" not in got


async def test_an_explicit_window_is_honoured_exactly():
    """AAPL's second fiscal quarter of 2026, which the issuer never filed."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fs.get_flow(db, "AAPL", "operating_cash_flow",
                                    start="2025-12-28", end="2026-03-28")
            await db.commit()
    finally:
        await engine.dispose()
    assert got["value"] == pytest.approx(28.702e9, rel=1e-9)
    assert len(got["terms"]) == 2


# ── A3: get_balance_sheet ─────────────────────────────────────────────────────

async def test_a_balance_sheet_is_one_instant_and_says_so():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fs.get_balance_sheet(db, "AAPL")
    finally:
        await engine.dispose()

    assert got["as_of"] == "2026-03-28"
    for name, line in got["balances"].items():
        assert line["as_of"] == got["as_of"], f"{name} came from another date"
    assert got["balances"]["long_term_debt_total"]["value"] == pytest.approx(82.700e9, rel=1e-9)


async def test_the_absent_lines_are_named_with_when_they_were_last_seen():
    """The pin. GOOGL's long_term_debt_total stops at 2025-12-31 while its
    noncurrent balance runs to 2026-06-30. Absent here means absent AT THIS
    DATE, and a reader is told where it was last reported so they can ask for
    that date deliberately — which is different from having it silently
    substituted."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fs.get_balance_sheet(db, "GOOGL")
    finally:
        await engine.dispose()

    assert got["as_of"] == "2026-06-30"
    absent = got["not_reported_at_this_date"]
    assert "long_term_debt_total" in absent
    assert absent["long_term_debt_total"]["last_reported"] == "2025-12-31"
    assert "long_term_debt_total" not in got["balances"]
    # and the one that IS there is the one that belongs to this date
    assert got["balances"]["long_term_debt_noncurrent"]["value"] == pytest.approx(98.165e9, rel=1e-9)


async def test_an_earlier_instant_can_be_asked_for_by_name():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fs.get_balance_sheet(db, "GOOGL", at="2025-12-31")
    finally:
        await engine.dispose()
    assert got["as_of"] == "2025-12-31"
    assert got["balances"]["long_term_debt_total"]["value"] == pytest.approx(49.085e9, rel=1e-9)
