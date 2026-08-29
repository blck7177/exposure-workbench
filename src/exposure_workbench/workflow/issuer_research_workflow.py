"""Issuer research workflow (M8, capability C) — three phases.

  1. readiness precheck  — ensure the issuer's data is ready (runs readiness if not;
                           fast when it already is)
  2. agent session       — the bounded research subagent explores + submit_brief
  3. finalize            — materialize the evidence trail, mark the run

The agent session is deliberately NOT idempotent — each run is a fresh judgment
and a fresh brief. skip flags remove capability from the session's face, never
an in-loop branch; since R4 the removal is stated once, to the mount, as a deny
list.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.errors import BriefNotSubmitted
from exposure_workbench.agents.research_session import run_research_session
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import Company, EvidencePack, FilingChunk, FinancialFact
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.services import company_service
from exposure_workbench.services import evidence_trail_service as trail
from exposure_workbench.services import research_run_service
from exposure_workbench.workflow.readiness_workflow import run_readiness
from exposure_workbench.workflow.step_context import step
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)


async def _is_ready(db: AsyncSession, company_id: str) -> bool:
    has_facts = (await db.execute(
        select(FinancialFact.id).where(FinancialFact.company_id == company_id).limit(1)
    )).scalar_one_or_none() is not None
    has_chunks = (await db.execute(
        select(FilingChunk.id).where(FilingChunk.company_id == company_id).limit(1)
    )).scalar_one_or_none() is not None
    return has_facts and has_chunks


async def run_issuer_research(
    db_factory,
    run_id: str,
    ticker: str,
    skip_external_research: bool = False,
    skip_market_refresh: bool = False,
) -> dict:
    ticker = ticker.upper()

    # ── phase 1: readiness precheck ────────────────────────────────────────────
    async with db_factory() as db:
        company = await company_service.require_investigable(db, ticker)
        company_id = company.id
        ready = await _is_ready(db, company_id)

    async with db_factory() as db:
        async with step(db, run_id, "readiness_precheck",
                        f"{'Data ready' if ready else 'Preparing data'} for {ticker}"):
            if not ready:
                await run_readiness(db, run_id, ticker, skip_market_refresh=skip_market_refresh)

    # ── phase 2: agent session ─────────────────────────────────────────────────
    async with db_factory() as db:
        # owner = the user who triggered this research (worker set the tenant ctx)
        agent_session = await sess.create_session(db, kind="research", owner_id=current_user_id())
        await research_run_service.update_status(db, run_id, "running", agent_session_id=agent_session.id)
        await db.commit()
        session_id = agent_session.id

    # skip flags remove capability rather than branch inside a tool. The face
    # belongs to the mount now, so the removal travels there in the token as a
    # deny list (R4/N7): what is served is FACE_RESEARCH minus deny, and a run
    # started with skip_external_research meets a face where the tool is
    # physically absent. Nothing is trimmed on this side as well — two places
    # narrowing one face is the error class the move deletes.
    deny = ("search_external_research",) if skip_external_research else ()

    async with db_factory() as db:
        async with step(db, run_id, "agent_session",
                        f"Research agent analysing {ticker}"):
            result = await run_research_session(db_factory, session_id, ticker, deny=deny)
            if not result["submitted"]:
                # A named class, not a bare RuntimeError: this is the agent
                # running out of room, not a defect, and the two get different
                # sentences (V13-S2).
                raise BriefNotSubmitted(
                    f"research agent did not submit a brief within budget "
                    f"(turns={result['turns_used']})"
                )

    # ── phase 3: finalize (materialize evidence trail) ─────────────────────────
    async with db_factory() as db:
        async with step(db, run_id, "finalize", "Materializing evidence trail"):
            pack = await trail.materialize_pack(db, session_id)
            db.add(EvidencePack(id=new_id("epack_"), research_run_id=run_id,
                                session_id=session_id, pack=pack))
            await db.flush()
        await research_run_service.update_status(db, run_id, "completed")
        await db.commit()

    return {"run_id": run_id, "brief_id": result["brief_id"], "evidence_count": len(pack)}
