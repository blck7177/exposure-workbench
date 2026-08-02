"""ToolRegistry + wrapper (M10) — the single enforcement point.

A tool is a five-tuple: {name, json_schema, fn, tool_class, budget_key}.
The wrapper does three things automatically around every LLM-driven call:

  1. reserve budget (agent_session_service) — before the tool runs
  2. run the fn, catching failures as structured results (never crashes the loop)
  3. record a trace step (trace_service) — success, rejection, or error alike,
     auto-extracting evidence_refs from the return value

Evidence-ref extraction is automatic: any returned id-shaped field (fact_/chunk_/
calc_/src_/alert_/run_ or an explicit {type,id}/citation) becomes a trace ref, so
tool authors can't forget to report what a call touched. Two limits are
deliberate: the prefix set is exactly what the citation gate can resolve, and
only a RETRIEVAL is harvested — never a gate's verdict, a reflection, or an
error payload, all three of which can hand the model's own words back to it
(see _harvestable).

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
from exposure_workbench.services import trace_service

logger = logging.getLogger(__name__)

# The active session id for the current tool call, so calc primitives can stamp
# calc_ledger.invoked_by without threading it through every fn signature.
_session_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("tool_session_id", default=None)


def current_session_id() -> str:
    return _session_ctx.get() or "agent"

READ = "read"
DELEGATION = "delegation"
REFLECTION = "reflection"
GATE = "gate"                # respond / submit_brief — session exits

# Exactly the prefixes the citation gate can resolve (evidence_trail_service.
# _RESOLVERS), and the symmetry is the point: harvesting an id the gate can never
# accept hands the model something it can retrieve, quote and then be refused
# for. co_/rrun_/filing_ used to be harvested and were never citable.
_ID_PREFIXES = ("fact_", "chunk_", "calc_", "src_", "alert_", "run_")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    json_schema: dict                                   # JSON Schema for the arguments object
    fn: Callable[..., Awaitable[dict]]                  # async (db, **args) -> dict
    tool_class: str                                     # READ | DELEGATION | REFLECTION | GATE
    budget_key: str | None = None                       # e.g. 'external_search'; None = plain tool


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


# ── evidence-ref extraction ─────────────────────────────────────────────────────

def _looks_like_id(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(_ID_PREFIXES)


def extract_evidence_refs(result: Any) -> list[dict]:
    """Walk a tool result and collect {type, id} refs into the four evidence stores.

    Recognises id-shaped strings, explicit {'type','id'} dicts, and 'citation(s)'
    keys, deduped in encounter order.
    """
    refs: list[dict] = []
    seen: set[tuple] = set()

    def add(ref_type: str, ref_id: str, extra: dict | None = None):
        key = (ref_type, ref_id)
        if ref_id and key not in seen:
            seen.add(key)
            refs.append({"type": ref_type, "id": ref_id, **(extra or {})})

    def walk(node: Any, key_hint: str | None = None):
        if isinstance(node, dict):
            if "type" in node and "id" in node and isinstance(node["id"], str):
                add(str(node["type"]), node["id"])
            for k, v in node.items():
                if k in ("calc_id",) and isinstance(v, str):
                    add("calc", v)
                elif k in ("fact_id", "chunk_id") and isinstance(v, str):
                    add(k.replace("_id", ""), v)
                else:
                    walk(v, k)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, key_hint)
        elif _looks_like_id(node):
            prefix = node.split("_", 1)[0]
            add({"src": "source", "co": "company", "rrun": "research_run"}.get(prefix, prefix), node)

    walk(result)
    return refs


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
    tool = registry.tools.get(tool_name)
    if tool is None:
        await trace_service.record_step(
            db, session_id, step_type="tool_call", tool_name=tool_name, args=args,
            result_summary=f"unknown tool {tool_name!r}", evidence_refs=[], status="error",
        )
        return {"error": "unknown_tool", "tool": tool_name}

    # 1) reserve budget (reflection tools are free by design)
    if tool.tool_class != REFLECTION:
        try:
            await sess.reserve(db, session_id, is_external_search=(tool.budget_key == "external_search"))
        except sess.BudgetExceeded as e:
            await trace_service.record_step(
                db, session_id, step_type=_step_type(tool), tool_name=tool_name, args=args,
                result_summary=str(e), evidence_refs=[], status="rejected",
                duration_ms=int((time.monotonic() - started) * 1000), message_id=message_id,
            )
            return {"error": "budget_exceeded", "kind": e.kind, "used": e.used, "limit": e.limit}

    # 2) run the fn, catching failures as structured results
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

    # 3) trace (auto-extract evidence refs)
    refs = extract_evidence_refs(result) if _harvestable(tool, status, result) else []
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


def _harvestable(tool: Tool, status: str, result: dict) -> bool:
    """Whether a call's return value may contribute evidence to the trail.

    Evidence is what a tool RETRIEVED. Everything below is that one sentence
    read against the ways a return value can fail to be a retrieval, and each
    clause was written after a payload got through the previous set:

    A GATE's output is never evidence — it is the session's verdict on evidence
    — and its REJECTION payload is actively poisonous: invalid_citations echoes
    the ids it just refused under problems[].id. The call itself completes
    successfully, so the harvester used to walk that payload and write the
    fabricated ids into the trail. On the next attempt they passed the trail
    check, leaving only _exists_in_db between a made-up id and an accepted
    answer, and materialize_pack wrote them into the run's evidence pack.

    A REFLECTION is the model talking to itself; think returns the thought
    verbatim, so any id-shaped string the model typed became evidence it had
    "retrieved". An ERROR PAYLOAD is a refusal, and the three that name their
    argument back — unknown_job, unknown_portfolio, not_your_portfolio — carry
    an id the model supplied rather than one a lookup produced.

    Two rules for three vectors, deliberately: a per-tool exclusion list would
    have to be extended by whoever writes the fourth echoing tool, and they will
    not know to. Nothing legitimate is lost — no error return anywhere in the
    tool layer carries a citable id that a successful call does not also carry.

    Note this closes the fabricated-id loop and nothing else: the explicit
    {type,id} branch and the calc_id/fact_id key branch are separate ingestion
    paths, and one malformed id from before V1's alert-prefix fix is still
    sitting in agent_steps.evidence_refs by way of the former.
    """
    if status != "completed" or tool.tool_class in (GATE, REFLECTION):
        return False
    return not (isinstance(result, dict) and "error" in result)


def _step_type(tool: Tool) -> str:
    if tool.tool_class == DELEGATION:
        return "delegation"
    if tool.tool_class == REFLECTION:
        return "think"
    if tool.tool_class == GATE:
        return "respond"
    return "tool_call"
