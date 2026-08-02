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
from exposure_workbench.services import numeric_verification as numeric
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
        # Roll back before returning. charge() debits the user pool and then the
        # global backstop in one transaction; when the backstop refuses, this
        # tool RETURNS rather than raising, and meta_agent commits the session
        # straight afterwards — making the user's debit permanent for an action
        # that never ran. The session holds only this tool call, so discarding it
        # is exactly right.
        await db.rollback()
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
        # Roll back before returning. charge() debits the user pool and then the
        # global backstop in one transaction; when the backstop refuses, this
        # tool RETURNS rather than raising, and meta_agent commits the session
        # straight afterwards — making the user's debit permanent for an action
        # that never ran. The session holds only this tool call, so discarding it
        # is exactly right.
        await db.rollback()
        return e.as_dict() | {"ticker": tk}
    try:
        run = await research_run_service.create_run(
            db, company.id, None, triggered_by=f"agent:{current_session_id()}", task_id=task.id,
            owner_id=current_user_id(),
        )
    except research_run_service.ActiveRunExists as e:
        # Lost the race between the precheck above and create_run's own re-read.
        # Roll back: create_task has already charged a research unit and inserted
        # a tasks row, and this tool RETURNS rather than raises, so meta_agent
        # would commit both — costing the user one of three daily runs and
        # leaving an orphan task the worker is guaranteed to fail.
        await db.rollback()
        return {"error": "active_run_exists", "run_id": e.run_id, "ticker": tk}
    task.payload = {**task.payload, "run_id": run.id}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.flush()
    return {"enqueued": True, "run_id": run.id, "kind": "issuer_research", "ticker": tk, "reason": reason}


async def _start_exposure_run(db: AsyncSession, portfolio_id: str, reason: str,
                              as_of_date: str | None = None) -> dict:
    from exposure_workbench.services import exposure_run_service, portfolio_service
    # Only run portfolios the user owns — the public demo is read-only.
    # semantic, not security: the RLS WITH CHECK is the real stop; this just gives
    # the agent a structured error instead of an aborted transaction.
    pf = await portfolio_service.get_portfolio(db, portfolio_id)
    if pf is None or pf.owner_id != current_user_id():
        return {"error": "not_your_portfolio", "portfolio_id": portfolio_id,
                "detail": "you can only run a portfolio you own; clone the demo to run it"}
    # The reporting date is a server fact, not something for the model to guess:
    # an LLM-supplied date reached the workflow completely unchecked, and "today"
    # before the close compares the newest bar against itself.
    from exposure_workbench.services import market_data_service
    if as_of_date:
        try:
            as_of = __import__("datetime").date.fromisoformat(as_of_date)
        except ValueError:
            # Typed, like every other bad-argument case here. Flattened to
            # tool_error the model cannot tell "you formatted the argument wrong,
            # drop it" from "the server broke".
            return {"error": "invalid_as_of_date", "as_of_date": as_of_date,
                    "detail": "expected YYYY-MM-DD, or omit it for the last completed session"}
    else:
        as_of = await market_data_service.latest_session_date(db)
        if as_of is None:
            return {"error": "no_price_data", "detail": "no market prices are loaded yet"}

    try:
        task = await task_service.create_task(
            db, task_type="exposure_update",
            payload={"portfolio_id": portfolio_id, "as_of_date": as_of.isoformat()},
            owner_user_id=current_user_id(),
        )
    except usage_service.QuotaExceeded as e:
        await db.rollback()   # see _ensure_company_ready: never commit a half charge
        return e.as_dict() | {"portfolio_id": portfolio_id}
    run = await exposure_run_service.create_run(
        db, portfolio_id=portfolio_id, as_of_date=as_of,
        task_id=task.id, triggered_by=f"agent:{current_session_id()}",
    )
    task.payload = {**task.payload, "run_id": run.id}
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(task, "payload")
    await db.flush()
    return {"enqueued": True, "run_id": run.id, "kind": "exposure_update", "reason": reason}


# ── respond gate ────────────────────────────────────────────────────────────────

async def _respond(db: AsyncSession, text: str, citations: list[str] | None = None) -> dict:
    """Meta-agent exit. A reply that states no number may cite nothing — a
    greeting or a clarifying question is not a factual claim. A reply that states
    a number must cite, and any cited id must be in the session's evidence trail
    and resolve in the DB.

    The empty-citations branch never touches `db`, which is what makes the
    refusal testable without one.
    """
    citation_ids = [c for c in (citations or []) if isinstance(c, str)]
    if citation_ids:
        ok, problems = await trail.validate_citations(db, current_session_id(), citation_ids)
        if not ok:
            return {"error": "invalid_citations", "problems": problems,
                    "detail": "cited ids must come from tool results you called this session"}
        # The ids are real; now the numbers standing next to them have to be.
        stated = numeric.extract_numbers(text)
        if stated:
            values, quoted = await numeric.resolve_cited_values(db, citation_ids)
            bad = numeric.verify(stated, values, quoted)
            if bad:
                # Three options, and the third one matters. Observed live: asked
                # to summarise a pre-V3 brief, the agent hit this three times
                # running and then gave up with an apology — because the brief
                # itself states figures its own citations do not support, and
                # neither re-citing nor recomputing can conjure evidence that was
                # never there. Omitting the figure and answering with the rest is
                # a legitimate, honest move, and the model has no way to know
                # that unless the refusal says so.
                return {"error": "unverified_numbers", "problems": bad,
                        "detail": "each number must match a value held by the evidence you "
                                  "cited. Re-cite the id that actually carries it, compute it "
                                  "with a tool so it has one, or leave that figure out and "
                                  "answer with what you can support — a partial answer that "
                                  "holds up is worth more than a complete one that does not"}
    else:
        # Zero citations used to skip validation entirely, so a reply made
        # entirely of numbers passed the gate untouched — the one shape the gate
        # exists to stop. Enforced here rather than by making `citations` a
        # required schema field, because that would also block the number-free
        # replies this branch deliberately allows.
        stated = numeric.extract_numbers(text)
        if stated:
            return {"error": "citations_required",
                    "numbers_found": numeric.raw_forms(stated),
                    "detail": "a reply that states numbers must cite the evidence ids "
                              "they came from; call a tool to get them first"}
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
            "as_of_date": {"type": "string", "description":
                "YYYY-MM-DD. Omit unless the user asked for a specific date — "
                "the server reports on the last completed session by default."},
            "reason": {"type": "string"},
        }, "required": ["portfolio_id", "reason"]},
        fn=_start_exposure_run, tool_class=DELEGATION,
    ))
    reg.register(Tool(
        name="respond",
        description="Reply to the user. Any reply that states a number must cite the evidence "
                    "ids that number came from; a reply with no numbers (a greeting, a "
                    "clarifying question) may cite nothing. Whatever you cite must be real.",
        json_schema={"type": "object", "properties": {
            "text": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}},
        }, "required": ["text"]},
        fn=_respond, tool_class=GATE,
    ))
    return reg
