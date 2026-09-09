"""Research-face tools (M6/M9) — external search + the submit_brief gate.

Registered onto the base read registry to form FACE_RESEARCH. submit_brief is
the session's exit, and since V15-S5 it is the SAME exit `respond` is: six
sections, each a list of blocks in the grammar of services/answer.py, every
pointer checked against the session's ledger by services/gate.py (V24). The
brief used to have its own gate — prose with figures in it, a number extractor,
a per-block value search — and that gate was the second implementation of a
rule the desk wanted to hold once. Now there is one grammar, one ledger and one
gate, and this module only shapes the verdict per section and persists what
was accepted. A rejected submission names the section and the block; nothing
partial is ever written.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import IssuerBrief, ResearchRun
from exposure_workbench.services import claims, ledger
from exposure_workbench.services import research_search_service as rss
from exposure_workbench.tools.registry import (
    DELEGATION, GATE, Tool, ToolRegistry, current_session_id,
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

    missing = [name for name in CITED_SECTIONS
               if not [c for c in (sections[name].get("claims") or []) if c.get("of") or c.get("rows")]]
    if missing:
        return {"error": "missing_citations", "sections": missing,
                "detail": "every section except open_questions must rest on evidence from this "
                          "session: at least one claim pointing at a fact the desk put on the "
                          "table (of=f_…, or a table of them)"}

    led = await ledger.load(db, session_id)
    accepted: dict[str, dict] = {}
    for name in SECTIONS:
        verdict = claims.check(sections[name], led)
        if not verdict.ok:
            return {**verdict.as_refusal(), "section": name}
        accepted[name] = claims.accepted(sections[name], verdict, led)

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
        # V31 §8 B1: what each figure CLAIMS, beside where it came from. The
        # blocks say which fact filled a slot; the claims say what the sentence
        # asserted of it — a level, a change, a room to a tier — which is what
        # makes a brief's figure traceable to the node that produced it.
        claims_by_section={name: accepted[name]["claims"] for name in SECTIONS},
        citations=citations,
        block_citations={name: accepted[name]["citations"] for name in CITED_SECTIONS},
    ))
    await db.flush()
    return {"accepted": True, "brief_id": brief_id, "citations_validated": len(citations)}


# ── schema ────────────────────────────────────────────────────────────────────────

# V31: one section IS an answer. claims.ANSWER_SCHEMA is imported by identity,
# not copied — the brief and the reply are one grammar checked by one gate, which
# is the standing rule the V24 brief path was the last exception to. A relation
# added to the reply is a relation a brief may use, the same day.
#
# Closed, and it matters more here than anywhere else: _submit_brief takes
# **sections, so an unknown key is not a TypeError — it is dropped in silence,
# and a mistyped section name would produce a brief that looks complete and is
# missing a section.
_SECTION_SCHEMA = claims.ANSWER_SCHEMA

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
        name="search_web",
        display="Searching the web for “{query}”",
        description=(
            "Search the web about an issuer for what the filings cannot hold: news, guidance, "
            "an event after the last report — and anything the user asks you to look up. Each "
            "result is a src_ id on the table; a sentence resting on one names it in cites."
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
        # Its sources are the answer's evidence: src_ ids go on the table.,
    ))
    return reg


def register_research_tools(reg: ToolRegistry) -> ToolRegistry:
    register_search_tool(reg)
    reg.register(Tool(
        name="submit_brief",
        display="Resolving every figure in the brief against the table, then filing it",
        description=(
            "Submit the Issuer Risk Brief: six sections (financial_summary, key_changes, "
            "management_explanation, market_context, portfolio_implications, open_questions). "
            "Each section is an answer in the same grammar as a reply — CLAIMS and PROSE. Each "
            "claim states one relation over facts you were shown (f_… ids): level, tier, change, "
            "versus, ratio, rank, room, absent, quote, series, table. " + claims.PROSE_RULE + " "
            "Every section but open_questions must rest on at least one claim pointing at a fact "
            "from this session. A refusal names the section and the claim; fix that claim and "
            "resubmit."
        ),
        json_schema=SUBMIT_BRIEF_SCHEMA,
        fn=_submit_brief, tool_class=GATE,
    ))
    return reg
