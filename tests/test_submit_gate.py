"""M9 submit_brief gate — structural checks (offline) + live citation validation."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from exposure_workbench.tools import research_tools as rt

load_dotenv(".env", override=True)


# ── offline: pure structural logic ────────────────────────────────────────────

def test_collect_citation_ids_gathers_from_cited_blocks_only():
    blocks = {
        "financial_summary": {"text": "x", "citations": ["calc_1", "fact_2"]},
        "key_changes": {"text": "y", "citations": ["chunk_3"]},
        "management_explanation": {"text": "", "citations": ["chunk_4"]},
        "market_context": {"text": "", "citations": ["src_5"]},
        "portfolio_implications": {"text": "", "citations": ["calc_6"]},
        "open_questions": {"text": "what about X?"},          # no citations key
    }
    ids = rt._collect_citation_ids(blocks)
    assert set(ids) == {"calc_1", "fact_2", "chunk_3", "chunk_4", "src_5", "calc_6"}


def test_cited_blocks_are_the_five_non_open_questions():
    assert set(rt._CITED_BLOCKS) == {
        "financial_summary", "key_changes", "management_explanation",
        "market_context", "portfolio_implications",
    }
    assert "open_questions" in rt._ALL_BLOCKS
    assert "open_questions" not in rt._CITED_BLOCKS


def test_block_schema_requires_citations_only_when_cited():
    cited = rt._block_schema(True)
    assert "citations" in cited["properties"] and "citations" in cited["required"]
    free = rt._block_schema(False)
    assert "citations" not in free["properties"]
    assert free["required"] == ["text"]


def test_submit_brief_schema_requires_all_six_blocks():
    from exposure_workbench.tools.definitions import build_read_registry
    reg = rt.register_research_tools(build_read_registry())
    schema = reg.get("submit_brief").json_schema
    assert set(schema["required"]) == set(rt._ALL_BLOCKS)


# ── live: the gate actually rejects out-of-trail citations ─────────────────────

pytest_live = pytest.mark.live


@pytest.mark.live
async def test_gate_rejects_citations_not_in_trail():
    """A fabricated citation id must be rejected by validate_citations."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from exposure_workbench.services import agent_session_service as sess
    from exposure_workbench.services import evidence_trail_service as trail

    url = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with mk() as db:
            s = await sess.create_session(db, kind="research")
            await db.commit()
            sid = s.id
        async with mk() as db:
            # nothing retrieved this session -> any citation is out of trail
            ok, problems = await trail.validate_citations(db, sid, ["calc_fabricated", "fact_nope"])
            assert ok is False
            assert {p["id"] for p in problems} == {"calc_fabricated", "fact_nope"}
            assert all(p["reason"] == "not_in_evidence_trail" for p in problems)
    finally:
        await engine.dispose()
