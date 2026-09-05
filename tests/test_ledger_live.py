"""V24 phase B, live: one tool call through the wrapper writes the same facts to
the step and to the facts table, the ledger loads them, the drawer resolves one."""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import AgentSession, AgentStep, FactRecord
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.services import evidence_resolver_service as ev
from exposure_workbench.services import facts as F
from exposure_workbench.services import ledger as L
from exposure_workbench.tools import registry as R
from exposure_workbench.tools.registries import build_meta_registry

pytestmark = pytest.mark.live
URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


@pytest.mark.asyncio
async def test_step_and_table_agree_and_the_drawer_resolves():
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    reg = build_meta_registry()
    async with mk() as db:
        s = await sess.create_session(db, kind="meta")
        await db.commit()
        sid = s.id
    try:
        async with mk() as db:
            res = await R.invoke(reg, db, sid, "read_fundamentals", {"ticker": "MSFT"})
            await db.commit()
        assert not res.get("error"), res
        async with mk() as db:
            led = await L.load(db, sid)
            rows = (await db.execute(select(FactRecord).where(FactRecord.session_id == sid))).scalars().all()
            step = (await db.execute(select(AgentStep).where(AgentStep.session_id == sid))).scalars().one()
        on_step = L.facts_in(step.evidence_refs)
        assert on_step and len(on_step) == len(rows) == len(led.by_id)
        assert {r["id"] for r in on_step} == {row.id for row in rows}
        by_row = {row.id: row for row in rows}
        for rec in on_step:
            row = by_row[rec["id"]]
            assert (row.measure, row.unit, row.value, row.as_of, row.subject) == \
                   (rec["measure"], rec["unit"], rec["value"], rec["as_of"], rec["subject"])
            assert row.step_id == step.id
        assert all(F.is_fact_id(i) for i in led.by_id)
        # the balance sheet: every balance a scalar as of the sheet's date, money or a count
        assert all(r["kind"] == F.SCALAR and r["as_of"] for r in on_step)
        async with mk() as db:
            env = await ev.resolve(db, next(iter(led.by_id)))
        assert env["type"] == "fact_record" and env["label"] and env["upstream"]
        assert env["upstream"][0]["id"].startswith("fact_")
    finally:
        async with mk() as db:
            await db.execute(delete(FactRecord).where(FactRecord.session_id == sid))
            await db.execute(delete(AgentStep).where(AgentStep.session_id == sid))
            await db.execute(delete(AgentSession).where(AgentSession.id == sid))
            await db.commit()
        await engine.dispose()
