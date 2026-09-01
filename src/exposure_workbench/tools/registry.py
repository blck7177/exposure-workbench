"""ToolRegistry + wrapper (M10) — the single enforcement point.

A tool is a five-tuple: {name, json_schema, fn, tool_class, budget_key}.
The wrapper does four things automatically around every LLM-driven call:

  1. validate the arguments against the tool's own schema — before any spend
  2. reserve budget (agent_session_service) — before the tool runs
  3. run the fn, catching failures as structured results (never crashes the loop)
  4. put what the tool DECLARED on the table (services/table.py) — the slice the
     model reads is attached as result["table"], and the declaration is the
     step's evidence_refs. The gate loads the same declarations.

Evidence is declared, not harvested (V15-S2a). A tool's registration says what
its results put on the table (`Tool.evidence`): the ids it returns, the run
child tables it read, the delegated work it started. A tool registered without
a declaration puts nothing on the table — visible in the first live test that
tries to cite it, which is the intended direction. Nothing walks a result
looking for id-shaped strings and guessing whether it was a retrieval.

The SAME registry is consumed by function-calling (schemas()), by the MCP server
(thin @mcp.tool wrappers), and by the recipe (direct fn call, no budget/trace).
"""

from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.services import table as tbl
from exposure_workbench.services import trace_service
from exposure_workbench.tools.arg_validation import validate_args

logger = logging.getLogger(__name__)

# The active session id for the current tool call, so calc primitives can stamp
# calc_ledger.invoked_by without threading it through every fn signature.
_session_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("tool_session_id", default=None)


def current_session_id() -> str:
    return _session_ctx.get() or "agent"


# V8-C1. The message this tool call belongs to. `invoke()` has taken message_id
# since the trace learned to group steps by turn, and passed it straight to
# record_step — so the value existed, was written to every row, and was
# unreachable from inside a tool fn. The respond gate needs it: a criterion about
# what the model did BEFORE answering is a question about this turn's steps, and
# without the id the only available scope is the whole session, where a tool call
# from four questions ago would satisfy it.
_message_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("tool_message_id", default=None)


def current_message_id() -> str | None:
    """None when a tool runs outside a turn — the recipe path, a direct call.

    Returned rather than defaulted, because a criterion scoped to "this message"
    has no meaning when there is no message, and a fabricated id would silently
    scope it to nothing.
    """
    return _message_ctx.get()

READ = "read"
DELEGATION = "delegation"
REFLECTION = "reflection"
GATE = "gate"                # respond / submit_brief — session exits

# The classes that cost no budget, because neither retrieves anything: a
# reflection is the model talking to itself, a gate is the turn's exit. Named
# rather than inlined at the one site that reads it, so a test can assert WHICH
# classes are free — and so that adding one is a decision somebody makes here,
# once, rather than a tuple that drifts.
BUDGET_FREE_CLASSES = (REFLECTION, GATE)



@dataclass(frozen=True)
class Evidence:
    """What a tool's results put on the table (V15-S2a).

    Every id-shaped string in a result is declared. A run id is declared with
    `scope` — the run child tables this tool read — or, when `names_from` names
    a result key, with the exact quantity names under it; a run id with neither
    is not on the table. `tasks_from` names result keys holding ids of delegated
    work, which go on the table as rows of kind `task`.
    """
    scope: tuple[str, ...] = ()
    names_from: str | None = None
    tasks_from: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    json_schema: dict                                   # JSON Schema for the arguments object
    fn: Callable[..., Awaitable[dict]]                  # async (db, **args) -> dict
    tool_class: str                                     # READ | DELEGATION | REFLECTION | GATE
    budget_key: str | None = None                       # e.g. 'external_search'; None = plain tool
    # V13-S4. What this call looks like to a person watching the turn, as a
    # format template over the call's own arguments:
    #
    #     "Evaluating {name} for {ticker}"  ->  Evaluating total debt for AAPL
    #
    # `description` is for the model and says what the tool is FOR; this says
    # what one call of it is DOING, in the past-facing present tense a progress
    # line is read in. They are different sentences to different readers, which
    # is why this is a field and not a slice of the other one: the activity
    # panel was rendering `get_portfolio_snapshot` and `evaluate_formula`, which
    # are correct and are not English.
    #
    # Required in practice — tests/test_tool_display.py fails the build for a
    # registered tool without one — and defaulted here only so the dataclass
    # stays constructible in the argument order every registration already uses.
    display: str = ""
    # What this tool's results put on the table. None for a gate, a reflection,
    # and any tool whose results are not evidence (get_task_status reads state,
    # list_risk_limits reads policy).
    evidence: Evidence | None = None


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"duplicate tool {tool.name!r}")
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise KeyError(f"unknown tool {name!r}")
        return self.tools[name]

    def schemas(self, names: list[str] | None = None) -> list[dict]:
        """OpenAI-style function tool schemas for a face (or all tools)."""
        chosen = [self.tools[n] for n in (names or self.tools)]
        return [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.json_schema},
            }
            for t in chosen
        ]





def _summarize(result: Any) -> str:
    if isinstance(result, dict):
        if result.get("error"):
            return f"error: {result.get('error')}"
        keys = [k for k in result if not k.startswith("_")]
        return "keys: " + ", ".join(keys[:8])
    return str(result)[:200]


# ── the wrapper: the single enforcement point ───────────────────────────────────

async def invoke(
    registry: ToolRegistry,
    db: AsyncSession,
    session_id: str,
    tool_name: str,
    args: dict,
    *,
    message_id: str | None = None,
) -> dict:
    """Run one LLM-driven tool call with budget + trace enforcement.

    Returns a structured dict always (never raises to the caller): budget
    rejections and tool errors come back as {'error': ...} and are traced, so an
    agent loop can read the failure and adapt instead of crashing.
    """
    started = time.monotonic()
    _session_ctx.set(session_id)          # so calc tools stamp ledger.invoked_by
    _message_ctx.set(message_id)          # so the gate can ask what THIS turn did
    tool = registry.tools.get(tool_name)
    if tool is None:
        await trace_service.record_step(
            db, session_id, step_type="tool_call", tool_name=tool_name, args=args,
            result_summary=f"unknown tool {tool_name!r}", evidence_refs=[], status="error",
        )
        return {"error": "unknown_tool", "tool": tool_name}

    # 1) validate the arguments — before anything is spent.
    #
    # Ordering is the point: a call the tool could never have run must not cost
    # the session a slot out of fifteen. It is traced anyway, with the same
    # 'rejected' status a budget refusal gets, because a refusal is something
    # the desk should be able to see the agent having provoked.
    problems = validate_args(tool.json_schema, args)
    if problems:
        await trace_service.record_step(
            db, session_id, step_type=_step_type(tool), tool_name=tool_name, args=args,
            result_summary=f"invalid arguments: {len(problems)} problem(s)", evidence_refs=[],
            status="rejected", duration_ms=int((time.monotonic() - started) * 1000),
            message_id=message_id,
        )
        return {"error": "invalid_arguments", "problems": problems}

    # 2) reserve budget. REFLECTION and GATE are free by design, for the same
    # reason stated two different ways: the budget bounds how much EVIDENCE a
    # turn gathers, and neither of these retrieves any. A reflection is the model
    # talking to itself; a gate is the turn's verdict and its only exit.
    #
    # The gate was charged here until V7-Q2, and the failure it produced was not
    # a degraded answer — it was a turn that could not end. Once the counter hit
    # its limit, respond was refused for lacking budget it needed in order to
    # spend nothing, and the loop then burned every remaining round trip at ~12k
    # prompt tokens each on a state where no outcome existed, before telling the
    # user their citations had been the problem. Reproduced from
    # sess_d90c19451151 and pinned in test_turn_budget_live.
    #
    # Exempting it is not a hole: a gate ENDS the turn, so there is nothing left
    # for an unbudgeted call to go on to do. What running out of budget now means
    # is the right thing — answer with the evidence you managed to gather.
    #
    # Derived from tool_class, never from a name: the property is being an exit,
    # and any exit written later inherits this without anybody remembering to.
    if tool.tool_class not in BUDGET_FREE_CLASSES:
        try:
            await sess.reserve(db, session_id, is_external_search=(tool.budget_key == "external_search"))
        except sess.BudgetExceeded as e:
            await trace_service.record_step(
                db, session_id, step_type=_step_type(tool), tool_name=tool_name, args=args,
                result_summary=str(e), evidence_refs=[], status="rejected",
                duration_ms=int((time.monotonic() - started) * 1000), message_id=message_id,
            )
            return {"error": "budget_exceeded", "kind": e.kind, "used": e.used, "limit": e.limit}

    # 3) run the fn, catching failures as structured results
    status = "completed"
    try:
        result = await tool.fn(db, **args)
        if not isinstance(result, dict):
            result = {"result": result}
    except Exception as exc:  # noqa: BLE001 — a tool error must not kill the agent loop
        logger.warning("tool %s failed: %s", tool_name, exc, exc_info=True)
        status = "error"
        result = {"error": "tool_error", "detail": str(exc)}
        # If the tool failed part-way through its own DML, this session is now in
        # an aborted transaction and the trace write below would raise
        # InFailedSQLTransactionError — straight past this handler, past the agent
        # loop, and out as a bare 500. The docstring above promises this function
        # never raises; keeping that promise means leaving the session usable.
        # The tool's partial work is being discarded anyway.
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001 — nothing left to salvage either way
            logger.exception("could not roll back after %s failed", tool_name)

    # 4) the table. The tool's registration says what its result puts on it;
    # build() names those quantities (services/quantities.py), attaches the
    # slice the model reads, and returns the declaration as stored — narrowed
    # to what fit, so the record and the payload agree. A gate's verdict, a
    # reflection and any tool registered without a declaration put nothing on
    # the table, which is what stops a refusal's echoed ids from becoming
    # evidence on the next attempt.
    refs: list[dict] = []
    if status == "completed" and tool.evidence is not None and isinstance(result, dict):
        declared = tbl.declare(
            result, scope=tool.evidence.scope or None,
            names=_names_from(result, tool.evidence.names_from),
            tasks=[v for k in tool.evidence.tasks_from
                   for v in [result.get(k)] if isinstance(v, str)],
        ).pop("evidence", [])
        try:
            refs, slice_ = await tbl.build(db, declared)
        except Exception:  # noqa: BLE001 — a table that cannot be built is a result with nothing citable
            logger.exception("could not build the table for %s (session %s)", tool_name, session_id)
            refs, slice_ = [], {}
        if slice_:
            result["table"] = slice_
    try:
        await trace_service.record_step(
            db, session_id, step_type=_step_type(tool), tool_name=tool_name, args=args,
            result_summary=_summarize(result), evidence_refs=refs, status=status,
            duration_ms=int((time.monotonic() - started) * 1000), message_id=message_id,
        )
    except Exception:  # noqa: BLE001
        # A hole in the audit trail is bad; turning one into an unexplained 500
        # that also spends the user's turn is worse. Log loudly and let the agent
        # see the structured result it was given.
        logger.exception("could not record trace step for %s (session %s)", tool_name, session_id)
    return result


def _names_from(result: dict, key: str | None) -> list[str] | None:
    """The exact quantity names a read-by-name tool returned, for its declaration."""
    if key is None:
        return None
    got = result.get(key)
    if isinstance(got, dict):
        return [n for names in got.values() if isinstance(names, dict) for n in names]
    if isinstance(got, list):
        return [n for n in got if isinstance(n, str)]
    return None


def _step_type(tool: Tool) -> str:
    if tool.tool_class == DELEGATION:
        return "delegation"
    if tool.tool_class == REFLECTION:
        return "think"
    if tool.tool_class == GATE:
        return "respond"
    return "tool_call"
