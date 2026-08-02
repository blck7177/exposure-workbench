"""V3-A1 numeric verification against the real database (live).

Run with:  pytest -m live -k numeric_verification

The offline file proves the matching rule. This one proves the three things that
can only be proved against real rows: that a citable prefix actually resolves to
the values its rows hold, that the derived-Q4 series is verifiable now that it is
ledgered, and that the whole thing does not refuse the answers the system has
already produced.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import AgentMessage
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import numeric_verification as nv

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _session():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_a_derived_q4_is_verifiable_only_because_the_series_is_ledgered():
    """The structural false rejection A1c closes, on the exact figure that
    produced it. MSFT's FY2025 Q4 revenue is annual minus three filed quarters —
    $76.441B, which is what one live brief states and which equals no row in
    financial_facts. Citing the four facts it came from is honest and, before
    the series had a ledger id of its own, unverifiable."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            out = await cs.series(db, cs.SeriesSpec("MSFT", "revenue", period_type="quarterly", last_n=8),
                                  invoked_by="test")
            await db.commit()
            derived = [p for p in out["points"] if len(p["fact_ids"]) > 1]
            assert derived, "expected at least one derived Q4 point in a quarterly series"

            point = derived[-1]
            written = f"revenue of ${point['value'] / 1e9:.3f}B"
            numbers = nv.extract_numbers(written)

            values, quoted = await nv.resolve_cited_values(db, [out["calc_id"]])
            assert nv.verify(numbers, values, quoted) == [], "the ledgered series must carry it"

            only_facts, q2 = await nv.resolve_cited_values(db, point["fact_ids"])
            assert nv.verify(numbers, only_facts, q2) != [], (
                "citing only the input facts must still fail — each holds a different number, "
                "which is the whole reason the series needed an id"
            )
    finally:
        await engine.dispose()


async def test_a_run_resolves_through_its_children_not_its_own_columns():
    """exposure_runs has no numeric column at all. If run_ resolved against the
    run row, every portfolio-level figure would come back unverified and the
    refusal would name the model rather than this table."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            run_id = (await db.execute(text(
                "SELECT run_id FROM exposure_metrics ORDER BY id LIMIT 1"))).scalar_one_or_none()
            if run_id is None:
                pytest.skip("no completed exposure run in this database")

            values, _ = await nv.resolve_cited_values(db, [run_id])
            assert values, "a completed run must resolve to the numbers on its children"
            labels = {v.label.split(".")[0] for v in values}
            assert "exposure_metrics" in labels
            assert {v.unit_class for v in values} <= {nv.MONEY, nv.RATIO}
    finally:
        await engine.dispose()


async def test_the_answers_already_in_the_database_still_pass():
    """The acceptance bar, measured rather than asserted: verification must not
    start refusing the system's own past work. Every number-bearing assistant
    message that carries citations is re-checked against them."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            rows = (await db.execute(
                select(AgentMessage).where(AgentMessage.role == "assistant")
            )).scalars().all()

            checked = failed = 0
            offenders: list[str] = []
            for m in rows:
                numbers = nv.extract_numbers(m.content or "")
                if not numbers or not m.citations:
                    continue
                values, quoted = await nv.resolve_cited_values(db, list(m.citations))
                problems = nv.verify(numbers, values, quoted)
                checked += len(numbers)
                failed += len(problems)
                if problems:
                    offenders.append(f"{m.id}: {[p['number'] for p in problems]}")

            assert checked >= 10, "expected a meaningful corpus of cited numbers"
            # The plan's bar is 2 in 20. Measured at 0 in 20 when this was written.
            assert failed * 10 <= checked, f"{failed}/{checked} refused: {offenders}"
    finally:
        await engine.dispose()
