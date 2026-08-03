"""Research-face tools (M6/M9) — external search + the submit_brief gate.

Registered onto the base read registry to form FACE_RESEARCH. submit_brief is the
session's exit: it enforces, at generation time, that every cited id is in the
session's evidence trail and resolves in the DB. A rejected submission comes back
as a structured error the agent can fix within its retry budget — no partial /
degraded brief is ever persisted.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import Company, IssuerBrief, ResearchRun
from exposure_workbench.services import evidence_trail_service as trail
from exposure_workbench.services import numeric_verification as numeric
from exposure_workbench.services import research_search_service as rss
from exposure_workbench.tools.registry import DELEGATION, GATE, Tool, ToolRegistry, current_session_id
from exposure_workbench.utils.ids import new_brief_id

logger = logging.getLogger(__name__)

# Five evidence-bearing blocks + open_questions (the one block exempt from
# citations, because a question is not a factual claim).
_CITED_BLOCKS = ("financial_summary", "key_changes", "management_explanation",
                 "market_context", "portfolio_implications")
_ALL_BLOCKS = _CITED_BLOCKS + ("open_questions",)


async def _run_for_session(db: AsyncSession, session_id: str) -> ResearchRun | None:
    return (
        await db.execute(select(ResearchRun).where(ResearchRun.agent_session_id == session_id))
    ).scalar_one_or_none()


# ── external research (M6) ───────────────────────────────────────────────────────

async def _search_external_research(db: AsyncSession, ticker: str, query: str, reason: str) -> dict:
    """Delegation tool: reason is REQUIRED by schema — the judgment is logged.
    Persists results and returns citable src_ ids."""
    tk = ticker.upper()
    company = (await db.execute(select(Company).where(Company.ticker == tk))).scalar_one_or_none()
    if company is None:
        return {"error": "company_not_found", "ticker": tk}
    run = await _run_for_session(db, current_session_id())
    try:
        sources = await rss.search(db, company.id, query, research_run_id=run.id if run else None)
    except rss.ResearchProviderUnavailable as e:
        return {"error": "provider_unavailable", "detail": str(e)}
    return {"ticker": tk, "query": query, "reason": reason, "sources": sources}


# ── submit_brief gate (M9) ────────────────────────────────────────────────────────

def _collect_citation_ids(blocks: dict) -> list[str]:
    ids: list[str] = []
    for name in _CITED_BLOCKS:
        block = blocks.get(name) or {}
        for cid in (block.get("citations") or []):
            if isinstance(cid, str):
                ids.append(cid)
    return ids


async def _unverified_blocks(db: AsyncSession, blocks: dict, citation_ids: list[str]) -> dict[str, list[dict]]:
    """Which blocks state a figure their evidence does not hold.

    Each cited block is checked against THAT block's own citations. Pooling them
    would let a figure in market_context be justified by an id cited only under
    financial_summary — which is how a brief ends up internally consistent and
    individually unsupported.

    open_questions is the exception, and it used to be the omission: it carries
    no citations by design, because it is where the analyst writes down what is
    still unknown, and the loop over the cited blocks therefore never saw it. A
    brief could ask "will capex stay above $23B?" with $23B appearing in none of
    its evidence, and that number is rendered to the reader exactly like every
    other one. It is verified against the UNION of everything the brief cites —
    the honest denominator for a block that cannot name its own support. A
    question built on the brief's own figures passes; one built on a figure from
    nowhere is an unsupported claim with a question mark on the end.
    """
    unverified: dict[str, list[dict]] = {}
    for name in _ALL_BLOCKS:
        block = blocks.get(name) or {}
        stated = numeric.extract_numbers(block.get("text") or "")
        if not stated:
            continue
        if name == "open_questions":
            ids = list(citation_ids)
        else:
            ids = [c for c in (block.get("citations") or []) if isinstance(c, str)]
        values, quoted = await numeric.resolve_cited_values(db, ids)
        bad = numeric.verify(stated, values, quoted)
        if bad:
            unverified[name] = bad
    return unverified


async def _submit_brief(db: AsyncSession, **blocks) -> dict:
    """Gate: validate citations against the evidence trail; persist only if clean."""
    session_id = current_session_id()
    run = await _run_for_session(db, session_id)
    if run is None:
        return {"error": "no_research_run", "detail": "submit_brief called outside a research run"}

    # structural check: every cited block must carry a non-empty citations list
    missing_cites = [b for b in _CITED_BLOCKS
                     if not ((blocks.get(b) or {}).get("citations"))]
    if missing_cites:
        return {"error": "missing_citations", "blocks": missing_cites,
                "detail": "every block except open_questions must cite evidence"}

    citation_ids = _collect_citation_ids(blocks)
    ok, problems = await trail.validate_citations(db, session_id, citation_ids)
    if not ok:
        return {"error": "invalid_citations", "problems": problems,
                "detail": "cited ids must be in this session's evidence trail and resolve in the DB"}

    unverified = await _unverified_blocks(db, blocks, citation_ids)
    if unverified:
        return {"error": "unverified_numbers", "blocks": unverified,
                "detail": "each figure must match a value held by the evidence cited in the "
                          "SAME block; re-cite the id that carries it, or drop the figure. "
                          "A figure in open_questions is checked against everything the brief "
                          "cites — ask the question without inventing a number for it"}

    brief_id = new_brief_id()
    all_citations = sorted(set(citation_ids))
    db.add(IssuerBrief(
        id=brief_id, research_run_id=run.id, company_id=run.company_id,
        owner_id=run.owner_id,   # V2-C: brief belongs to who triggered the research (RLS WITH CHECK)
        financial_summary=(blocks.get("financial_summary") or {}).get("text"),
        key_changes=(blocks.get("key_changes") or {}).get("text"),
        management_explanation=(blocks.get("management_explanation") or {}).get("text"),
        market_context=(blocks.get("market_context") or {}).get("text"),
        portfolio_implications=(blocks.get("portfolio_implications") or {}).get("text"),
        open_questions=(blocks.get("open_questions") or {}).get("text"),
        citations=all_citations,
        block_citations={n: [c for c in ((blocks.get(n) or {}).get("citations") or [])
                             if isinstance(c, str)] for n in _CITED_BLOCKS},
        confidence_flags=blocks.get("confidence_flags") or {},
    ))
    await db.flush()
    return {"accepted": True, "brief_id": brief_id, "citations_validated": len(all_citations)}


# ── schema ────────────────────────────────────────────────────────────────────────

def _block_schema(cited: bool) -> dict:
    props: dict = {"text": {"type": "string", "minLength": 1}}
    required = ["text"]
    if cited:
        props["citations"] = {"type": "array", "items": {"type": "string"}, "minItems": 1,
                              "description": "evidence ids (fact_/calc_/chunk_/src_) supporting every claim"}
        required.append("citations")
    # Closed, and it matters more here than anywhere else: _submit_brief takes
    # **blocks, so an unknown key is not a TypeError — it is dropped in silence.
    # `citations` on open_questions was accepted and then ignored, because the
    # gate collects citations from the five cited blocks only. Ids that are never
    # trail-checked, never stored and never shown, in the one tool whose whole
    # job is citation discipline.
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def register_research_tools(reg: ToolRegistry) -> ToolRegistry:
    reg.register(Tool(
        name="search_external_research",
        description="Search current external developments for an issuer (news, industry, regulatory). "
                    "reason states why the existing evidence is insufficient.",
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "query": {"type": "string"},
            "reason": {"type": "string", "description": "why this search is needed now"},
        }, "required": ["ticker", "query", "reason"], "additionalProperties": False},
        fn=_search_external_research, tool_class=DELEGATION, budget_key="external_search",
    ))
    reg.register(Tool(
        name="submit_brief",
        description="Submit the Issuer Risk Brief. Five blocks require citations; open_questions does not. "
                    "Every cited id must come from a tool result you actually called this session.",
        json_schema={"type": "object", "properties": {
            "financial_summary": _block_schema(True),
            "key_changes": _block_schema(True),
            "management_explanation": _block_schema(True),
            "market_context": _block_schema(True),
            "portfolio_implications": _block_schema(True),
            "open_questions": _block_schema(False),
            "confidence_flags": {"type": "object"},
        }, "required": list(_ALL_BLOCKS), "additionalProperties": False},
        fn=_submit_brief, tool_class=GATE,
    ))
    return reg
