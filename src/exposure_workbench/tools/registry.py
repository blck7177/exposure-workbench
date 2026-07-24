"""ToolRegistry + wrapper (M10) — the single enforcement point.

A tool is a five-tuple: {name, json_schema, fn, tool_class, budget_key}.
The wrapper does three things automatically around every LLM-driven call:

  1. reserve budget (agent_session_service) — before the tool runs
  2. run the fn, catching failures as structured results (never crashes the loop)
  3. record a trace step (trace_service) — success, rejection, or error alike,
     auto-extracting evidence_refs from the return value

Evidence-ref extraction is automatic: any returned id-shaped field (fact_/chunk_/
calc_/src_/co_/rrun_/alert_/run_ or an explicit {type,id}/citation) becomes a
trace ref, so tool authors can't forget to report what a call touched.

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

_ID_PREFIXES = ("fact_", "chunk_", "calc_", "src_", "co_", "rrun_", "filing_", "alert_", "run_")


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

    # 3) trace (auto-extract evidence refs)
    refs = extract_evidence_refs(result) if status == "completed" else []
    await trace_service.record_step(
        db, session_id, step_type=_step_type(tool), tool_name=tool_name, args=args,
        result_summary=_summarize(result), evidence_refs=refs, status=status,
        duration_ms=int((time.monotonic() - started) * 1000), message_id=message_id,
    )
    return result


def _step_type(tool: Tool) -> str:
    if tool.tool_class == DELEGATION:
        return "delegation"
    if tool.tool_class == REFLECTION:
        return "think"
    if tool.tool_class == GATE:
        return "respond"
    return "tool_call"
