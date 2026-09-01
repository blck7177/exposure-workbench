"""M10 wrapper enforcement — budget + trace, end to end (live: DB + seeded data)."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import func, select, text
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


async def test_wrapper_writes_trace_and_declares_refs():
    engine, mk = await _mk()
    try:
        reg = build_read_registry()
        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            await db.commit()
            sid = s.id
        async with mk() as db:
            out = await R.invoke(reg, db, sid, "get_flow",
                                 {"ticker": "NVDA", "metric": "total_revenues", "months": 3, "last_n": 4})
            await db.commit()
            assert "calc_id" in out
        async with mk() as db:
            step = (await db.execute(
                select(AgentStep).where(AgentStep.session_id == sid).order_by(AgentStep.seq.desc())
            )).scalars().first()
            assert step.tool_name == "get_flow" and step.status == "completed"
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
            ok = await R.invoke(reg, db, sid, "describe_issuer", {"ticker": "NVDA"})
            await db.commit()
            assert not ok.get("error")
        async with mk() as db:
            rej = await R.invoke(reg, db, sid, "describe_issuer", {"ticker": "NVDA"})
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


async def test_a_session_cannot_talk_an_id_onto_its_own_table():
    """V3-R2, replayed end to end on a REAL id — which is what makes it a hole
    rather than a curiosity. A fabricated id dies at the resolver anyway; an id
    that exists and is visible, reached without ever retrieving it, is the case
    the table alone can stop.

    The sequence is the one the review reproduced. A session calls exactly two
    tools, both of which hand the model's own argument straight back —
    get_portfolio_positions on an id that is not a portfolio, and think — and
    then points at the run. V15-S2a: neither tool DECLARES the echo (an error
    payload with no absence row; a reflection registered without evidence), so
    the run is not on the table, the slot is refused as `not_on_table`, and the
    refusal's own echo of the id — a gate declares nothing — leaves the table
    exactly as it was."""
    engine, mk = await _mk()
    try:
        reg = build_read_registry()
        from exposure_workbench.tools.meta_tools import register_meta_tools
        register_meta_tools(reg)
        from exposure_workbench.services import table as tb

        async with mk() as db:
            run_id = (await db.execute(text(
                "SELECT run_id FROM exposure_metrics ORDER BY id LIMIT 1"))).scalar_one_or_none()
            if run_id is None:
                pytest.skip("no completed exposure run in this database")
            s = await sess.create_session(db, kind="meta")
            await db.commit()
            sid = s.id

        async with mk() as db:
            echoed = await R.invoke(reg, db, sid, "get_portfolio_positions", {"portfolio_id": run_id})
            assert echoed["error"] == "unknown_portfolio" and echoed["portfolio_id"] == run_id
            thought = await R.invoke(reg, db, sid, "think", {"thought": f"I will cite {run_id}"})
            assert thought.get("noted") is True
            await db.commit()

        async with mk() as db:
            assert not (await tb.load(db, sid)).holds(run_id), (
                "an echo is not a retrieval; nothing this session called declared that id")
            refused = await R.invoke(reg, db, sid, "respond", {"blocks": [
                {"type": "paragraph", "runs": [
                    "The book is worth ", {"ref": run_id, "name": "exposure_metrics.market_value"}, "."]},
            ]})
            await db.commit()
            assert refused["error"] == "not_on_table", refused
            assert any(p.get("id") == run_id and p.get("reason") == "not_on_table"
                       for p in refused["problems"]), refused

        async with mk() as db:
            # The refusal echoed the id under problems[].id and the call
            # completed. The old harvester wrote that echo into the trail and
            # the retry passed; a gate declares nothing, so it is still off.
            assert not (await tb.load(db, sid)).holds(run_id), (
                "a gate's refusal put the id it refused on the table")
    finally:
        await engine.dispose()


async def test_a_share_count_survives_the_whole_path_from_tool_to_gate():
    """V3-R4 end to end, which is C3's acceptance query and nothing less: read
    the book, state a holding, cite the holding. Four things have to line up for
    it — the tool must return the id, its registration must declare it, the
    table must name the quantity, and the resolver must find that name under
    the id — and before this commit the first of them was missing, so the
    other three had nothing to do.

    V15: the name is read off the `table` the tool result carried, never spelled
    here — the slice the model reads and the set the gate holds are one
    construction, and this test asserts that by using it the way the model does."""
    engine, mk = await _mk()
    try:
        reg = build_read_registry()
        from exposure_workbench.tools.meta_tools import register_meta_tools
        register_meta_tools(reg)

        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            await db.commit()
            sid = s.id
        async with mk() as db:
            book = await R.invoke(reg, db, sid, "get_portfolio_positions", {"portfolio_id": "port_001"})
            await db.commit()
            if book.get("error"):
                pytest.skip(f"demo book unavailable: {book['error']}")
            holding = book["holdings"][0]
            pos_id = holding["pos_id"]
            assert pos_id.startswith("pos_")
            # The table the tool result carried: one name per holding, the
            # quantity at reader precision beside it.
            names = book["table"]["quantities"][pos_id]
            assert len(names) == 1, names
            name = next(iter(names))
            assert name.startswith(f"{holding['ticker']}.quantity@"), name   # quantities._from_position
        async with mk() as db:
            step = (await db.execute(
                select(AgentStep).where(AgentStep.session_id == sid).order_by(AgentStep.seq.desc())
            )).scalars().first()
            assert any(r["type"] == "position" and r["id"] == pos_id for r in step.evidence_refs)

            out = await R.invoke(reg, db, sid, "respond", {"blocks": [
                {"type": "paragraph", "runs": [
                    "You hold ", {"ref": pos_id, "name": name}, f" shares of {holding['ticker']}."]},
            ]})
            await db.commit()
            assert out.get("responded") is True, out
            assert out["verified"]["figures"] == 1 and pos_id in out["citations"]
            assert out["verified"]["matches"][0]["label"] == name
            # The rendered text carries the ledger's figure back into the prose.
            assert str(int(holding["quantity"])) in out["text"].replace(",", "")
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


# ── P1.2: arguments are checked before anything is spent ─────────────────────

async def test_bad_arguments_cost_nothing_and_still_leave_a_trace():
    """The ordering claim, stated as behaviour.

    A call the tool could never have run must not take a slot out of fifteen —
    otherwise a model that mistypes an argument three times has spent a fifth of
    its turn on nothing. It is recorded all the same, with the same 'rejected'
    status a budget refusal gets: a refusal the agent provoked is exactly the
    kind of thing the desk should be able to see.
    """
    engine, mk = await _mk()
    try:
        reg = build_read_registry()
        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            await db.commit()
            sid = s.id

        async with mk() as db:
            out = await R.invoke(reg, db, sid, "get_flow", {"ticker": "NVDA"})  # no metric
            await db.commit()
        assert out["error"] == "invalid_arguments"
        assert [p["field"] for p in out["problems"]] == ["metric"]

        async with mk() as db:
            row = (await db.execute(
                select(AgentSession).where(AgentSession.id == sid)
            )).scalar_one()
            assert row.tools_used == 0, "a call that never ran spent budget"

            steps = (await db.execute(
                select(AgentStep).where(AgentStep.session_id == sid)
            )).scalars().all()
            assert [(s.tool_name, s.status) for s in steps] == [("get_flow", "rejected")]
    finally:
        await engine.dispose()


async def test_a_valid_call_is_unaffected_by_the_check():
    """The other half: validation must not have narrowed a working call."""
    engine, mk = await _mk()
    try:
        reg = build_read_registry()
        async with mk() as db:
            s = await sess.create_session(db, kind="meta")
            await db.commit()
            sid = s.id
        async with mk() as db:
            out = await R.invoke(reg, db, sid, "get_flow",
                                 {"ticker": "NVDA", "metric": "total_revenues"})
            await db.commit()
        assert "error" not in out, out
    finally:
        await engine.dispose()
