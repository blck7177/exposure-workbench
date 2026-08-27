"""An absence has an id, a sentence, and no numbers (V11-A, gap G1).

Measured over 43 real sessions: every "this cannot be produced" answer hit the
citation gate — three for three — because a refusal had no evidence row to cite,
and the model worked up through citing tool names and `co_jpm` to inventing
`run_?`. With no statement to relay it wrote its own, and twice out of three it
moved the gap from this desk's coverage onto the issuer.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import CalcLedger
from exposure_workbench.services import absence_service as ab
from exposure_workbench.services import formula_service as fms
from exposure_workbench.services import fundamentals_service as fs
from exposure_workbench.services import numeric_verification as nv
from exposure_workbench.services import typed_calculator as tc

pytestmark = pytest.mark.live

URL = os.getenv(
    "DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench"
)


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_an_unavailable_formula_says_whose_gap_it_is():
    """MSFT files depreciation every quarter and not the combined D&A line.

    The battery's answer: "not reported as such in the model" — read by a user as
    MSFT not disclosing it.
    """
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fms.evaluate_formula(db, "MSFT", "ebitda", months=12)
            await db.commit()
    finally:
        await engine.dispose()

    assert got["error"] == "input_unavailable"
    assert got["absence_id"].startswith("calc_")
    s = got["statement"]
    assert "depreciation_amortization" in s
    assert "no depreciation_amortization for MSFT at any date" in s
    assert "coverage, not a statement that the issuer does not disclose" in s


async def test_an_absence_names_the_metric_that_superseded_the_one_asked_for():
    """NVDA's revenue moved to total_revenues in 2022. Asked for four quarters of
    revenue, the battery's agent reported that the filings cannot support a
    quarterly series; get_flow on total_revenues returns four."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fs.get_flow(db, "NVDA", "revenue", months=3, last_n=4)
            alt = await fs.get_flow(db, "NVDA", "total_revenues", months=3, last_n=4)
            await db.commit()
    finally:
        await engine.dispose()

    assert got["error"] == "series_not_derivable"
    assert "total_revenues" in got["statement"], "the stand-in the registry knows about"
    assert len(alt["points"]) == 4, "and it really does answer the question"


async def test_an_absence_supports_no_number_at_all():
    """The row is citable so a refusal can be said with evidence. It must not
    become a way to attach a figure to nothing."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fms.evaluate_formula(db, "MSFT", "ebitda", months=12)
            await db.commit()
        async with mk() as db:
            values, quoted = await nv.resolve_cited_values(db, [got["absence_id"]])
    finally:
        await engine.dispose()

    assert values == [] and quoted == set()
    stated = nv.extract_numbers("MSFT's EBITDA was 145.2 billion")
    assert nv.verify(stated, values, quoted), "a number cited only to an absence is refused"


async def test_the_bank_refusal_keeps_its_reason_verbatim_and_proposes_nothing():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fms.evaluate_formula(db, "JPM", "ebit_interest_coverage", months=12)
            await db.commit()
    finally:
        await engine.dispose()

    assert got["error"] == "not_applicable"
    assert got["absence_id"].startswith("calc_")
    assert "interest expense is an operating cost for a bank" in got["statement"]
    assert "proposes no substitute" in got["statement"], (
        "which measures do describe a bank is a claim about bank analysis, and "
        "manufacturing one here is the issuer-behaviour rule this design refuses")


async def test_formulas_failing_on_one_input_share_one_absence():
    """ebitda and debt_to_ebitda miss the same thing for the same reason. Three
    ids for one fact would be three facts."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            panel = await fms.build_panel(db, "GOOGL", months=12)
            await db.commit()
    finally:
        await engine.dispose()

    refused = {k: v for k, v in panel["lines"].items() if v.get("absence_id")}
    by_id: dict[str, list[str]] = {}
    for name, line in refused.items():
        by_id.setdefault(line["absence_id"], []).append(name)
    shared = [names for names in by_id.values() if len(names) > 1]
    assert shared, "GOOGL has dependent formulas failing on one missing input"
    for names in shared:
        carrying = [n for n in names if panel["lines"][n].get("statement")]
        assert len(carrying) == 1, f"the paragraph belongs on the page once: {names}"


async def test_the_row_records_what_was_tried_and_what_sits_beside_it():
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await fms.evaluate_formula(db, "LLY", "free_cash_flow", months=12)
            await db.commit()
        async with mk() as db:
            row = (await db.execute(
                select(CalcLedger).where(CalcLedger.id == got["absence_id"])
            )).scalar_one()
    finally:
        await engine.dispose()

    assert row.operation == f"{ab.OP_ABSENCE}.input_unavailable"
    assert row.params["tried"]["formula"] == "free_cash_flow"
    assert row.params["stopped_at"]["input"] == "capex"
    # Both inputs' coverage, because "no shared window" is a fact about the pair.
    cov = row.params["neighbours"]["input_coverage"]
    assert cov["capex"]["through"] < cov["operating_cash_flow"]["through"]
    assert "value" not in row.result


def test_the_registry_reverse_index_is_the_source_of_stand_ins():
    """No new knowledge: Formula.alternatives, read backwards."""
    assert ab.superseded_by("revenue") == ("total_revenues",)
    assert ab.superseded_by("interest_expense") == ("interest_expense_nonoperating",)
    assert ab.superseded_by("net_income") == ()


async def test_a_filing_passage_is_refused_as_an_operand_with_the_reason():
    """The worst answer in the battery ended "I need to recompute ... then I'll
    give you the percentage" — a promise it could not keep, because it had run
    out of moves and did not know that "this cannot be computed" was one."""
    engine, mk = await _mk()
    try:
        async with mk() as db:
            got = await tc.calculate(db, "add", "chunk_00e947bae71d", "chunk_5e30ae1dd78f")
    finally:
        await engine.dispose()

    assert got["error"] == "unknown_operand"
    assert "filing passage" in got["detail"]
    assert "quoted and cited" in got["detail"]
