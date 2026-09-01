"""P3/R5 — the transport does not change what is recorded (live).

Run with:  pytest -m live -k transport_parity

Route 2 is a real request to the resident face now (R4), so this file needs the
stack up. Two things have to be true of it and neither is checkable from here:
exposure-mcp must be reachable at MCP_URL_LOCAL — the loopback port compose
publishes for exactly this, since the service name only resolves inside the
network — and this suite's DATABASE_URL_LOCAL must be the same database that
container writes to, or the two routes are compared across two ledgers. Both
sides sign with the MCP_INTERNAL_SECRET in .env.

That is also why the sessions below are owned by a real user where they used to
be ownerless: the face runs its work under app_rls, and a session with no tenant
is a session whose rows RLS will not let it write. Residency made "whose turn is
this" load-bearing at a point where the in-memory pair let it stay None.

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

import json
import os
import re

import pytest
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.db.models import AgentStep
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.tools import faces, registry as R
from exposure_workbench.tools.registries import build_meta_registry

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
# The RUNTIME role. The parity tests read as the owner, which is fine for
# comparing two routes; an isolation test must not, because the table owner has
# rolbypassrls and its assertions cannot fail.
APP_URL = os.getenv("DATABASE_URL_LOCAL_APP",
                    "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")
# Every session these tests open belongs to somebody: see the module docstring.
PARITY_USER = os.getenv("PARITY_USER_ID", "user_demo_system")
# The face, from the host. The agents inside compose reach it by service name,
# which resolves nowhere out here; this is the loopback port the mcp service
# publishes so that this guard can exist at all.
MCP_URL_LOCAL = os.getenv("MCP_URL_LOCAL", "http://127.0.0.1:8104")


@pytest.fixture(autouse=True)
def the_face_on_the_host(monkeypatch):
    """Point tool_session at the published port, and nothing else.

    On the settings object rather than the environment, because settings are
    read once per process: an os.environ write here would take effect or not
    depending on which test module imported them first.
    """
    from exposure_workbench.app_state.settings import get_settings

    monkeypatch.setattr(get_settings(), "mcp_url", MCP_URL_LOCAL)


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
        # V15: a minted id is also a KEY in the table slice (quantities/rows are
        # keyed by ref), so keys are blanked the same way values are.
        return {_normalise(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    return value

CASES = [
    ("describe_issuer", {"ticker": "NVDA"}, "a plain read"),
    ("get_flow", {"ticker": "NVDA", "metric": "total_revenues", "months": 3, "last_n": 4}, "a ledgered calc"),
    ("get_flow", {"ticker": "NVDA"}, "a refusal: missing required argument"),
    ("get_flow", {"ticker": "NVDA", "metric": "total_revenues", "last_n": 0}, "a refusal: below the floor"),
    ("describe_issuer", {"ticker": "NVDA", "period_type": "annual"}, "a refusal: unknown argument"),
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
            direct = await sess.create_session(db, kind="meta", owner_id=PARITY_USER)
            through = await sess.create_session(db, kind="meta", owner_id=PARITY_USER)
            await db.commit()
            direct_id, through_id = direct.id, through.id

        # route 1 — the wrapper, called the way it was before P3
        async with mk() as db:
            direct_result = await R.invoke(registry, db, direct_id, tool_name, args)
            await db.commit()

        # route 2 — the same wrapper, reached over the resident face: a real
        # request, a real bearer, a different process, a different DB role.
        async with tool_session(faces.FACE_NAME_META, session_id=through_id,
                                user_id=PARITY_USER) as tools:
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
    session_id = None
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="meta", owner_id=PARITY_USER)
            await db.commit()
            session_id = s.id

        async with tool_session(faces.FACE_NAME_META, session_id=session_id,
                                user_id=PARITY_USER) as tools:
            await tools.call("describe_issuer", {"ticker": "NVDA"})      # +1
            await tools.call("think", {"thought": "free"})                   # +0
            await tools.call("get_flow", {"ticker": "NVDA"})          # +0, refused

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
    session_id = None
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="meta", owner_id=PARITY_USER)
            await db.commit()
            session_id = s.id

        # A face is the mount's now, and a client narrows it with deny rather
        # than by naming a different list — which is the same property from the
        # other side: what the token removes is not there to be called.
        async with tool_session(faces.FACE_NAME_META, session_id=session_id,
                                user_id=PARITY_USER,
                                deny=("start_issuer_research",)) as tools:
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


async def test_two_tenants_calling_at_once_do_not_see_each_other():
    """The one genuinely new risk in moving to a transport.

    The tenant is a contextvar, and a handler runs in whatever task the
    transport schedules it in — so an identity that happened to be inherited
    from the calling context would be a tenant mechanism that depends on how a
    library schedules work. R4 raised the stakes rather than settling them: the
    server outlives every turn now and serves both tenants below from the same
    process, so the binding is not "fixed when the pair was built" any more. It
    is the bearer each request carries, verified at the door and bound there.
    What this test proves is therefore no longer a property of construction but
    of the door, which is the one thing residency bought at a price.

    Two things this test has to get right, both of which it got wrong first:

    It runs on the app_rls connection, not the owner one the parity tests use.
    The table owner has rolbypassrls, so an isolation assertion made through it
    cannot fail — the first version of this test reported that B could see A's
    private book, which was the owner connection showing everything to
    everybody. Same trap V3-R found in the tenancy tests.

    And it asserts the GUC is actually set, because db/session.py's listener is
    registered by importing that module: a test that builds its own sessionmaker
    without it gets no tenant at all, every read falls back to is_public, and
    "B cannot see A" passes for the wrong reason.

    Run CONCURRENTLY, because a shared contextvar shows there and not in two
    sequential calls, where the last writer simply wins.
    """
    import asyncio
    import uuid

    from exposure_workbench.auth.context import current_user_ctx
    from exposure_workbench.db import session as db_session   # registers the tenant listener

    tag = uuid.uuid4().hex[:8]
    a, b = f"user_par_a_{tag}", f"user_par_b_{tag}"
    book = f"port_a_{tag}"

    owner_engine = create_async_engine(URL)
    app_engine = create_async_engine(APP_URL)
    app_mk = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False,
                                autoflush=False)
    sessions: dict[str, str] = {}
    try:
        async with owner_engine.begin() as c:
            for uid in (a, b):
                await c.execute(text(
                    "INSERT INTO users (id, email) VALUES (:i, :e) ON CONFLICT DO NOTHING"),
                    {"i": uid, "e": f"{uid}@example.test"})
            # A owns a private book; B owns none. Each must see their own plus
            # the public demo, and never the other's.
            await c.execute(text(
                "INSERT INTO portfolios (id, name, owner_id, is_public) "
                "VALUES (:i, 'A book', :o, false)"), {"i": book, "o": a})

        for uid in (a, b):
            current_user_ctx.set(uid)
            async with app_mk() as db:
                s = await sess.create_session(db, kind="meta", owner_id=uid)
                await db.commit()
                sessions[uid] = s.id

        # The mechanism is live: contextvar -> after_begin listener -> GUC. Without
        # this the isolation assertions below pass because nobody sees anything.
        current_user_ctx.set(a)
        async with app_mk() as db:
            guc = (await db.execute(text("SELECT current_setting('app.user_id', true)"))).scalar()
        assert guc == a, f"the tenant listener is not applying: {guc!r}"

        async def read_as(uid):
            async with tool_session(faces.FACE_NAME_META, session_id=sessions[uid],
                                    user_id=uid) as tools:
                return await tools.call("get_portfolio_snapshot", {})

        # Deliberately a THIRD value, and now it lives in a DIFFERENT PROCESS
        # from the one that answers: if either side inherited a tenant instead
        # of reading the token, both calls come back as this one.
        current_user_ctx.set("user_neither_of_them")
        for_a, for_b = await asyncio.gather(read_as(a), read_as(b))

        assert book in json.dumps(for_a), "A could not see A's own book"
        assert book not in json.dumps(for_b), "B saw A's book"
        assert "port_001" in json.dumps(for_b), "B saw nothing at all, so scope proves nothing"
    finally:
        async with owner_engine.begin() as c:
            for sid in sessions.values():
                await c.execute(text("DELETE FROM agent_steps WHERE session_id = :i"), {"i": sid})
                await c.execute(text("DELETE FROM agent_sessions WHERE id = :i"), {"i": sid})
            await c.execute(text("DELETE FROM portfolios WHERE id = :i"), {"i": book})
            await c.execute(text("DELETE FROM users WHERE id IN (:a, :b)"), {"a": a, "b": b})
        await app_engine.dispose()
        await owner_engine.dispose()
