"""Agent step trace (M11) — the audit backbone.

The registry wrapper calls record_step() on EVERY tool invocation (success,
rejection, or error). Recording lives below the transport, so the in-process
meta-agent, a worker research session, and an external MCP host all produce the
same trace — you can't tell which drove it, and none can skip it.

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
    step_type: str,                  # 'tool_call' | 'think' | 'delegation' | 'respond'
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
            args=_jsonable(redact_args(args or {})),
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
