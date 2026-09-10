"""Meta-agent-face tools (M10) — delegation + the respond gate.

Delegation tools only ENQUEUE (non-blocking): they return a run/task id
immediately, never wait for completion, so the meta-agent stays responsive and
the heavy work runs on the worker. respond is the meta-agent's exit: an answer
is blocks (services/answer.py), and every pointer in it is checked against the
session's ledger by the one gate (services/gate.py) — submit_brief goes
through the same function.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import Company
from exposure_workbench.services import company_service, research_run_service, task_service, usage_service
from exposure_workbench.services import answer, claims, gate, ledger
from exposure_workbench.tools.registry import (
    DELEGATION, GATE, Tool, ToolRegistry, current_session_id,
)

logger = logging.getLogger(__name__)


# ── delegation (enqueue-only, non-blocking) ─────────────────────────────────────

async def _ensure_company_ready(db: AsyncSession, ticker: str, reason: str) -> dict:
    tk = ticker.upper()
    # The one tool that may bring a new issuer onto the desk (V17). `admit`
    # writes the row from the listed universe; everything expensive happens on
    # the worker, so this stays the immediate, non-blocking return it was.
    try:
        await company_service.admit(db, tk)
    except company_service.CompanyNotFound:
        return {"error": "not_listed", "ticker": tk,
                "detail": f"{tk} is not in the listed universe this desk holds, so there "
                          f"is no issuer to prepare. Check the symbol."}
    except company_service.NotInvestigable as e:
        return {"error": "not_investigable", "ticker": tk, "detail": e.reason}
    except company_service.NotAnSecFiler:
        return {"error": "not_an_sec_filer", "ticker": tk,
                "detail": f"{tk} is listed but files with no SEC CIK, so this desk cannot "
                          f"read statements for it. Its price history is still available."}
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
        company = await company_service.admit(db, tk)
    except company_service.CompanyNotFound:
        return {"error": "not_listed", "ticker": tk,
                "detail": f"{tk} is not in the listed universe this desk holds."}
    except company_service.NotInvestigable as e:
        return {"error": "not_investigable", "ticker": tk, "detail": e.reason}
    except company_service.NotAnSecFiler:
        return {"error": "not_an_sec_filer", "ticker": tk,
                "detail": f"{tk} is listed but files with no SEC CIK; there are no "
                          f"statements to research."}
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


# ── respond gate (V24) ──────────────────────────────────────────────────────────

async def _respond_claims(db: AsyncSession, claims: list, prose: list) -> dict:
    """The exit (V30): claims typed against the facts they point at, prose whose
    digits account to the ledger (services/claims.py). The ledger is read as
    recorded; nothing here rebuilds anything."""
    led = await ledger.load(db, current_session_id())
    from exposure_workbench.services import claims as claims_mod
    answer_ = {"claims": claims, "prose": prose}
    verdict = claims_mod.check(answer_, led, question=await _question(db, current_session_id()))
    if not verdict.ok:
        return verdict.as_refusal()
    return {"responded": True, "format": "blocks", **claims_mod.accepted(answer_, verdict, led)}


async def _question(db: AsyncSession, session_id: str) -> str | None:
    """The user's message this turn answers — the latest user row of the session."""
    from exposure_workbench.db.models import AgentMessage
    row = (await db.execute(
        select(AgentMessage.content).where(AgentMessage.session_id == session_id, AgentMessage.role == "user")
        .order_by(AgentMessage.created_at.desc()).limit(1))).first()
    return row[0] if row else None


# The exit's grammar, as schema (Law B): services/answer.py owns the block
# shapes; the brief's sections reuse the same list.
BLOCK_SCHEMAS = answer.BLOCK_SCHEMAS
RESPOND_SCHEMA = claims.ANSWER_SCHEMA


# ── registration ────────────────────────────────────────────────────────────────

_START_KINDS = ("readiness", "research", "exposure_run")


async def _start(db: AsyncSession, kind: str, subject: str, reason: str,
                 as_of_date: str | None = None) -> dict:
    """One delegation tool (V23): readiness for an issuer, a research run for an
    issuer, an exposure run for a portfolio. Each returns an id immediately and
    the work runs in the background; read_book(id, ['state']) follows it."""
    if kind == "readiness":
        return await _ensure_company_ready(db, subject, reason)
    if kind == "research":
        return await _start_issuer_research(db, subject, reason)
    if kind == "exposure_run":
        return await _start_exposure_run(db, subject, reason, as_of_date)
    return {"error": "unknown_kind", "kind": kind, "known": list(_START_KINDS)}


def register_meta_tools(reg: ToolRegistry) -> ToolRegistry:
    reg.register(Tool(
        name="start",
        display="Starting {kind} for {subject}",
        description=(
            "Start background work and return its id at once: readiness (ingest, index and price an "
            "issuer — any listed SEC filer, prepared in a couple of minutes), research (an Issuer Risk "
            "Brief), exposure_run (a portfolio run on the book AS IT IS, on the last completed session "
            "unless as_of_date — it does not apply a trade; a hypothetical sale or purchase is "
            "a sell / buy node in run(program) over the run id, which answers at once). "
            "Never blocks; tell the user it is being prepared. A started run's figures are readable "
            "once its status is completed; read_book(task_…, names=['state']) reports its progress."
        ),
        json_schema={"type": "object", "properties": {
            "kind": {"type": "string", "enum": list(_START_KINDS)},
            "subject": {"type": "string", "description": "a ticker (readiness, research) or a port_… id (exposure_run)"},
            "reason": {"type": "string", "description": "why this work is needed now"},
            "as_of_date": {"type": ["string", "null"], "description": "YYYY-MM-DD; exposure_run only; omit unless asked"},
        }, "required": ["kind", "subject", "reason"], "additionalProperties": False},
        fn=_start, tool_class=DELEGATION,
    ))
    reg.register(Tool(
        name="respond",
        display="Checking every claim against its facts, then answering",
        description=(
            "Reply to the user. An answer is CLAIMS and PROSE. Each claim states one relation over facts you were "
            "shown (f_… ids): level (a reading), tier (a warning/breach/limit level, said as one), change (of = later reading, against = earlier; or a yoy/qoq/subtract "
            "node, or one series), versus (one measure on two subjects, of against against), ratio (a divided or ratio-method figure), rank (an entry of a rank/top node), room (a check's "
            "current_value against its warning or breach tier), absent (an absence fact), quote (a passage + the "
            "verbatim span), series (a chart), table (rows of scalar facts). " + claims.PROSE_RULE + " "
            "A claim whose relation its facts do not fit is refused with the reason; a number the ledger cannot account for is refused."
        ),
        json_schema=RESPOND_SCHEMA,
        fn=_respond_claims, tool_class=GATE,
    ))
    return reg
