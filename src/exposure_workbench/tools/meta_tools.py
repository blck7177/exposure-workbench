"""Meta-agent-face tools (M10) — delegation + the respond gate.

Delegation tools only ENQUEUE (non-blocking): they return a run/task id
immediately, never wait for completion, so the meta-agent stays responsive and
the heavy work runs on the worker. respond is the meta-agent's exit: an answer
is blocks (services/answer_blocks.py), and every pointer in it is resolved
against the session's table by the one resolver (services/resolver.py) —
submit_brief resolves through the same function.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import Company
from exposure_workbench.services import company_service, research_run_service, task_service, usage_service
from exposure_workbench.services import answer_blocks as ab
from exposure_workbench.services import resolver
from exposure_workbench.tools.registry import (
    DELEGATION, GATE, NOT_EVIDENCE, Evidence, Tool, ToolRegistry, current_session_id,
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


# ── respond gate ────────────────────────────────────────────────────────────────

async def _respond_blocks(db: AsyncSession, blocks: list) -> dict:
    """V15-S3/S4. The exit: every pointer in the answer lands on the table, or the
    answer comes back with the block and the reason.

    Nothing here reads a figure out of a sentence — a sentence may not contain
    one — and nothing here guesses which figure a value meant, because a slot
    carries a name. The resolver is shared with submit_brief; this function only
    shapes its verdict into the exit's reply.
    """
    verdict = await resolver.resolve(db, current_session_id(), blocks)
    if not verdict.ok:
        return verdict.as_refusal()
    return {"responded": True, "format": "blocks", **resolver.accepted(blocks, verdict)}


# ── the exit's grammar, as schema (Law B) ──────────────────────────────────────
# Every claim type has one shape; a block outside these six is refused by the
# argument validator before the gate runs, with every problem named.

_SLOT = {"type": "object",
         "description": "one figure: the id and the NAME the table gave it, e.g. "
                        "{ref: 'run_…', name: 'issuer_exposures.MSFT.weight'}",
         "properties": {"ref": {"type": "string"}, "name": {"type": "string"}},
         "required": ["ref", "name"], "additionalProperties": False}
_RUN = {"anyOf": [{"type": "string"}, _SLOT]}
_CITES = {"type": "array", "items": {"type": "string"},
          "description": "chunk_/src_ ids the prose of this block rests on"}
_TEXT = {"type": "string", "minLength": 1, "description": "the claim, with no figures in it"}


def _block(kind: str, props: dict, required: list[str]) -> dict:
    return {"type": "object",
            "properties": {"type": {"type": "string", "enum": [kind]}, **props},
            "required": ["type", *required], "additionalProperties": False}


BLOCK_SCHEMAS = [
    _block("paragraph", {"runs": {"type": "array", "minItems": 1, "items": _RUN,
                                  "description": "strings and slots, in reading order"},
                         "cites": _CITES}, ["runs"]),
    _block("metric_table", {"title": {"type": "string"},
                            "columns": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                            "rows": {"type": "array", "minItems": 1,
                                     "items": {"type": "array", "items": _RUN}},
                            "cites": _CITES}, ["columns", "rows"]),
    _block("chart", {"kind": {"type": "string", "enum": list(ab.CHART_KINDS)},
                     "title": {"type": "string"},
                     "series_ref": {"type": "string", "description": "the calc id of a series you read"}},
           ["kind", "series_ref"]),
    _block("trend", {"text": _TEXT,
                     "series_ref": {"type": "string", "description": "the calc id of the series the claim was read from"}},
           ["text", "series_ref"]),
    _block("absence", {"text": _TEXT,
                       "absence_ref": {"type": "string", "description": "the calc id of the recorded refusal"}},
           ["text", "absence_ref"]),
    _block("action", {"text": _TEXT,
                      "task_ref": {"type": "string", "description": "the task/run id a delegation tool returned this turn"}},
           ["text", "task_ref"]),
]

RESPOND_SCHEMA = {"type": "object", "properties": {
    "blocks": {"type": "array", "minItems": 1, "description": "the answer, in reading order",
               "items": {"oneOf": BLOCK_SCHEMAS}},
}, "required": ["blocks"], "additionalProperties": False}


# ── registration ────────────────────────────────────────────────────────────────

def register_meta_tools(reg: ToolRegistry) -> ToolRegistry:
    reg.register(Tool(
        name="ensure_company_ready",
        display="Preparing {ticker}'s filings and prices",
        description=(
            "Enqueue a data-readiness pass for an issuer (ingest/index/price). Returns "
            "immediately. Works for ANY listed SEC filer, not only issuers already on "
            "the desk: a ticker with no filings or facts yet is prepared by this call, "
            "and becomes readable a couple of minutes later. Refuses a symbol that is "
            "not listed, an ETF, and a listing with no SEC CIK, each by name."
        ),
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "reason": {"type": "string", "description": "why readiness is needed now"},
        }, "required": ["ticker", "reason"], "additionalProperties": False},
        fn=_ensure_company_ready, tool_class=DELEGATION,
        evidence=Evidence(tasks_from=("task_id",)),
    ))
    reg.register(Tool(
        name="start_issuer_research",
        display="Starting a research run on {ticker}",
        description="Enqueue a full issuer research run (produces an Issuer Risk Brief). Returns a run id immediately.",
        json_schema={"type": "object", "properties": {
            "ticker": {"type": "string"},
            "reason": {"type": "string"},
        }, "required": ["ticker", "reason"], "additionalProperties": False},
        fn=_start_issuer_research, tool_class=DELEGATION,
        evidence=Evidence(tasks_from=("run_id",)),
    ))
    reg.register(Tool(
        name="start_exposure_run",
        display="Starting an exposure run",
        description="Enqueue a portfolio exposure run. Returns a run id immediately.",
        json_schema={"type": "object", "properties": {
            "portfolio_id": {"type": "string"},
            # Nullable because the description tells the model to omit it, and
            # a model that has decided not to use an optional argument says so
            # with null about as often as by leaving it out.
            "as_of_date": {"type": ["string", "null"], "description":
                "YYYY-MM-DD. Omit unless the user asked for a specific date — "
                "the server reports on the last completed session by default."},
            "reason": {"type": "string"},
        }, "required": ["portfolio_id", "reason"], "additionalProperties": False},
        fn=_start_exposure_run, tool_class=DELEGATION,
        evidence=Evidence(tasks_from=("run_id",)),
    ))
    reg.register(Tool(
        name="respond",
        display="Resolving every figure against the table, then answering",
        description=(
            "Reply to the user. An answer is a list of BLOCKS; every figure is a SLOT "
            "{ref, name} using a name from the `table` a tool result carried, and the "
            "reader is shown the table's own value — you never write a number. Blocks: "
            "`paragraph` (runs: strings and slots in reading order; `cites`: the chunk_/src_ "
            "ids its prose rests on), `metric_table` (columns + rows of strings/slots — use "
            "it whenever you compare or rank), `chart` (kind + series_ref), `trend` (text + "
            "series_ref: a claim that something rose or fell rests on the series it was read "
            "from), `absence` (text + absence_ref: a claim that something was not reported "
            "rests on the row the refused read minted), `action` (text + task_ref: work you "
            "started this turn, by its id). Text carries no digits except dates. A reply "
            "that states nothing factual needs no slots and no cites."
        ),
        json_schema=RESPOND_SCHEMA,
        fn=_respond_blocks, tool_class=GATE,
        evidence=NOT_EVIDENCE,  # a verdict is not evidence — a refusal's echoed ids must not become citable
    ))
    return reg
