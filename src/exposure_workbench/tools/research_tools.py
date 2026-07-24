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

    brief_id = new_brief_id()
    all_citations = sorted(set(citation_ids))
    db.add(IssuerBrief(
        id=brief_id, research_run_id=run.id, company_id=run.company_id,
        financial_summary=(blocks.get("financial_summary") or {}).get("text"),
        key_changes=(blocks.get("key_changes") or {}).get("text"),
        management_explanation=(blocks.get("management_explanation") or {}).get("text"),
        market_context=(blocks.get("market_context") or {}).get("text"),
        portfolio_implications=(blocks.get("portfolio_implications") or {}).get("text"),
        open_questions=(blocks.get("open_questions") or {}).get("text"),
        citations=all_citations,
        confidence_flags=blocks.get("confidence_flags") or {},
    ))
    await db.flush()
    return {"accepted": True, "brief_id": brief_id, "citations_validated": len(all_citations)}


# ── schema ────────────────────────────────────────────────────────────────────────

def _block_schema(cited: bool) -> dict:
    props: dict = {"text": {"type": "string"}}
    required = ["text"]
    if cited:
        props["citations"] = {"type": "array", "items": {"type": "string"},
                              "description": "evidence ids (fact_/calc_/chunk_/src_) supporting every claim"}
        required.append("citations")
    return {"type": "object", "properties": props, "required": required}


def register_research_tools(reg: ToolRegistry) -> ToolRegistry:
    reg.register(Tool(
        name="search_external_research",
        description="Search current external developments for an issuer (news, industry, regulatory). "
                    "reason states why the existing evidence is insufficient.",
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "query": {"type": "string"},
            "reason": {"type": "string", "description": "why this search is needed now"},
        }, "required": ["ticker", "query", "reason"]},
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
        }, "required": list(_ALL_BLOCKS)},
        fn=_submit_brief, tool_class=GATE,
    ))
    return reg
