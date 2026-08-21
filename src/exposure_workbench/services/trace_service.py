"""Agent step trace (M11) — the audit backbone.

The registry wrapper calls record_step() on EVERY tool invocation (success,
rejection, or error). Recording lives below the transport, so the in-process
meta-agent, a worker research session, and an external MCP host all produce the
same trace — you can't tell which drove it, and none can skip it.

There is a second writer since V4-S2, and it is not an exception to that: the
completion that DECIDES on a tool call happens on the agent's side of the MCP
door, so the wrapper cannot see it and something on that side has to record it.
agents/llm_session is that something, and it is the agents layer's only route to
a provider for exactly this reason. Its rows are step_type 'llm_call' and they
are the only rows with the token columns filled.

Key-class arguments are redacted before persistence (MVP scope: only key-shaped
fields; the user's own messages are audit subjects and stored verbatim).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import AgentStep
from exposure_workbench.utils.ids import new_step_id

_REDACT_HINTS = ("api_key", "apikey", "token", "secret", "password", "authorization", "identity")


def redact_args(args: Any) -> dict[str, Any]:
    """Redact key-class fields. Never raises — recording is not allowed to be
    the thing that kills a call.

    A non-dict payload is real: the agent loops build args with
    `json.loads(tool_call.arguments)`, and a model that emits `"NVDA"` or `[1,2]`
    produces a str or a list. Argument validation refuses those, and the
    refusal is traced — so this function is on the path where the payload is,
    by definition, not a dict. It used to do `(args or {}).items()` and raise
    AttributeError straight out of invoke(), which promises never to raise.
    Kept rather than dropped, because what the model actually sent is the one
    thing an auditor reading that rejection wants.
    """
    if not isinstance(args, dict):
        return {} if args is None else {"_raw": str(args)[:2000]}
    out: dict[str, Any] = {}
    for k, v in args.items():
        if any(h in k.lower() for h in _REDACT_HINTS):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


# Wide enough that no real call is altered — the longest argument any tool takes
# is a search query or a thought, and both are sentences.
MAX_ARG_CHARS = 4096
_TRUNCATED = "…[truncated]"


def bound_args(args: dict[str, Any]) -> dict[str, Any]:
    """Cap each string argument, so one row cannot be arbitrarily large.

    result_summary beside it has been capped at 2000 all along; args was not,
    and the arguments are the half that comes from the model. `think` takes free
    prose (its own 400-char truncation protects the return value, not the row),
    and validation made this cheaper to abuse rather than dearer: an argument
    refused before the budget is reserved is still recorded.

    Per-argument rather than per-row, so a long thought does not push the ticker
    beside it out of the trace, and here rather than as maxLength in twenty-two
    schemas because it is a property of the audit row, not of any one tool.
    """
    out: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, str) and len(v) > MAX_ARG_CHARS:
            # The marker counts against the cap. A bound that the marker pushes
            # past itself is not a bound.
            out[k] = v[:MAX_ARG_CHARS - len(_TRUNCATED)] + _TRUNCATED
        else:
            out[k] = v
    return out


def _jsonable(v: Any) -> Any:
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


async def record_step(
    db: AsyncSession,
    session_id: str,
    *,
    # 'llm_call' is the odd one and the reason the token columns below have a
    # writer at last (V4-S2): every other step_type is something the agent did
    # with a tool, this one is the completion that decided to do it.
    step_type: str,                  # 'tool_call' | 'think' | 'delegation' | 'respond' | 'llm_call'
    tool_name: str | None,
    args: dict | None,
    result_summary: str | None,
    evidence_refs: list[dict] | None,
    status: str = "completed",       # 'completed' | 'rejected' | 'error'
    duration_ms: int | None = None,
    message_id: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> str:
    """Append one immutable trace row; returns its seq-scoped id."""
    next_seq = (
        await db.execute(select(func.coalesce(func.max(AgentStep.seq), 0) + 1).where(AgentStep.session_id == session_id))
    ).scalar_one()

    step_id = new_step_id()
    db.add(
        AgentStep(
            id=step_id,
            session_id=session_id,
            message_id=message_id,
            seq=next_seq,
            step_type=step_type,
            tool_name=tool_name,
            args=_jsonable(bound_args(redact_args(args))),
            result_summary=(result_summary or "")[:2000],
            evidence_refs=evidence_refs or [],
            status=status,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    )
    await db.flush()
    return step_id
