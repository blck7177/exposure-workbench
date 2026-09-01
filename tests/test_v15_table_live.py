"""V15-S2a — the absence path end to end, through the wrapper and the gate (live).

The first red test of the plan: cite, through `respond`, an `absence_id` that
`get_flow` minted when it refused. Before the table, the refusal's id sat under
an `error` key, the harvester skipped anything that looked like an error, and
the one id the model was told to cite was the one it could not. Now the tool's
declaration puts it on the table like any calc id, the step records it, and
the resolver finds it by lookup. The other two tests are the plain path (a
slot naming a figure from the table a tool just returned) and the shape rule
(a slot with a value never reaches the gate at all).
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

from exposure_workbench.db.models import AgentStep
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.tools import registry as R
from exposure_workbench.tools.registries import build_meta_registry

pytestmark = pytest.mark.live

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


async def _mk():
    engine = create_async_engine(URL)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _session(mk) -> str:
    async with mk() as db:
        s = await sess.create_session(db, kind="meta")
        await db.commit()
        return s.id


async def _last_step(mk, sid: str) -> AgentStep:
    async with mk() as db:
        return (await db.execute(
            select(AgentStep).where(AgentStep.session_id == sid).order_by(AgentStep.seq.desc())
        )).scalars().first()


async def test_a_refused_read_mints_an_absence_the_answer_can_point_at():
    """MSFT files depreciation every quarter and never the combined D&A line
    (test_v11_absence_live). The refusal is evidence; the answer relays it."""
    engine, mk = await _mk()
    try:
        reg = build_meta_registry()
        sid = await _session(mk)

        async with mk() as db:
            got = await R.invoke(reg, db, sid, "get_flow",
                                 {"ticker": "MSFT", "metric": "depreciation_amortization", "months": 12})
            await db.commit()
        assert got["error"] == "not_reported", got
        absence_id = got["absence_id"]
        assert absence_id.startswith("calc_")
        assert got["table"]["rows"] == {absence_id: "absence"}, (
            "the slice the model reads says what kind of row the refusal minted")

        step = await _last_step(mk, sid)
        assert step.tool_name == "get_flow" and step.status == "completed"
        assert {"type": "calc", "id": absence_id} in step.evidence_refs, step.evidence_refs

        async with mk() as db:
            out = await R.invoke(reg, db, sid, "respond", {"blocks": [
                {"type": "absence", "absence_ref": absence_id,
                 "text": "This desk holds no depreciation and amortization line for MSFT; "
                         "it files depreciation on its own, which is a statement about coverage."},
            ]})
            await db.commit()
        assert out.get("responded") is True, out
        assert out["citations"] == [absence_id]
        assert out["verified"]["figures"] == 0
    finally:
        await engine.dispose()


async def test_a_slot_naming_a_figure_from_the_snapshot_table_is_accepted():
    engine, mk = await _mk()
    try:
        reg = build_meta_registry()
        sid = await _session(mk)

        async with mk() as db:
            snap = await R.invoke(reg, db, sid, "get_portfolio_snapshot", {})
            await db.commit()
        if snap.get("error"):
            pytest.skip(f"no portfolio to read: {snap['error']}")
        quantities = snap["table"]["quantities"]
        run_id, name = next(
            (ref, n) for ref, names in quantities.items() if ref.startswith("run_")
            for n in names if n.startswith("issuer_exposures.") and n.endswith(".weight"))
        ticker = name.split(".")[1]

        async with mk() as db:
            out = await R.invoke(reg, db, sid, "respond", {"blocks": [
                {"type": "paragraph", "runs": [f"{ticker} weighs ", {"ref": run_id, "name": name}, " of the book."]},
            ]})
            await db.commit()
        assert out.get("responded") is True, out
        assert out["verified"]["figures"] == 1 and out["citations"] == [run_id]
        [m] = out["verified"]["matches"]
        assert m["label"] == name and m["unit_class"] == "RATIO" and m["source_id"] == run_id
        assert "%" in out["text"], out["text"]
    finally:
        await engine.dispose()


async def test_a_slot_with_a_value_is_refused_by_the_schema_and_never_reaches_the_gate():
    """Law B: the value form is refused as a shape, before budget, before the
    resolver. The trace shows a rejected respond and no verdict."""
    engine, mk = await _mk()
    try:
        reg = build_meta_registry()
        sid = await _session(mk)
        async with mk() as db:
            out = await R.invoke(reg, db, sid, "respond", {"blocks": [
                {"type": "paragraph", "runs": ["MSFT weighs ", {"ref": "run_1d6e9e05bee6", "value": 0.16}, "."]},
            ]})
            await db.commit()
        assert out["error"] == "invalid_arguments", out
        assert "blocks.0.runs.1.value" in [p["field"] for p in out["problems"]], out["problems"]

        step = await _last_step(mk, sid)
        assert step.tool_name == "respond" and step.status == "rejected"
        assert step.evidence_refs == []
    finally:
        await engine.dispose()
