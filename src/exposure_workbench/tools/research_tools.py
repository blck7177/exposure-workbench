"""Research-face tools (M6/M9) — external search + the submit_brief gate.

Registered onto the base read registry to form FACE_RESEARCH. submit_brief is
the session's exit, and since V15-S5 it is the SAME exit `respond` is: six
sections, each a list of blocks in the grammar of tools/meta_tools.BLOCK_SCHEMAS,
every pointer resolved against the session's table by services/resolver.py. The
brief used to have its own gate — prose with figures in it, a number extractor,
a per-block value search — and that gate was the second implementation of a
rule the desk wanted to hold once. Now there is one grammar, one table and one
resolver, and this module only shapes the verdict per section and persists what
was accepted. A rejected submission names the section and the block; nothing
partial is ever written.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import IssuerBrief, ResearchRun
from exposure_workbench.services import answer_blocks as ab
from exposure_workbench.services import research_search_service as rss
from exposure_workbench.services import resolver
from exposure_workbench.services import table as tbl
from exposure_workbench.tools.meta_tools import BLOCK_SCHEMAS
from exposure_workbench.tools.registry import (
    DELEGATION, GATE, NOT_EVIDENCE, Evidence, Tool, ToolRegistry, current_session_id,
)
from exposure_workbench.utils.ids import new_brief_id

logger = logging.getLogger(__name__)

# The five evidence-bearing sections, plus open_questions — the one section that
# need not point at anything, because a question is not a factual claim. The
# same six names are the brief's text columns (db/models.IssuerBrief) and the
# keys brief_service reads back.
CITED_SECTIONS = ("financial_summary", "key_changes", "management_explanation",
                  "market_context", "portfolio_implications")
SECTIONS = CITED_SECTIONS + ("open_questions",)


async def _run_for_session(db: AsyncSession, session_id: str) -> ResearchRun | None:
    return (
        await db.execute(select(ResearchRun).where(ResearchRun.agent_session_id == session_id))
    ).scalar_one_or_none()


# ── external research (M6) ───────────────────────────────────────────────────────

async def _search_external_research(db: AsyncSession, ticker: str, query: str, reason: str,
                                    days: int | None = None) -> dict:
    """Delegation tool: reason is REQUIRED by schema — the judgment is logged.
    Persists results and returns citable src_ ids.

    V19: on both faces. Inside a research run the sources belong to the run;
    in a chat turn there is no run and `research_run_id` stays NULL — the row
    is keyed by the company either way, and the src_ id goes on the session's
    table through the same declaration. A ticker the desk has not met is
    admitted from the listed universe first (company_service.admit, V17), so
    "what is the news on X" works for any listed filer; an ETF or a name with
    no CIK is refused with its reason, because a source row is issuer-scoped
    and there is no issuer to hang it on.
    """
    from exposure_workbench.services import company_service
    tk = ticker.upper()
    try:
        company = await company_service.admit(db, tk)
    except company_service.CompanyNotFound:
        return {"error": "company_not_found", "ticker": tk,
                "detail": "not a listed symbol in this desk's universe"}
    except (company_service.NotInvestigable, company_service.NotAnSecFiler) as e:
        return {"error": "not_investigable", "ticker": tk, "detail": str(e)}
    run = await _run_for_session(db, current_session_id())
    composed = rss.compose_query(company.name, tk, query)
    try:
        sources = await rss.search(db, company.id, composed, research_run_id=run.id if run else None,
                                   days=days)
    except rss.ResearchProviderUnavailable as e:
        return {"error": "provider_unavailable", "detail": str(e)}
    return {"ticker": tk, "query": composed, "days": days, "reason": reason, "sources": sources}


# ── submit_brief gate (M9, V15-S5) ────────────────────────────────────────────────

async def _submit_brief(db: AsyncSession, **sections) -> dict:
    """The exit: six sections of blocks, every pointer on the table, or a refusal
    naming the section and the block.

    The table is loaded once and every section is resolved against it, because
    the brief is one answer written in six parts — a passage read while writing
    key_changes is just as much on the table for market_context. What stays
    per-section is the structural rule from V3: each of the five cited sections
    must lean on at least one id of its own. Without it a section could be all
    prose, pass every check (there is nothing to resolve), and read to the desk
    as a supported paragraph that supports nothing.

    Persistence happens only after all six are clean. There is no partial
    brief: a section the resolver refused is a section the model gets to fix,
    and the retry is cheaper than a reader discovering a hole.
    """
    session_id = current_session_id()
    run = await _run_for_session(db, session_id)
    if run is None:
        return {"error": "no_research_run", "detail": "submit_brief called outside a research run"}

    missing = [name for name in CITED_SECTIONS if not ab.refs_in(sections[name]["blocks"])]
    if missing:
        return {"error": "missing_citations", "sections": missing,
                "detail": "every section except open_questions must point at evidence — a slot "
                          "{ref, name}, a `cites` list, or a series/absence ref — from a tool "
                          "result this session"}

    table = await tbl.load(db, session_id)
    accepted: dict[str, dict] = {}
    for name in SECTIONS:
        blocks = sections[name]["blocks"]
        verdict = resolver.resolve_against(blocks, table)
        if not verdict.ok:
            return {**verdict.as_refusal(), "section": name}
        accepted[name] = resolver.accepted(blocks, verdict)

    # The flat list is the union over all six: an id open_questions pointed at
    # was resolved like any other and belongs on the record, even though the
    # per-section map keeps to the five sections that are required to cite.
    citations = sorted({ref for a in accepted.values() for ref in a["citations"]})
    brief_id = new_brief_id()
    db.add(IssuerBrief(
        id=brief_id, research_run_id=run.id, company_id=run.company_id,
        owner_id=run.owner_id,   # V2-C: brief belongs to who triggered the research (RLS WITH CHECK)
        **{name: accepted[name]["text"] for name in SECTIONS},
        blocks={name: accepted[name]["blocks"] for name in SECTIONS},
        citations=citations,
        block_citations={name: accepted[name]["citations"] for name in CITED_SECTIONS},
    ))
    await db.flush()
    return {"accepted": True, "brief_id": brief_id, "citations_validated": len(citations)}


# ── schema ────────────────────────────────────────────────────────────────────────

# One section: a non-empty list of blocks in the exit's grammar. BLOCK_SCHEMAS is
# imported, not copied — the brief and the reply are the same grammar, and a
# block shape added there is a block shape a brief may use.
#
# Closed, and it matters more here than anywhere else: _submit_brief takes
# **sections, so an unknown key is not a TypeError — it is dropped in silence,
# and a mistyped section name would produce a brief that looks complete and is
# missing a section.
_SECTION_SCHEMA = {
    "type": "object",
    "properties": {"blocks": {"type": "array", "minItems": 1, "items": {"oneOf": BLOCK_SCHEMAS},
                              "description": "the section, in reading order"}},
    "required": ["blocks"], "additionalProperties": False,
}

SUBMIT_BRIEF_SCHEMA = {
    "type": "object",
    "properties": {name: _SECTION_SCHEMA for name in SECTIONS},
    "required": list(SECTIONS), "additionalProperties": False,
}


def register_search_tool(reg: ToolRegistry) -> ToolRegistry:
    """The one registration of the web search — called by both registry builders
    (V19), so the meta face and the research face carry the same tool with the
    same budget key and the same evidence declaration."""
    reg.register(Tool(
        name="search_external_research",
        display="Searching the web for “{query}”",
        description=(
            "Search the web for what the filings cannot hold: news, guidance, an event "
            "after the last report, industry or regulatory developments — and anything the "
            "user asks you to look up. Each result is a src_ id on the table; a sentence "
            "resting on one names it in the block's cites. reason states why the filed "
            "evidence is insufficient."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "query": {"type": "string", "description":
                      "what to look for; the issuer's name is added by the tool, so do not repeat it"},
            "reason": {"type": "string", "description": "why this search is needed now"},
            "days": {"type": ["integer", "null"], "minimum": 1, "maximum": 365, "description":
                     "restrict to news published within this many days (the past week is 7); "
                     "omit for no time restriction"},
        }, "required": ["ticker", "query", "reason"], "additionalProperties": False},
        fn=_search_external_research, tool_class=DELEGATION, budget_key="external_search",
        # Its sources are the answer's evidence: src_ ids go on the table.
        evidence=Evidence(),
    ))
    return reg


def register_research_tools(reg: ToolRegistry) -> ToolRegistry:
    register_search_tool(reg)
    reg.register(Tool(
        name="submit_brief",
        display="Resolving every figure in the brief against the table, then filing it",
        description=(
            "Submit the Issuer Risk Brief: six sections (financial_summary, key_changes, "
            "management_explanation, market_context, portfolio_implications, open_questions), "
            "each a list of BLOCKS. A figure is a SLOT {ref, name} using a name from the `table` "
            "a tool result carried — the reader is shown the table's own value; you never write "
            "a number. Blocks: `paragraph` (runs of strings and slots; `cites`: the chunk_/src_ "
            "ids its prose rests on), `metric_table` (rows of slots only — the header and each "
            "row's label are derived from the slots' names), `chart` "
            "(kind + series_ref), `trend` (text + series_ref), `absence` (text + absence_ref), "
            "`action` (text + task_ref). Text carries no digits except dates. Every section but "
            "open_questions must point at evidence from this session. A refusal names the "
            "section and the block; fix that block and resubmit."
        ),
        json_schema=SUBMIT_BRIEF_SCHEMA,
        fn=_submit_brief, tool_class=GATE,
        evidence=NOT_EVIDENCE,  # the filing verdict — same reason respond declares none
    ))
    return reg
