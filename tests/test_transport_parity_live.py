"""P3 — the transport does not change what is recorded (live).

Run with:  pytest -m live -k transport_parity

The agents reach their tools through an MCP client now. The claim that makes
that safe is that enforcement never lived in the transport: budget, argument
validation, evidence harvesting and the trace all sit in invoke(), below it. If
that is true, a call made directly and the same call made through a client
produce the same row — and if it stops being true, this goes red rather than an
answer quietly getting worse.

Standing, not a one-off before/after: the point is to keep the two routes from
drifting, and drift is a thing that happens later.
"""

from __future__ import annotations

import os
import re

import pytest
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.agents.meta_agent import build_meta_registry
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.db.models import AgentStep
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.tools import faces, registry as R

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")

# The fields a consumer of the audit trail reads. id, session_id, seq and
# duration_ms are excluded on purpose: the first three are per-row identity and
# the last is a stopwatch.
COMPARED = ("step_type", "tool_name", "args", "result_summary", "evidence_refs", "status")

# calc_ ids are MINTED per call — the ledger is append-only, so one calculation
# run twice is two rows, and two routes producing the same calc_id would mean
# the ledger had stopped recording. Every other prefix is a reference to a row
# that already exists and must match exactly: normalising those away would let
# the two routes cite different filings and still pass.
_MINTED = re.compile(r"\bcalc_[0-9a-f]+")


def _normalise(value):
    """Blank the ids a call mints, keep the ids a call cites."""
    if isinstance(value, str):
        return _MINTED.sub("calc_<minted>", value)
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    return value

CASES = [
    ("get_issuer_snapshot", {"ticker": "NVDA"}, "a plain read"),
    ("get_fact_series", {"ticker": "NVDA", "metric": "revenue", "last_n": 4}, "a ledgered calc"),
    ("get_fact_series", {"ticker": "NVDA"}, "a refusal: missing required argument"),
    ("get_fact_series", {"ticker": "NVDA", "metric": "revenue", "last_n": 0}, "a refusal: below the floor"),
    ("get_issuer_snapshot", {"ticker": "NVDA", "period_type": "annual"}, "a refusal: unknown argument"),
    ("think", {"thought": "checking both routes"}, "a reflection, which spends no budget"),
]


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _row(mk, session_id: str) -> dict:
    async with mk() as db:
        step = (await db.execute(
            select(AgentStep).where(AgentStep.session_id == session_id)
        )).scalars().one()
        return {f: getattr(step, f) for f in COMPARED}


@pytest.mark.parametrize("tool_name, args, what", CASES, ids=[c[2] for c in CASES])
async def test_both_routes_record_the_same_step(tool_name, args, what):
    engine, mk = await _mk()
    registry = build_meta_registry()
    try:
        async with mk() as db:
            direct = await sess.create_session(db, kind="meta")
            through = await sess.create_session(db, kind="meta")
            await db.commit()
            direct_id, through_id = direct.id, through.id

        # route 1 — the wrapper, called the way it was before P3
        async with mk() as db:
            direct_result = await R.invoke(registry, db, direct_id, tool_name, args)
            await db.commit()

        # route 2 — the same wrapper, reached over the transport
        async with tool_session(registry, faces.FACE_META_AGENT, db_factory=mk,
                                session_id=through_id) as tools:
            through_result = await tools.call(tool_name, args)

        assert _normalise(direct_result) == _normalise(through_result), \
            "the payload differs between routes"
        assert _normalise(await _row(mk, direct_id)) == _normalise(await _row(mk, through_id)), \
            "the recorded step differs between routes"
    finally:
        async with mk() as db:
            await db.execute(text(
                "DELETE FROM agent_steps WHERE session_id IN (:a, :b)"), {"a": direct_id, "b": through_id})
            await db.execute(text(
                "DELETE FROM agent_sessions WHERE id IN (:a, :b)"), {"a": direct_id, "b": through_id})
            await db.commit()
        await engine.dispose()


async def test_the_budget_is_spent_the_same_way_through_the_transport():
    """Reads cost a unit, reflections do not, and a refused call costs nothing.
    All three are decisions invoke() makes, and none of them should become a
    decision the transport makes."""
    engine, mk = await _mk()
    registry = build_meta_registry()
    session_id = None
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            await db.commit()
            session_id = s.id

        async with tool_session(registry, faces.FACE_META_AGENT, db_factory=mk,
                                session_id=session_id) as tools:
            await tools.call("get_issuer_snapshot", {"ticker": "NVDA"})      # +1
            await tools.call("think", {"thought": "free"})                   # +0
            await tools.call("get_fact_series", {"ticker": "NVDA"})          # +0, refused

        async with mk() as db:
            used = (await db.execute(text(
                "SELECT tools_used FROM agent_sessions WHERE id = :i"), {"i": session_id})).scalar_one()
        assert used == 1
    finally:
        if session_id:
            async with mk() as db:
                await db.execute(text("DELETE FROM agent_steps WHERE session_id = :i"), {"i": session_id})
                await db.execute(text("DELETE FROM agent_sessions WHERE id = :i"), {"i": session_id})
                await db.commit()
        await engine.dispose()


async def test_the_face_the_loop_is_given_is_the_face_it_can_call():
    """A tool outside the face is not refused by the transport — it is not there
    at all. Face trimming is how skip-flags work, so this is the property that
    makes 'the capability does not exist for this session' true."""
    engine, mk = await _mk()
    registry = build_meta_registry()
    session_id = None
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            await db.commit()
            session_id = s.id

        async with tool_session(registry, faces.READ_CORE, db_factory=mk,
                                session_id=session_id) as tools:
            names = {t["function"]["name"] for t in tools.tools}
            assert "start_issuer_research" not in names
            out = await tools.call("start_issuer_research", {"ticker": "NVDA", "reason": "x"})

        # invoke() answers for an unknown name, so the refusal is the gate's and
        # is recorded — the model gets told, and the desk can see it was tried.
        assert out["error"] == "unknown_tool"
        async with mk() as db:
            step = (await db.execute(
                select(AgentStep).where(AgentStep.session_id == session_id)
            )).scalars().one()
            assert (step.tool_name, step.status) == ("start_issuer_research", "error")
    finally:
        if session_id:
            async with mk() as db:
                await db.execute(text("DELETE FROM agent_steps WHERE session_id = :i"), {"i": session_id})
                await db.execute(text("DELETE FROM agent_sessions WHERE id = :i"), {"i": session_id})
                await db.commit()
        await engine.dispose()
