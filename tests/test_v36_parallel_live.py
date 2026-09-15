"""V36 Phase 3 preconditions, MEASURED (live: a real database, a real face).

Running several domain analysts at once is a performance change, and the plan
says its three preconditions are measured before they are assumed rather than
after something silently goes wrong. This file is the measurement. Each test
states the precondition and what failing it costs, so a red one is a decision
rather than a puzzle.

  1. seq allocation. `record_step` reads `max(seq)+1` and inserts, each in its
     own committed transaction. Two agents recording at the same instant read
     the same max. There is no unique constraint on (session_id, seq), so the
     collision is silent and the trace — the thing the whole round is read with
     — comes out with two different steps claiming one position.
  2. the MCP session. One `tool_session` is one client and one stream. The
     protocol multiplexes by request id; this repo has never sent two calls down
     one at the same time, and "it should work" is not a measurement.
  3. attribution. The row a tool call writes is written behind the MCP door by
     the registry wrapper, which the bearer tells the session and the message
     and not the actor. Serially the forensics can infer it from who spoke last;
     in parallel nothing can.

MEASURED 2026-09-15, against the fixture database and the fixture face:

  1  RED.   18 of 20 seq positions collided with two agents recording at once.
  2  GREEN on correctness: every concurrent call returns, every one leaves its
         own row, no two share a seq. UNMEASURED on benefit — every tool this
         desk has returns in tens of milliseconds against the fixture, so the
         difference between overlapped and queued is inside the noise: eight
         calls together against eight one at a time gave ratios of 1.91 and
         0.72 on two consecutive runs. Whether one stream overlaps anything is
         not answerable with these tools on this machine, and a threshold
         asserted on that number would be a coin flip in a test.
  3  RED by design (see the test).

So parallelism is off, and what it is waiting on is not three fixes. One is
mechanical (allocate seq under a lock). The other two are the same question:
does each domain analyst get its own tool session? A session each is a
connection each and a TOKEN each — and a token per analyst is where the actor
claim `auth/internal_token` argues against would stop being context and start
being identity. It is also the only shape in which "do concurrent tool calls
overlap" becomes a question worth measuring, since one session per analyst is
one stream per analyst by construction. Until that is decided, the serial path
runs and its trace is exact.
"""
from __future__ import annotations

import asyncio
import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import AgentSession, AgentStep
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.services import trace_service

pytestmark = pytest.mark.live

# These write and delete rows, and one of them deliberately hammers the step
# table from two tasks at once, so they run against the FIXTURE database rather
# than the desk's own. `load_dotenv(override=True)` above has already replaced
# whatever DATABASE_URL_LOCAL the shell set, which is why the override is read
# from a name .env does not define:
#
#   V36_DB_URL=…/exposure_battery MCP_URL=http://127.0.0.1:8105 pytest -m live tests/test_v36_parallel_live.py
URL = os.getenv("V36_DB_URL") or os.getenv("DATABASE_URL_LOCAL", "").replace(
    "/exposure_workbench", "/exposure_battery")

STEPS_EACH = 20


async def _record_many(mk, session_id: str, actor: str, n: int) -> None:
    for i in range(n):
        async with mk() as db:
            await trace_service.record_step(
                db, session_id, step_type="think", tool_name="think", args={"i": i},
                result_summary=actor, evidence_refs=[], actor=actor)
            await db.commit()


@pytest.mark.xfail(strict=True, reason="measured red: record_step allocates seq outside any lock")
@pytest.mark.asyncio
async def test_precondition_1_seq_survives_two_agents_recording_at_once():
    """If this is red, parallelism is off until `record_step` allocates under a
    lock: a trace with two steps at one seq cannot be read in order, and the
    communication table is the whole reading."""
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    async with mk() as db:
        s = await sess.create_session(db, kind="meta")
        await db.commit()
        sid = s.id
    try:
        await asyncio.gather(_record_many(mk, sid, "sub:a", STEPS_EACH),
                            _record_many(mk, sid, "sub:b", STEPS_EACH))
        async with mk() as db:
            seqs = (await db.execute(select(AgentStep.seq).where(AgentStep.session_id == sid))).scalars().all()
            dupes = (await db.execute(
                select(AgentStep.seq, func.count()).where(AgentStep.session_id == sid)
                .group_by(AgentStep.seq).having(func.count() > 1))).all()
        assert len(seqs) == 2 * STEPS_EACH, "every step was written"
        assert dupes == [], f"two steps share a seq: {dupes}"
        assert sorted(seqs) == list(range(1, 2 * STEPS_EACH + 1)), "and the positions are the whole range"
    finally:
        async with mk() as db:
            await db.execute(delete(AgentStep).where(AgentStep.session_id == sid))
            await db.execute(delete(AgentSession).where(AgentSession.id == sid))
            await db.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_precondition_2_one_tool_session_serves_two_callers_at_once():
    """One client, one stream, three calls in flight.

    Green on correctness: every call returns, every one leaves its own row, no
    two share a seq. The timing line below is printed and NOT asserted — see the
    module docstring: at these call durations the number is noise, and the
    honest reading is that this probe cannot answer whether the stream
    overlaps."""
    from exposure_workbench.agents.tool_session import tool_session
    from exposure_workbench.tools import faces

    import time

    calls = [("read_filings", {"ticker": "MSFT", "item": "7"}),
             ("read_filings", {"ticker": "AAPL", "item": "7"}),
             ("read_filings", {"ticker": "NVDA", "item": "7"})]
    async with mk_session() as (sid, mk):
        async with tool_session(faces.FACE_NAME_META, session_id=sid,
                                user_id="user_parallel_probe", message_id="msg_probe") as tools:
            t0 = time.monotonic()
            results = await asyncio.gather(*(tools.call(n, a) for n, a in calls))
            together = time.monotonic() - t0
            t0 = time.monotonic()
            for n, a in calls:
                await tools.call(n, a)
            one_at_a_time = time.monotonic() - t0
        # Printed, not asserted: what matters for correctness is that the stream
        # carried them; whether it OVERLAPPED them decides whether parallel
        # analysts buy anything, and a threshold on a shared machine is a flake.
        print(f"\n  {len(calls)} calls together {together:.3f}s · one at a time {one_at_a_time:.3f}s "
              f"· ratio {together / max(one_at_a_time, 1e-6):.2f} (noise at this duration; see the docstring)")
        transport = [r for r in results if isinstance(r, dict) and r.get("error") == "tool_transport_error"]
        assert transport == [], f"the stream could not carry concurrent calls: {transport}"
        async with mk() as db:
            rows = (await db.execute(
                select(AgentStep.seq, AgentStep.step_type, AgentStep.tool_name)
                .where(AgentStep.session_id == sid))).all()
        assert len(rows) == 2 * len(results), f"every call left its own trace row; got {rows}"
        assert len({r[0] for r in rows}) == len(rows), f"and no two share a seq: {rows}"


@pytest.mark.xfail(strict=True, reason="measured red by design: the bearer carries no actor")
@pytest.mark.asyncio
async def test_precondition_3_a_tool_call_cannot_yet_say_which_analyst_made_it():
    """Stated as a test because it is the one that decides the shape, and it is
    currently RED BY DESIGN: the bearer carries the session and the message, and
    `auth/internal_token` argues — in its own docstring — against carrying more.
    Until that argument is answered, the actor of a tool call is inferred from
    who spoke last, which is exact serially and meaningless in parallel.

    Passing means someone added the claim (or an equivalent) and parallelism may
    proceed; failing means it may not, and says why in one line.
    """
    from exposure_workbench.auth import internal_token

    claims = internal_token.InternalClaims("u", "sess_x", "meta", "msg_x")
    assert hasattr(claims, "actor"), (
        "a tool call's trace row cannot name the analyst that made it: the bearer has no actor claim, "
        "so registry.invoke writes actor=NULL and the forensics infers it from the last speaker. "
        "Serial is exact; parallel is not. Answer auth/internal_token's 'a token is not a place to "
        "stash context' before turning parallel_analysts on.")


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def mk_session():
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    async with mk() as db:
        s = await sess.create_session(db, kind="meta", owner_id="user_parallel_probe")
        await db.commit()
        sid = s.id
    try:
        yield sid, mk
    finally:
        async with mk() as db:
            await db.execute(delete(AgentStep).where(AgentStep.session_id == sid))
            await db.execute(delete(AgentSession).where(AgentSession.id == sid))
            await db.commit()
        await engine.dispose()
