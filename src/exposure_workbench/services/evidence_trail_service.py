"""Evidence trail (M7) + citation gate (M9 core).

The Evidence Trail is NOT an input pack assembled up front. It is derived from
what the session ACTUALLY touched: the union of evidence_refs across the
session's trace steps. So it answers "what did the agent really look at while
writing this brief", which is a stronger audit property than a hand-built list.

A citation is valid iff its id is in the session's trail (the agent retrieved it)
AND still resolves in the DB. Both are checked: trail membership stops the agent
citing something it never fetched; DB existence stops a dangling id.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import (
    AgentStep,
    CalcLedger,
    ExposureRun,
    FilingChunk,
    FinancialFact,
    Position,
    ResearchSource,
    RiskAlert,
)

# id prefix -> (table, column) for DB existence checks. Must stay in sync with the
# evidence resolver's prefixes: an id the agent can retrieve and drill through is
# an id it must be able to cite. alert_/run_ are portfolio-level evidence
# (get_portfolio_snapshot); without them a portfolio claim can't pass this gate.
_RESOLVERS = {
    "calc_": (CalcLedger, CalcLedger.id),
    "fact_": (FinancialFact, FinancialFact.id),
    "chunk_": (FilingChunk, FilingChunk.id),
    "src_": (ResearchSource, ResearchSource.id),
    "alert_": (RiskAlert, RiskAlert.id),
    "run_": (ExposureRun, ExposureRun.id),
    # A holding is evidence for exactly one thing — how many shares are held —
    # and the memory tool that reads the book back (C3) cannot support that
    # number without it. Under RLS this row is only visible on the user's own or
    # a public portfolio, which is the behaviour to want: citing a holding you
    # cannot see does not resolve.
    "pos_": (Position, Position.id),
}


async def collect_trail(db: AsyncSession, session_id: str) -> set[str]:
    """All evidence ids the session's completed tool calls surfaced."""
    rows = (
        await db.execute(
            select(AgentStep.evidence_refs).where(
                AgentStep.session_id == session_id, AgentStep.status == "completed"
            )
        )
    ).all()
    trail: set[str] = set()
    for (refs,) in rows:
        for ref in refs or []:
            rid = ref.get("id") if isinstance(ref, dict) else None
            if rid:
                trail.add(rid)
    return trail


async def _exists_in_db(db: AsyncSession, ref_id: str) -> bool:
    for prefix, (model, col) in _RESOLVERS.items():
        if ref_id.startswith(prefix):
            found = (await db.execute(select(col).where(col == ref_id))).scalar_one_or_none()
            return found is not None
    return False       # unknown prefix -> cannot be resolved -> invalid


async def validate_citations(
    db: AsyncSession, session_id: str, citation_ids: list[str]
) -> tuple[bool, list[dict]]:
    """Return (all_valid, problems). Each problem is {id, reason}."""
    trail = await collect_trail(db, session_id)
    problems: list[dict] = []
    for cid in citation_ids:
        if cid not in trail:
            problems.append({"id": cid, "reason": "not_in_evidence_trail"})
        elif not await _exists_in_db(db, cid):
            problems.append({"id": cid, "reason": "unresolved_in_db"})
    return (len(problems) == 0, problems)


async def materialize_pack(db: AsyncSession, session_id: str) -> list[dict]:
    """The trail as a stored refs list (evidence_packs.pack). A refs list, not a
    snapshot — the append-only stores keep the referenced rows immutable."""
    trail = await collect_trail(db, session_id)
    return [{"id": rid} for rid in sorted(trail)]
