"""V15-S5 submit_brief gate — six sections of blocks, one table, one resolver.

Offline: the schema is the exit's grammar (BLOCK_SCHEMAS, shared by identity
with `respond`), a section that points at nothing is refused structurally, and a
slot the table cannot name is refused with the section named. Live: a clean
submission persists the prose, the filled blocks and the per-section ids.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv

from exposure_workbench.services import quantities as qn
from exposure_workbench.services import table as tbl
from exposure_workbench.tools import research_tools as rt
from exposure_workbench.tools.meta_tools import BLOCK_SCHEMAS

load_dotenv(".env", override=True)

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")

CALC, CHUNK = "calc_hand_built", "chunk_hand_built"


def _table() -> tbl.Table:
    """A table built by hand: one figure under one calc id, one passage."""
    t = tbl.Table()
    t.quantities[CALC] = {"stat.latest": qn.Quantity(13_237_000_000.0, qn.MONEY, "stat.latest", CALC)}
    t.passages[CHUNK] = "Demand for our data center products remained strong through the quarter."
    t.rows.update({CALC: qn.KIND_SCALAR, CHUNK: "passage"})
    t.refs.update({CALC, CHUNK})
    return t


def _para(*runs, cites=None) -> dict:
    block = {"type": "paragraph", "runs": list(runs)}
    if cites:
        block["cites"] = list(cites)
    return block


def _sections(**overrides) -> dict:
    """Six clean sections against `_table()`; override any one to break it."""
    cited = {"blocks": [_para("Management described demand as firm.", cites=[CHUNK])]}
    base = {
        "financial_summary": {"blocks": [_para("Revenue reached ", {"ref": CALC, "name": "stat.latest"}, ".")]},
        "key_changes": cited,
        "management_explanation": cited,
        "market_context": cited,
        "portfolio_implications": cited,
        "open_questions": {"blocks": [_para("Will the mix shift hold next quarter?")]},
    }
    return {**base, **overrides}


@pytest.fixture
def offline_gate(monkeypatch):
    """A run exists for the session and the table is the hand-built one; the
    gate never touches a database before it decides."""
    async def run(db, session_id):
        return SimpleNamespace(id="rrun_test", company_id="co_test", owner_id=None)

    async def load(db, session_id):
        return _table()

    monkeypatch.setattr(rt, "_run_for_session", run)
    monkeypatch.setattr(tbl, "load", load)


# ── offline ───────────────────────────────────────────────────────────────────

def test_schema_requires_all_six_sections_and_reuses_the_block_grammar():
    """The brief and the reply are ONE grammar: the section's items are the very
    list `respond` validates against, not a copy that could drift."""
    from exposure_workbench.tools.registries import build_research_registry
    schema = build_research_registry().get("submit_brief").json_schema
    assert set(schema["required"]) == set(rt.SECTIONS) == {
        "financial_summary", "key_changes", "management_explanation",
        "market_context", "portfolio_implications", "open_questions"}
    assert schema["additionalProperties"] is False
    for name in rt.SECTIONS:
        section = schema["properties"][name]
        assert section["required"] == ["blocks"] and section["additionalProperties"] is False
        assert section["properties"]["blocks"]["minItems"] == 1
        assert section["properties"]["blocks"]["items"]["oneOf"] is BLOCK_SCHEMAS
    assert "confidence_flags" not in schema["properties"]


async def test_a_section_that_points_at_nothing_is_missing_citations(offline_gate):
    """Prose alone resolves trivially — there is nothing to look up — which is
    exactly why the structural rule exists: a cited section must lean on an id."""
    out = await rt._submit_brief(None, **_sections(
        market_context={"blocks": [_para("The stock traded sideways after the print.")]}))
    assert out["error"] == "missing_citations"
    assert out["sections"] == ["market_context"]


async def test_open_questions_needs_no_ids(offline_gate, monkeypatch):
    """The exemption is the one section that states nothing — reaching the write
    proves the structural rule and the resolver both let it through."""
    written = []
    db = SimpleNamespace(add=written.append)

    async def flush():
        pass
    db.flush = flush
    out = await rt._submit_brief(db, **_sections())
    assert out["accepted"] is True and out["citations_validated"] == 2
    assert written[0].open_questions == "Will the mix shift hold next quarter?"
    assert set(written[0].block_citations) == set(rt.CITED_SECTIONS)


async def test_a_slot_with_an_unknown_name_names_the_section(offline_gate):
    """The refusal is the verdict `respond` would give, plus which section it
    was in — the model fixes that block, not the brief."""
    out = await rt._submit_brief(None, **_sections(
        key_changes={"blocks": [_para("Gross margin was ", {"ref": CALC, "name": "gross_margin"}, ".",
                                      cites=[CHUNK])]}))
    assert out["error"] == "unknown_name"
    assert out["section"] == "key_changes"
    (problem,) = out["problems"]
    assert problem["at"] == "blocks[0].runs[1]" and problem["available"] == ["stat.latest"]


async def test_an_id_off_the_table_names_the_section(offline_gate):
    out = await rt._submit_brief(None, **_sections(
        portfolio_implications={"blocks": [_para("Held across two books.", cites=["chunk_fabricated"])]}))
    assert out["error"] == "not_on_table"
    assert out["section"] == "portfolio_implications"
    assert [p["id"] for p in out["problems"]] == ["chunk_fabricated"]


def test_submit_brief_is_the_only_gate_and_declares_no_evidence():
    """A gate's verdict puts nothing on the table: the ids a refusal echoes must
    not become citable on the next attempt."""
    from exposure_workbench.tools.registries import build_research_registry
    from exposure_workbench.tools.registry import GATE
    tool = build_research_registry().get("submit_brief")
    assert tool.tool_class == GATE and tool.evidence is None


# ── live ──────────────────────────────────────────────────────────────────────

@pytest.mark.live
async def test_a_clean_submission_persists_text_blocks_and_per_section_ids():
    """End to end against the real table: a session whose one completed step
    declared a calc and a passage, a brief that slots the calc and cites the
    passage, and a row holding the prose at reader precision, the filled blocks
    and the ids under each section. Rolled back at the end — nothing is left."""
    from sqlalchemy import text as sql
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from exposure_workbench.analytics import display_conventions as dc
    from exposure_workbench.db.models import ResearchRun
    from exposure_workbench.services import agent_session_service as sess
    from exposure_workbench.services import brief_service, trace_service
    from exposure_workbench.tools import registry
    from exposure_workbench.utils.ids import new_research_run_id

    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with mk() as db:
            calc = (await db.execute(sql(
                "SELECT id, (result->>'value')::float FROM calc_ledger "
                "WHERE operation = 'stat.latest' AND result ? 'value' LIMIT 1"))).first()
            chunk = (await db.execute(sql("SELECT id FROM filing_chunks LIMIT 1"))).scalar_one_or_none()
            company_id = (await db.execute(sql("SELECT id FROM companies LIMIT 1"))).scalar_one_or_none()
            if calc is None or chunk is None or company_id is None:
                pytest.skip("needs a ledgered stat.latest, a filing chunk and a company")
            calc_id, value = calc

            s = await sess.create_session(db, kind="research", owner_id=None)
            db.add(ResearchRun(id=new_research_run_id(), company_id=company_id, status="running",
                               agent_session_id=s.id, triggered_by="test"))
            await db.flush()
            await trace_service.record_step(
                db, s.id, step_type="tool_call", tool_name="get_stat", args={}, result_summary="",
                evidence_refs=[{"type": "calc", "id": calc_id}, {"type": "chunk", "id": chunk}],
                status="completed")
            registry._session_ctx.set(s.id)

            cited = {"blocks": [_para("Management described demand as firm.", cites=[chunk])]}
            out = await rt._submit_brief(db, **{
                "financial_summary": {"blocks": [_para("The latest reading was ",
                                                        {"ref": calc_id, "name": "stat.latest"}, ".")]},
                "key_changes": cited, "management_explanation": cited,
                "market_context": cited, "portfolio_implications": cited,
                "open_questions": {"blocks": [_para("Will it hold next quarter?")]},
            })
            assert out.get("accepted") is True, out
            assert out["citations_validated"] == 2

            row = (await db.execute(sql(
                "SELECT financial_summary, blocks, block_citations, citations "
                "FROM issuer_briefs WHERE id = :id"), {"id": out["brief_id"]})).one()
            prose, blocks, per_section, citations = row
            assert prose == f"The latest reading was {dc.display(value, qn.MONEY)}."
            slot = blocks["financial_summary"][0]["runs"][1]["slot"]
            assert slot["ref"] == calc_id and slot["label"] == "stat.latest"
            assert slot["value"] == pytest.approx(value)
            assert set(per_section) == set(rt.CITED_SECTIONS)
            assert per_section["financial_summary"] == [calc_id]
            assert per_section["key_changes"] == [chunk]
            assert citations == sorted({calc_id, chunk})

            # The read side hands the blocks back under each section.
            seen = await brief_service.latest_visible(db, company_id)
            assert seen["brief_id"] == out["brief_id"]
            assert seen["blocks"]["financial_summary"]["blocks"] == blocks["financial_summary"]
            assert seen["blocks"]["open_questions"]["blocks"][0]["runs"] == ["Will it hold next quarter?"]
            await db.rollback()
    finally:
        await engine.dispose()
