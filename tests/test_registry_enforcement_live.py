"""M10 wrapper enforcement — budget + trace, end to end (live: DB + seeded data)."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import AgentSession, AgentStep
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.tools import registry as R
from exposure_workbench.tools.definitions import build_read_registry

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_wrapper_writes_trace_and_extracts_refs():
    engine, mk = await _mk()
    try:
        reg = build_read_registry()
        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            await db.commit()
            sid = s.id
        async with mk() as db:
            out = await R.invoke(reg, db, sid, "compute_change",
                                 {"ticker": "NVDA", "metric": "revenue", "mode": "yoy"})
            await db.commit()
            assert "calc_id" in out
        async with mk() as db:
            step = (await db.execute(
                select(AgentStep).where(AgentStep.session_id == sid).order_by(AgentStep.seq.desc())
            )).scalars().first()
            assert step.tool_name == "compute_change" and step.status == "completed"
            assert any(r["type"] == "calc" for r in step.evidence_refs)
    finally:
        await engine.dispose()


async def test_budget_exhaustion_rejects_and_is_traced():
    engine, mk = await _mk()
    try:
        reg = build_read_registry()
        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            # Tiny budget: allow exactly one tool call. V3-B2 made turn_tool_budget
            # the enforced number for a conversation (tool_budget stayed as the
            # lifetime audit counter), so this sets the one reserve() actually
            # reads — setting the other would silently test nothing.
            await db.execute(AgentSession.__table__.update()
                             .where(AgentSession.id == s.id).values(turn_tool_budget=1))
            await db.commit()
            sid = s.id
        async with mk() as db:
            ok = await R.invoke(reg, db, sid, "get_issuer_snapshot", {"ticker": "NVDA"})
            await db.commit()
            assert not ok.get("error")
        async with mk() as db:
            rej = await R.invoke(reg, db, sid, "get_issuer_snapshot", {"ticker": "NVDA"})
            await db.commit()
            assert rej["error"] == "budget_exceeded"
        async with mk() as db:
            rejected = (await db.execute(
                select(func.count()).select_from(AgentStep)
                .where(AgentStep.session_id == sid, AgentStep.status == "rejected")
            )).scalar_one()
            assert rejected == 1        # the over-budget call was still recorded
    finally:
        await engine.dispose()


async def test_reflection_tool_is_free():
    engine, mk = await _mk()
    try:
        reg = build_read_registry()
        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            await db.execute(AgentSession.__table__.update().where(AgentSession.id == s.id).values(tool_budget=0))
            await db.commit()
            sid = s.id
        async with mk() as db:
            # budget is 0, but think must still work (no reservation)
            out = await R.invoke(reg, db, sid, "think", {"thought": "pause"})
            await db.commit()
            assert out.get("noted") is True
    finally:
        await engine.dispose()
