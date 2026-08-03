"""Every portfolio in the real database can actually be run (live: needs Postgres).

Run with:  pytest -m live -k limit_completeness

An offline test can prove that LIMIT_SPECS and SEED_DEFAULTS agree with each
other. It cannot prove that the rows exist. That gap has a specific, expensive
shape: once a missing required limit fails a run, the pull request that adds a
ninth limit_type is green in CI and, on deploy, fails EVERY run of EVERY
portfolio — including the public demo — because no database anywhere has a row
for it. Same for the reverse: applying the migration to one volume and not
another leaves a book that cannot be valued and nothing says so until a user
presses Run.

This test is the thing that goes red before the deploy instead of after it.

It connects as the OWNER role on purpose. This is a database-wide invariant over
every tenant's portfolios, not a tenancy question — as app_rls it would see only
the public demo and pass while six other books were broken.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from exposure_workbench.analytics.limits import LIMIT_SPECS, REQUIRED_LIMIT_TYPES

load_dotenv(".env", override=True)

pytestmark = pytest.mark.live

OWNER_URL = os.getenv(
    "DATABASE_URL_LOCAL",
    "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench",
)


@pytest.fixture
async def owner_session():
    engine = create_async_engine(OWNER_URL, poolclass=None)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_every_portfolio_carries_every_required_default(owner_session):
    rows = (await owner_session.execute(text("""
        SELECT p.id, rl.limit_type
          FROM portfolios p
          LEFT JOIN risk_limits rl
            ON rl.portfolio_id = p.id AND rl.entity_id IS NULL AND rl.is_active
    """))).all()

    assert rows, "no portfolios at all — is this pointed at the right database?"

    present: dict[str, set[str]] = {}
    for portfolio_id, limit_type in rows:
        present.setdefault(portfolio_id, set())
        if limit_type is not None:
            present[portfolio_id].add(limit_type)

    incomplete = {
        pid: sorted(REQUIRED_LIMIT_TYPES - got)
        for pid, got in present.items()
        if REQUIRED_LIMIT_TYPES - got
    }
    assert not incomplete, (
        "these portfolios cannot be run — a required limit has no active row "
        f"with entity_id NULL: {incomplete}"
    )


async def test_no_row_names_a_check_that_does_not_exist(owner_session):
    """`stress_loss_tech` is why this test exists.

    Six rows carried that limit_type, all is_active, and the limits endpoint
    served them to users as policy in force. Nothing ever looked it up —
    check_limits asks for `stress_loss` — so it was decoration with a number on
    it. A row naming a check that does not exist is worse than a missing row,
    because it reads as coverage.
    """
    rows = (await owner_session.execute(text("""
        SELECT limit_type, count(*) FROM risk_limits GROUP BY 1
    """))).all()
    unknown = {lt: n for lt, n in rows if lt not in LIMIT_SPECS}
    assert not unknown, f"risk_limits rows name checks the engine cannot run: {unknown}"


async def test_the_constraints_are_actually_applied_here(owner_session):
    """The migration file being correct is not the same as it having been run.

    Without these, a threshold expressed in percent (unit 'percent', warning 15,
    breach 20) is schema-valid and can never fire against a fraction; tiers that
    coincide or invert are legal, and both silently disable the warning tier
    because _check_one tests breach first; and a second entity_id-NULL row for
    one limit_type is legal, which puts the reader back in the business of
    arbitrating between two sources of truth — the exact thing this deletes.

    What these constraints do NOT catch is a number that is merely wrong for its
    check: breach_level = 9.99 on daily_loss passes all four and never fires. No
    schema rule can catch that without a per-check ceiling, and a per-check
    ceiling would put threshold numbers back in the schema. Nothing catches it
    today. The run's payload_summary records which checks were EVALUATED, which
    is a different question from whether their numbers were sane.
    """
    declared = {
        name for (name,) in (await owner_session.execute(text("""
            SELECT conname FROM pg_constraint WHERE conrelid = 'risk_limits'::regclass
            UNION ALL
            SELECT indexname FROM pg_indexes WHERE tablename = 'risk_limits'
        """))).all()
    }
    missing = {
        "ux_risk_limits_default",
        "ck_risk_limits_levels",
        "ck_risk_limits_unit",
        "ck_risk_limits_default_active",
    } - declared
    assert not missing, f"migration not applied to this database: {sorted(missing)}"
