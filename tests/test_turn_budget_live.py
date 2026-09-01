"""V3-B2 — the per-turn tool budget, against a real database (live).

Run with:  pytest -m live -k turn_budget

The regime a session is under is carried by its row, not decided by a branch in
reserve(), so the two things worth proving are that a conversation's budget
really does reset per turn and that a research run really does keep the lifetime
one. The second is not a nicety: research spends 25-32 tool calls inside a single
session and never claims a turn, so getting this wrong kills every issuer
research run partway through.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.services import agent_session_service as sess

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _session():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_a_conversation_gets_its_budget_back_every_turn():
    """The behaviour reversal. Under the lifetime budget a long session did not
    fail — it degraded, answering worse and worse as tools ran out, with nothing
    told to the user. Claiming the next turn is what resets it, in the same
    UPDATE that takes the turn, so there is no second write to get wrong."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="meta", owner_id=None)
            await db.commit()
            assert s.turn_tool_budget == get_settings().turn_tool_budget
            # Held as a plain string: the rollback below expires every ORM
            # attribute, and reading one back would attempt IO outside the async
            # context rather than telling us anything about budgets.
            sid = s.id

            claimed = await sess.claim_turn(db, sid)
            await db.commit()
            assert claimed is not None
            for _ in range(get_settings().turn_tool_budget):
                await sess.reserve(db, sid, is_external_search=False)
            await db.commit()
            with pytest.raises(sess.BudgetExceeded) as first:
                await sess.reserve(db, sid, is_external_search=False)
            assert first.value.kind == "turn_tool"
            await db.rollback()

            # Released on THIS connection rather than through release_turn,
            # which opens its own session from the app's configured URL — the
            # container hostname, unreachable from a host-side test, and it
            # swallows the failure by design. The fence on release_turn has its
            # own V2 coverage; what is under test here is the reset on claim.
            await db.execute(text("UPDATE agent_sessions SET turn_started_at = NULL "
                                  "WHERE id = :sid"), {"sid": sid})
            await db.commit()
            claimed2 = await sess.claim_turn(db, sid)
            await db.commit()
            assert claimed2 is not None

            # A fresh allowance, and the lifetime counter still telling the truth.
            status = await sess.reserve(db, sid, is_external_search=False)
            await db.commit()
            assert status.turn_tools_used == 1
            assert status.tools_used == get_settings().turn_tool_budget + 1
    finally:
        await engine.dispose()


async def test_a_research_session_keeps_the_lifetime_budget_it_never_resets():
    """A research run holds one session for its whole life and claims no turn.
    Under a per-turn counter nothing would ever zero it, so the run would die at
    the per-turn limit — well inside the 25-32 calls real runs actually use."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="research", owner_id=None)
            await db.commit()
            assert s.turn_tool_budget is None, "research must carry no per-turn budget"

            over_the_turn_limit = get_settings().turn_tool_budget + 5
            assert over_the_turn_limit < get_settings().session_tool_budget
            for _ in range(over_the_turn_limit):
                await sess.reserve(db, s.id, is_external_search=False)
            await db.commit()

            status = await sess.reserve(db, s.id, is_external_search=False)
            await db.commit()
            assert status.tools_used == over_the_turn_limit + 1
            assert status.tool_budget == get_settings().session_tool_budget
    finally:
        await engine.dispose()


async def test_a_stored_zero_budget_is_a_kill_switch_not_an_unset_default():
    """`session.tool_budget or default` read a stored 0 as "unset" and handed
    back 40 — so the one value you would reach for to switch a runaway session
    off was the only value that did nothing at all."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="research", owner_id=None)
            s.tool_budget = 0
            await db.commit()

            with pytest.raises(sess.BudgetExceeded) as exc:
                await sess.reserve(db, s.id, is_external_search=False)
            assert exc.value.limit == 0
    finally:
        await engine.dispose()


async def test_the_mcp_host_session_keeps_the_lifetime_budget_the_docs_promise():
    """V3-R6. B2 chose the budget regime from `kind`, and the MCP host opens its
    session with kind="meta" — so it was stamped with a per-turn budget of 15
    and never claimed a turn to reset it. Fifteen tool calls per PROCESS, not
    per turn, silently, in the face documented as keeping the lifetime budget.

    The regime is now an argument rather than an inference from a label that
    means something else. kind still says what the session is; per_turn says how
    it is metered, and the MCP host is the case where those two differ."""
    engine, mk = await _session()
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="meta", per_turn=False)
            await db.commit()
            assert s.turn_tool_budget is None, "the MCP host has no per-turn budget"

            over_the_turn_limit = get_settings().turn_tool_budget + 1
            for _ in range(over_the_turn_limit):
                status = await sess.reserve(db, s.id, is_external_search=False)
            await db.commit()
            assert status.tools_used == over_the_turn_limit
            assert status.tool_budget == get_settings().session_tool_budget

            # and a conversation still gets one, from the same function
            c = await sess.create_session(db, kind="meta")
            await db.commit()
            assert c.turn_tool_budget == get_settings().turn_tool_budget
    finally:
        await engine.dispose()


async def test_the_exit_is_not_charged_against_the_budget_it_needs(monkeypatch):
    """V7-Q2 — reproduced from a real conversation before it was fixed.

    `sess_d90c19451151`, "why there is large drawdowns? do some research and
    explain": the model spent all fifteen calls gathering (one snapshot, eight
    read_issuer_brief, six start_issuer_research), then called respond — and the
    gate was refused for `turn_tool budget exhausted: 15/15`. respond is the only
    way a turn ends, so the turn could no longer end at all: six more round trips
    at ~12k prompt tokens each, every one of them structurally incapable of
    producing an outcome, until max_turns ran out.

    The budget bounds how much EVIDENCE a turn gathers. A gate retrieves nothing
    — it is the turn's verdict and its exit — so charging it against that budget
    is charging someone's right to stop talking against their speaking time.
    Reflection tools were already free here for the same reason; the gate was the
    case nobody had had to think about, because nothing else can be refused into
    a state with no way out.
    """
    from exposure_workbench.tools import registry as reg

    engine, mk = await _session()
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="meta", owner_id=None)
            sid = s.id
            await db.commit()
            assert await sess.claim_turn(db, sid) is not None
            for _ in range(get_settings().turn_tool_budget):
                await sess.reserve(db, sid, is_external_search=False)
            await db.commit()

            ran: list[str] = []

            async def _fn(_db, **kw):
                ran.append(kw.get("who", "?"))
                return {"ok": True}

            r = reg.ToolRegistry()
            r.register(reg.Tool(name="a_read", description="", json_schema={}, fn=_fn,
                                tool_class=reg.READ, evidence=reg.Evidence()))
            r.register(reg.Tool(name="an_exit", description="", json_schema={}, fn=_fn,
                                tool_class=reg.GATE, evidence=reg.NOT_EVIDENCE))

            # The budget still works — that is the half that must not regress.
            refused = await reg.invoke(r, db, sid, "a_read", {"who": "read"})
            assert refused.get("error") == "budget_exceeded", refused
            await db.commit()

            # ...and the exit still opens.
            out = await reg.invoke(r, db, sid, "an_exit", {"who": "exit"})
            await db.commit()
            assert out.get("error") != "budget_exceeded", (
                "the gate was refused for lack of the budget it needs to spend nothing"
            )
            assert out == {"ok": True} and ran == ["exit"]
    finally:
        async with mk() as db, db.begin():
            await db.execute(text("DELETE FROM agent_steps WHERE session_id = :s"), {"s": sid})
            await db.execute(text("DELETE FROM agent_sessions WHERE id = :s"), {"s": sid})
        await engine.dispose()
