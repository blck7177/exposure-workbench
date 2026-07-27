"""Meta-agent-face tools (M10) — delegation + the respond gate.

Delegation tools only ENQUEUE (non-blocking): they return a run/task id
immediately, never wait for completion, so the meta-agent stays responsive and
the heavy work runs on the worker. respond is the meta-agent's exit, gated by the
same citation check as submit_brief (lighter: chat replies may cite nothing, but
whatever they cite must be real).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import Company
from exposure_workbench.services import company_service, research_run_service, task_service, usage_service
from exposure_workbench.services import evidence_trail_service as trail
from exposure_workbench.tools.registry import DELEGATION, GATE, Tool, ToolRegistry, current_session_id

logger = logging.getLogger(__name__)


# ── delegation (enqueue-only, non-blocking) ─────────────────────────────────────

async def _ensure_company_ready(db: AsyncSession, ticker: str, reason: str) -> dict:
    tk = ticker.upper()
    try:
        await company_service.require_investigable(db, tk)
    except company_service.CompanyNotFound:
        return {"error": "company_not_found", "ticker": tk}
    except company_service.NotInvestigable:
        return {"error": "not_investigable", "ticker": tk}
    try:
        task = await task_service.create_task(db, task_type="company_readiness", payload={"ticker": tk},
                                              owner_user_id=current_user_id())
    except usage_service.QuotaExceeded as e:
        return e.as_dict() | {"ticker": tk}
    task.payload = {**task.payload, "run_id": task.id}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.flush()
    return {"enqueued": True, "task_id": task.id, "kind": "company_readiness", "ticker": tk, "reason": reason}


async def _start_issuer_research(db: AsyncSession, ticker: str, reason: str) -> dict:
    tk = ticker.upper()
    try:
        company = await company_service.require_investigable(db, tk)
    except company_service.CompanyNotFound:
        return {"error": "company_not_found", "ticker": tk}
    except company_service.NotInvestigable:
        return {"error": "not_investigable", "ticker": tk}
    # Precheck before enqueuing: create_run raises ActiveRunExists only after the
    # task exists, and on this path the tool RETURNS normally, so meta_agent
    # commits — leaving an orphan task the worker is guaranteed to fail, and a
    # quota unit spent on a request that never had a chance.
    active = await research_run_service.get_active_run(db, company.id)
    if active is not None:
        return {"error": "active_run_exists", "run_id": active.id, "ticker": tk}
    try:
        task = await task_service.create_task(db, task_type="issuer_research", payload={"ticker": tk},
                                              owner_user_id=current_user_id())
    except usage_service.QuotaExceeded as e:
        return e.as_dict() | {"ticker": tk}
    try:
        run = await research_run_service.create_run(
            db, company.id, None, triggered_by=f"agent:{current_session_id()}", task_id=task.id,
            owner_id=current_user_id(),
        )
    except research_run_service.ActiveRunExists as e:
        return {"error": "active_run_exists", "run_id": e.run_id, "ticker": tk}
    task.payload = {**task.payload, "run_id": run.id}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.flush()
    return {"enqueued": True, "run_id": run.id, "kind": "issuer_research", "ticker": tk, "reason": reason}


async def _start_exposure_run(db: AsyncSession, portfolio_id: str, as_of_date: str, reason: str) -> dict:
    from exposure_workbench.services import exposure_run_service, portfolio_service
    # only run portfolios the user owns — the public demo is read-only (matches the
    # REST route + the RLS WITH CHECK; a clean error beats an RLS-aborted transaction).
    pf = await portfolio_service.get_portfolio(db, portfolio_id)
    if pf is None or pf.owner_id != current_user_id():
        return {"error": "not_your_portfolio", "portfolio_id": portfolio_id,
                "detail": "you can only run a portfolio you own; clone the demo to run it"}
    try:
        task = await task_service.create_task(
            db, task_type="exposure_update",
            payload={"portfolio_id": portfolio_id, "as_of_date": as_of_date},
            owner_user_id=current_user_id(),
        )
    except usage_service.QuotaExceeded as e:
        return e.as_dict() | {"portfolio_id": portfolio_id}
    run = await exposure_run_service.create_run(
        db, portfolio_id=portfolio_id, as_of_date=__import__("datetime").date.fromisoformat(as_of_date),
        task_id=task.id, triggered_by=f"agent:{current_session_id()}",
    )
    task.payload = {**task.payload, "run_id": run.id}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.flush()
    return {"enqueued": True, "run_id": run.id, "kind": "exposure_update", "reason": reason}


# ── respond gate ────────────────────────────────────────────────────────────────

async def _respond(db: AsyncSession, text: str, citations: list[str] | None = None) -> dict:
    """Meta-agent exit. citations=[] is fine (non-factual replies); but any cited
    id must be in the session's evidence trail and resolve in the DB."""
    citation_ids = [c for c in (citations or []) if isinstance(c, str)]
    if citation_ids:
        ok, problems = await trail.validate_citations(db, current_session_id(), citation_ids)
        if not ok:
            return {"error": "invalid_citations", "problems": problems,
                    "detail": "cited ids must come from tool results you called this session"}
    return {"responded": True, "text": text, "citations": citation_ids}


# ── registration ────────────────────────────────────────────────────────────────

def register_meta_tools(reg: ToolRegistry) -> ToolRegistry:
    reg.register(Tool(
        name="ensure_company_ready",
        description="Enqueue a data-readiness pass for an issuer (ingest/index/price). Returns immediately.",
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "reason": {"type": "string", "description": "why readiness is needed now"},
        }, "required": ["ticker", "reason"]},
        fn=_ensure_company_ready, tool_class=DELEGATION,
    ))
    reg.register(Tool(
        name="start_issuer_research",
        description="Enqueue a full issuer research run (produces an Issuer Risk Brief). Returns a run id immediately.",
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "reason": {"type": "string"},
        }, "required": ["ticker", "reason"]},
        fn=_start_issuer_research, tool_class=DELEGATION,
    ))
    reg.register(Tool(
        name="start_exposure_run",
        description="Enqueue a portfolio exposure run. Returns a run id immediately.",
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
            "as_of_date": {"type": "string", "description": "YYYY-MM-DD"},
            "reason": {"type": "string"},
        }, "required": ["portfolio_id", "as_of_date", "reason"]},
        fn=_start_exposure_run, tool_class=DELEGATION,
    ))
    reg.register(Tool(
        name="respond",
        description="Reply to the user. Provide citations (evidence ids) for any factual claim; "
                    "an acknowledgement needs none, but whatever you cite must be real.",
        json_schema={"type": "object", "properties": {
            "text": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}},
        }, "required": ["text"]},
        fn=_respond, tool_class=GATE,
    ))
    return reg
