"""V3-C — the read-back tools, against a real database (live).

Run with:  pytest -m live -k memory_tools

Everything here answers a question the agent previously could not: what did the
research I commissioned conclude, did the work I delegated finish, what is
actually in this book, and what is A minus B.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.services import brief_service, job_status_service
from exposure_workbench.services import portfolio_service
from exposure_workbench.tools import definitions as D
from exposure_workbench.tools.registry import extract_evidence_refs

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _session():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_a_brief_can_be_read_back_with_the_evidence_under_each_block():
    """The gap this closes: the meta-agent could spend a user's research quota
    commissioning a brief and then had no way to read one."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            ticker = (await db.execute(text(
                "SELECT c.ticker FROM issuer_briefs b JOIN companies c ON c.id = b.company_id LIMIT 1"
            ))).scalar_one_or_none()
            if ticker is None:
                pytest.skip("no brief in this database")

            out = await D._read_issuer_brief(db, ticker)
            assert out["brief_id"].startswith("brief_")
            assert out["blocks"], "a brief with no readable block is not a brief"
            assert out["citations"], "the flat citation list is always present"
    finally:
        await engine.dispose()


async def test_reading_a_brief_never_makes_the_brief_itself_citable():
    """brief_id is a plain string field on purpose. Returned as {"type","id"} the
    wrapper would harvest it into the evidence trail, where it would pass the
    trail check and then fail DB existence with a misleading "unresolved_in_db" —
    and a brief is a conclusion drawn from evidence, so citing it is a loop."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            ticker = (await db.execute(text(
                "SELECT c.ticker FROM issuer_briefs b JOIN companies c ON c.id = b.company_id LIMIT 1"
            ))).scalar_one_or_none()
            if ticker is None:
                pytest.skip("no brief in this database")

            out = await D._read_issuer_brief(db, ticker)
            harvested = {r["id"] for r in extract_evidence_refs(out)}
            assert out["brief_id"] not in harvested
            # the underlying evidence, however, must be harvested — that is the point
            assert harvested, "the block citations must reach the trail"
    finally:
        await engine.dispose()


async def test_task_status_refuses_rather_than_matching_ownerless_rows():
    """`Task.owner_user_id == None` compiles to IS NULL, which matches every
    ownerless seed task. With no authenticated user the only safe answer is a
    refusal, decided before the query rather than by it."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            task_id = (await db.execute(text("SELECT id FROM tasks LIMIT 1"))).scalar_one_or_none()
            if task_id is None:
                pytest.skip("no tasks in this database")
            with pytest.raises(job_status_service.NoOwner):
                await job_status_service.status_of(db, task_id)
            # and the tool turns that into a structured answer, never an exception
            out = await D._get_task_status(db, task_id)
            assert out["error"] == "sign_in_required"
    finally:
        await engine.dispose()


async def test_run_status_is_readable_and_unknown_ids_are_structured():
    engine, mk = await _session()
    try:
        async with mk() as db:
            run_id = (await db.execute(text(
                "SELECT id FROM exposure_runs WHERE status='completed' LIMIT 1"))).scalar_one_or_none()
            if run_id is None:
                pytest.skip("no completed run")
            out = await D._get_task_status(db, run_id)
            assert out["kind"] == "exposure_run" and out["status"] == "completed"
            assert (await D._get_task_status(db, "run_nope"))["error"] == "unknown_job"
    finally:
        await engine.dispose()


async def test_every_holding_is_listed_and_priced_from_the_run_not_the_position():
    """A1-coupled. Every market value and weight has to come from the run's
    issuer_exposures, because only those have a citable id behind them; reading a
    price off the position row would hand the model figures the numeric check
    must then refuse."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            out = await portfolio_service.positions_with_weights(db, "port_001")
            assert out is not None
            assert out["count"] == len(out["holdings"]) >= 10
            assert out["run_id"], "the demo portfolio has completed runs"

            priced = [h for h in out["holdings"] if "market_value" in h]
            assert priced, "a portfolio with a completed run must carry values"
            for h in priced:
                assert h["weight"] is not None and h["quantity"] is not None
            # the field the snapshot does not carry at all
            assert all("quantity" in h for h in out["holdings"])
    finally:
        await engine.dispose()


async def test_free_cash_flow_is_finally_a_ledgered_calculation():
    """operating_cash_flow minus capex is the example in this project's own
    module notes, and until now `sub` was unreachable from every agent face:
    compute_ratio hardcoded divide and nothing else exposed combine."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            out = await D._compute_combine(db, "AAPL", "operating_cash_flow", "capex", "sub")
            await db.commit()
            assert out["calc_id"].startswith("calc_")
            assert out["operation"] == "combine.sub"
            assert out["points"], "expected at least one period of free cash flow"

            bad = await D._compute_combine(db, "AAPL", "revenue", "capex", "multiply")
            assert bad["error"] == "unsupported_op"
    finally:
        await engine.dispose()
