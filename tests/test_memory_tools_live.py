"""V3-C — the read-back tools, against a real database (live).

Run with:  pytest -m live -k memory_tools

Everything here answers a question the agent previously could not: what did the
research I commissioned conclude, did the work I delegated finish, what is
actually in this book, and what is A minus B.
"""

from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.services import brief_service, job_status_service
from exposure_workbench.services import portfolio_service
from exposure_workbench.services import fundamentals_service as fs
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.tools import definitions as D
from exposure_workbench.services import table as tbl

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
            # V3-R8: whose reading this is, and which run produced it. RLS shows
            # a caller its own briefs AND the public demo ones, so "I can see
            # it" and "I commissioned it" are different facts — without is_own
            # the agent hands a user the demo's conclusions as if they had paid
            # for them.
            assert out["is_own"] is False, "no authenticated user here"
            assert out["research_run_id"].startswith("rrun_")
    finally:
        await engine.dispose()


async def test_reading_a_brief_never_makes_the_brief_itself_citable():
    """brief_ is not a prefix the table places, on purpose: a brief is a
    conclusion drawn from evidence, so citing it is a loop. What the tool
    DECLARES (V15-S2a, the registration's Evidence()) is the evidence under the
    blocks, and that must reach the table."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            ticker = (await db.execute(text(
                "SELECT c.ticker FROM issuer_briefs b JOIN companies c ON c.id = b.company_id LIMIT 1"
            ))).scalar_one_or_none()
            if ticker is None:
                pytest.skip("no brief in this database")

            out = await D._read_issuer_brief(db, ticker)
            assert D.build_read_registry().get("read_issuer_brief").evidence is not None
            declared = {e["id"] for e in tbl.declare(dict(out))["evidence"]}
            assert out["brief_id"] not in declared
            # the underlying evidence, however, must be declared — that is the point
            assert declared, "the block citations must reach the table"
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
            # V3-R8: bounded, and the bound is legible. A tool result is
            # summarised at 6000 characters, so an unbounded book would be cut
            # mid-JSON — the model would read a broken object, or a plausible
            # one that stops at "AAP".
            assert out["count"] <= 50
            assert out["total_holdings"] >= out["count"]
            assert ("truncated" in out) == (out["total_holdings"] > out["count"])
    finally:
        await engine.dispose()


async def test_free_cash_flow_is_a_ledgered_series_calculation():
    """operating_cash_flow minus capex is the example in this project's own
    module notes. It used to need compute_combine with op='sub'; since V10 it
    is calculate over two series ids, and a nonsense op is refused by name."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            ocf = await fs.get_flow(db, "AAPL", "operating_cash_flow", months=3, last_n=8)
            capex = await fs.get_flow(db, "AAPL", "capex", months=3, last_n=8)
            out = await tc.calculate(db, "subtract", ocf["calc_id"], capex["calc_id"])
            await db.commit()
            assert out["calc_id"].startswith("calc_")
            assert out["points"], "expected at least one period of free cash flow"

            bad = await tc.calculate(db, "power", ocf["calc_id"], capex["calc_id"])
            assert bad["error"] == "unsupported_op"
    finally:
        await engine.dispose()


# ── V3-R8: the visibility claims, asserted through the RLS role ───────────────
# brief_service.latest_visible and status_of("rrun_...") carry no owner filter,
# and both say so in their docstrings: RLS is what scopes them. Asserting that
# through the `exposure` connection above proves nothing — the table owner has
# rolbypassrls, so every policy is inert for it and these tests would pass with
# row-level security switched off entirely. These connect as `app_rls` and set
# the tenant transaction-locally, exactly as the API does.

APP_URL = os.getenv(
    "DATABASE_URL_LOCAL_APP",
    "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench",
)
TAG = uuid.uuid4().hex[:8]
TENANT_A = f"user_v3c_A_{TAG}"
TENANT_B = f"user_v3c_B_{TAG}"


@pytest.fixture
async def two_tenants():
    """A owns a private brief and a research run on a company nobody else has
    written about; the same company also carries a public brief."""
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    ids = {"co": f"co_{TAG}", "brief_a": f"brief_{TAG}a", "brief_pub": f"brief_{TAG}p",
           "rrun_a": f"rrun_{TAG}a", "rrun_pub": f"rrun_{TAG}p"}
    async with mk() as db, db.begin():
        for uid in (TENANT_A, TENANT_B):
            await db.execute(text("INSERT INTO users (id, email) VALUES (:u, :e)"),
                             {"u": uid, "e": f"{uid}@example.test"})
        await db.execute(text("INSERT INTO companies (id, ticker, name) VALUES (:c, :t, 'V3R Probe Inc')"),
                         {"c": ids["co"], "t": f"ZZ{TAG[:2].upper()}"})
        await db.execute(text("""INSERT INTO research_runs (id, company_id, status, owner_id)
                                 VALUES (:r, :c, 'completed', :a)"""),
                         {"r": ids["rrun_a"], "c": ids["co"], "a": TENANT_A})
        await db.execute(text("""INSERT INTO research_runs (id, company_id, status, owner_id)
                                 VALUES (:r, :c, 'completed', NULL)"""),
                         {"r": ids["rrun_pub"], "c": ids["co"]})
        # created_at is set explicitly, and A's private brief is the NEWER of
        # the two, so that these tests cannot pass vacuously: latest_visible
        # takes the newest row it can see, so a reader that bypasses RLS gets
        # A's. Left to the default both rows would share one timestamp — now()
        # is transaction time — and the ordering would decide nothing.
        await db.execute(text("""INSERT INTO issuer_briefs
                                 (id, research_run_id, company_id, financial_summary, owner_id,
                                  is_public, created_at)
                                 VALUES (:b, :r, :c, 'The public read', NULL, TRUE,
                                         now() - interval '1 hour')"""),
                         {"b": ids["brief_pub"], "r": ids["rrun_pub"], "c": ids["co"]})
        await db.execute(text("""INSERT INTO issuer_briefs
                                 (id, research_run_id, company_id, financial_summary, owner_id,
                                  is_public, created_at)
                                 VALUES (:b, :r, :c, 'A private read', :a, FALSE, now())"""),
                         {"b": ids["brief_a"], "r": ids["rrun_a"], "c": ids["co"], "a": TENANT_A})
    try:
        yield ids
    finally:
        async with mk() as db, db.begin():
            await db.execute(text("DELETE FROM issuer_briefs WHERE id IN (:x, :y)"),
                             {"x": ids["brief_a"], "y": ids["brief_pub"]})
            await db.execute(text("DELETE FROM research_runs WHERE id IN (:r, :p)"),
                             {"r": ids["rrun_a"], "p": ids["rrun_pub"]})
            await db.execute(text("DELETE FROM companies WHERE id = :c"), {"c": ids["co"]})
            await db.execute(text("DELETE FROM users WHERE id IN (:a, :b)"),
                             {"a": TENANT_A, "b": TENANT_B})
        await engine.dispose()


async def _as_tenant(uid: str | None, fn):
    engine = create_async_engine(APP_URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with mk() as db, db.begin():
            if uid is not None:
                await db.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": uid})
            return await fn(db)
    finally:
        await engine.dispose()


async def test_a_brief_is_visible_to_its_owner_and_to_nobody_else(two_tenants):
    """Three readers, one company. The owner sees their own; another tenant and
    an anonymous reader see the public one and have no way to learn that the
    private one exists — invisibility rather than a refusal, which is the whole
    reason this is a policy and not a WHERE clause."""
    co = two_tenants["co"]

    mine = await _as_tenant(TENANT_A, lambda db: brief_service.latest_visible(db, co))
    theirs = await _as_tenant(TENANT_B, lambda db: brief_service.latest_visible(db, co))
    anon = await _as_tenant(None, lambda db: brief_service.latest_visible(db, co))

    assert mine["brief_id"] == two_tenants["brief_a"]
    assert theirs["brief_id"] == two_tenants["brief_pub"]
    assert anon["brief_id"] == two_tenants["brief_pub"]


async def test_another_tenants_research_run_is_an_unknown_job_not_a_denied_one(two_tenants):
    """status_of has no owner filter for rrun_ and says RLS scopes it. Under the
    app role it does: B's query returns no row, so the tool answers unknown_job
    — the same answer it gives for an id that was never minted, which is the
    point. A "denied" would confirm the run exists."""
    rrun = two_tenants["rrun_a"]

    mine = await _as_tenant(TENANT_A, lambda db: job_status_service.status_of(db, rrun))
    assert mine["kind"] == "research_run" and mine["status"] == "completed"

    theirs = await _as_tenant(TENANT_B, lambda db: D._get_task_status(db, rrun))
    never = await _as_tenant(TENANT_B, lambda db: D._get_task_status(db, "rrun_neverminted"))
    assert theirs == {"error": "unknown_job", "job_id": rrun}
    # the same shape, key for key, as an id that was never minted: nothing in the
    # answer distinguishes "not yours" from "does not exist"
    assert set(theirs) == set(never) and theirs["error"] == never["error"]
