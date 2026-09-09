"""V31 submit_brief gate — six sections of CLAIMS, one ledger, one gate.

The brief was the last thing on the desk checked by a second grammar. V24 gave
the reply typed claims and left the brief with pointers-in-a-sentence; V31 makes
a section an answer in exactly `claims.ANSWER_SCHEMA`, checked by
`claims.check`. One grammar and one gate is the standing rule, and what it buys
here is that a relation added to the reply is a relation a brief may use the
same day, with the same refusal.

Offline: the schema is the reply's grammar by identity, a cited section that
rests on nothing is refused structurally, and a claim the ledger cannot resolve
is refused with the section named. Live: a clean submission persists the prose,
the rendered blocks, the per-section ids and the claims beside them.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv

from exposure_workbench.services import claims as C
from exposure_workbench.services import facts as F
from exposure_workbench.services import ledger as L
from exposure_workbench.tools import research_tools as rt

load_dotenv(".env", override=True)

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")

CALC, CHUNK = "calc_hand_built", "chunk_hand_built"
FIG = F.Fact(id="f_a1b2c3d4e5f6", kind=F.SCALAR, measure="revenue", subject="NVDA", unit=F.__dict__.get("MONEY", "MONEY"),
             value=13_237_000_000.0, as_of="2026-01-25", sources=(CALC,))
PAS = F.Fact(id="f_0f1e2d3c4b5a", kind=F.PASSAGE, measure="10-Q Item 2", subject="NVDA", as_of="2026-02-26",
             text="Demand for our data center products remained strong through the quarter.", sources=(CHUNK,))


def _ledger() -> L.Ledger:
    """A ledger built by hand: one figure, one passage."""
    return L.Ledger.of_facts([FIG, PAS])


def _quote(fid=None) -> dict:
    """A section resting on the passage: the sentence says it, the claim carries
    the words verbatim."""
    return {"claims": [{"id": "c1", "relation": "quote", "of": fid or PAS.id,
                        "span": "Demand for our data center products remained strong"}],
            "prose": ["Management described demand as firm: {c1}."]}


def _sections(**overrides) -> dict:
    """Six clean sections against `_ledger()`; override any one to break it."""
    base = {
        "financial_summary": {"claims": [{"id": "c1", "relation": "level", "of": FIG.id}],
                              "prose": ["Revenue reached {c1}."]},
        "key_changes": _quote(),
        "management_explanation": _quote(),
        "market_context": _quote(),
        "portfolio_implications": _quote(),
        "open_questions": {"claims": [], "prose": ["Will the mix shift hold next quarter?"]},
    }
    return {**base, **overrides}


@pytest.fixture
def offline_gate(monkeypatch):
    """A run exists for the session and the ledger is the hand-built one; the
    gate never touches a database before it decides."""
    async def run(db, session_id):
        return SimpleNamespace(id="rrun_test", company_id="co_test", owner_id=None)

    async def load(db, session_id):
        return _ledger()

    monkeypatch.setattr(rt, "_run_for_session", run)
    monkeypatch.setattr(rt.ledger, "load", load)


# ── offline ───────────────────────────────────────────────────────────────────

def test_schema_requires_all_six_sections_and_is_the_replys_grammar_by_identity():
    """The brief and the reply are ONE grammar: a section IS the object `respond`
    validates, not a copy that could drift. Identity, not equality — a copy that
    starts equal is a copy that stops being equal."""
    from exposure_workbench.tools.registries import build_research_registry
    schema = build_research_registry().get("submit_brief").json_schema
    assert set(schema["required"]) == set(rt.SECTIONS) == {
        "financial_summary", "key_changes", "management_explanation",
        "market_context", "portfolio_implications", "open_questions"}
    assert schema["additionalProperties"] is False
    for name in rt.SECTIONS:
        assert schema["properties"][name] is C.ANSWER_SCHEMA
    assert "confidence_flags" not in schema["properties"]


async def test_a_section_that_rests_on_nothing_is_missing_citations(offline_gate):
    """Prose with no claim passes the gate trivially — there is nothing to check
    — which is exactly why the structural rule exists: a cited section must rest
    on at least one claim pointing at a fact."""
    out = await rt._submit_brief(None, **_sections(
        market_context={"claims": [], "prose": ["The stock traded sideways after the print."]}))
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
    # V31 §8 B1: what each sentence asserted, beside where the figure came from
    assert written[0].claims_by_section["financial_summary"][0]["relation"] == "level"
    assert set(written[0].claims_by_section) == set(rt.SECTIONS)


async def test_a_claim_the_ledger_does_not_hold_names_the_section(offline_gate):
    """The refusal is the verdict `respond` would give, plus which section it was
    in — the model fixes that claim, not the brief."""
    out = await rt._submit_brief(None, **_sections(
        key_changes={"claims": [{"id": "c1", "relation": "level", "of": "f_000000000000"}],
                     "prose": ["Gross margin was {c1}."]}))
    assert out["error"] == "not_on_ledger"
    assert out["section"] == "key_changes"
    assert [p["id"] for p in out["problems"]] == ["f_000000000000"]


async def test_the_old_blocks_shape_is_not_the_grammar(offline_gate):
    """A section written the V24 way rests on nothing, because evidence is a
    claim now; the structural rule catches it before the gate. A section that
    does carry claims but in the old container is malformed."""
    out = await rt._submit_brief(None, **_sections(
        key_changes={"blocks": [{"type": "paragraph", "text": f"Gross margin was {FIG.id}."}]}))
    assert out["error"] == "missing_citations" and out["sections"] == ["key_changes"]
    out2 = await rt._submit_brief(None, **_sections(
        key_changes={"claims": [{"id": "c1", "relation": "level", "of": FIG.id}],
                     "blocks": [{"type": "paragraph", "text": "x"}]}))
    assert out2["error"] == "malformed_answer" and out2["section"] == "key_changes"


async def test_an_id_off_the_ledger_names_the_section(offline_gate):
    out = await rt._submit_brief(None, **_sections(
        portfolio_implications={"claims": [{"id": "c1", "relation": "quote", "of": "chunk_fabricated",
                                            "span": "held across two books"}],
                                "prose": ["Held across two books: {c1}."]}))
    assert out["error"] == "not_on_ledger"
    assert out["section"] == "portfolio_implications"
    assert [p["id"] for p in out["problems"]] == ["chunk_fabricated"]


def test_submit_brief_is_the_only_gate_and_declares_no_evidence():
    """A gate's verdict puts nothing on the table: the ids a refusal echoes must
    not become citable on the next attempt."""
    from exposure_workbench.tools.registries import build_research_registry
    from exposure_workbench.tools.registry import GATE
    from exposure_workbench.services import fact_adapters as fa
    tool = build_research_registry().get("submit_brief")
    assert tool.tool_class == GATE and fa.ADAPTERS["submit_brief"] is fa.no_facts


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
            fig = F.fact(F.SCALAR, "stat.latest", subject="NVDA", unit="MONEY", value=float(value),
                         as_of="2026-01-25", sources=(calc_id,))
            pas = F.fact(F.PASSAGE, "10-K Item 7", subject="NVDA", as_of="2026-02-26",
                         text="Management described demand as firm through the period.", sources=(chunk,))
            await trace_service.record_step(
                db, s.id, step_type="tool_call", tool_name="read_fundamentals", args={}, result_summary="",
                evidence_refs=[L.step_entry([fig, pas])], status="completed")
            registry._session_ctx.set(s.id)

            cited = {"claims": [{"id": "c1", "relation": "quote", "of": pas.id,
                                 "span": "Management described demand as firm"}],
                     "prose": ["The filing says it: {c1}."]}
            out = await rt._submit_brief(db, **{
                "financial_summary": {"claims": [{"id": "c1", "relation": "level", "of": fig.id}],
                                      "prose": ["The latest reading was {c1}."]},
                "key_changes": cited, "management_explanation": cited,
                "market_context": cited, "portfolio_implications": cited,
                "open_questions": {"claims": [], "prose": ["Will it hold next quarter?"]},
            })
            assert out.get("accepted") is True, out
            assert out["citations_validated"] == 2

            row = (await db.execute(sql(
                "SELECT financial_summary, blocks, block_citations, citations, claims_by_section "
                "FROM issuer_briefs WHERE id = :id"), {"id": out["brief_id"]})).one()
            prose, blocks, per_section, citations, by_claim = row
            assert prose == f"The latest reading was {dc.display(value, 'MONEY')}."
            assert by_claim["financial_summary"][0]["of"] == fig.id
            filled = blocks["financial_summary"][0]["runs"][1]["fact"]
            assert filled["id"] == fig.id and filled["measure"] == "stat.latest" and filled["sources"] == [calc_id]
            assert filled["value"] == pytest.approx(value)
            assert set(per_section) == set(rt.CITED_SECTIONS)
            assert per_section["financial_summary"] == [fig.id]
            assert per_section["key_changes"] == [pas.id]
            assert citations == sorted({fig.id, pas.id})

            # The read side hands the blocks back under each section.
            seen = await brief_service.latest_visible(db, company_id)
            assert seen["brief_id"] == out["brief_id"]
            assert seen["blocks"]["financial_summary"]["blocks"] == blocks["financial_summary"]
            assert seen["blocks"]["open_questions"]["blocks"][0]["runs"] == ["Will it hold next quarter?"]
            await db.rollback()
    finally:
        await engine.dispose()
