"""V21-S1. A batch of tool calls is dispatched up to its first refusal per tool.

THE CLASS THIS ENDS. A model answers "rank the ten holdings by net income" by
sending ten calls in one assistant message, and the loop dispatched them whole:
ten MCP round trips, ten budget units, and only then the ten results — all ten
of them the same refusal, because the belief the batch was composed under was
wrong once (`evaluate_formula("net_income")` is not a formula; V19 round 1).
The refusal that would have corrected the second call arrived after the tenth,
with five units of fifteen left. Round 4 of the same battery spent ten on a
call that was right and reached `rank` with five to spare; whether a
multi-issuer question completes has depended on the first guess being right.

The wrapper cannot see this: it sees one call at a time and every one of the
ten was, on its own, a call to refuse. Only the loop holds the batch, so the
rule lives here, once, for both loops: within one assistant message, once a
tool has refused a call, the remaining calls TO THAT TOOL are not sent. They
come back to the model as `not_attempted`, naming the refusal they were held
behind, and they cost nothing — no round trip, no budget, no table. The model
reads the refusal in the same turn it would have read the ten, and re-issues
whichever calls still apply.

WHAT COUNTS AS A REFUSAL is a property of the result, not a list of codes: an
`error` with nothing on the table. A refusal that minted an absence row —
`get_flow` for a metric the issuer never filed, `get_beta` on too few
observations — arrives WITH a table and is a finding about the world; the
model may well want the same read for the other nine names, and gets it. A
result that put nothing on the table refused the call itself (an unknown
formula, an unknown name, arguments the schema rejected, a face that is down),
and that is what the other nine were about to repeat.

Two scopes, both structural:
  - by tool name, for a call-shaped refusal — the belief that was wrong was
    about how this tool is called;
  - the whole rest of the batch, once the evidence pool is empty
    (`budget_exceeded` on the turn or session pool) — sess_1c71b5fb7f79's 65
    refused calls were one message of 69, and nothing after the fifteenth
    could have returned evidence.

The budget-free tools — the pause and the exits — are never held and never
hold: they put nothing on the table by construction, so their refusals say
nothing about any read.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

NOT_ATTEMPTED = "not_attempted"

# The pools whose exhaustion means no later call in the batch can return
# evidence. `external_search` is not one: a search pool running dry says
# nothing about a filing read that follows it.
_EVIDENCE_POOLS = ("turn_tool", "tool")

Recorder = Callable[[str, dict, dict], Awaitable[None]]


def trace_recorder(db_factory, session_id: str, message_id: str | None = None) -> Recorder:
    """The recorder both loops hand dispatch(): one `rejected` step per held
    call, in the same table the wrapper writes, with the summary saying what it
    was held behind. Its own session per row — the loop holds no transaction
    open across a turn, and a held call is not the place to start one."""
    from exposure_workbench.services import trace_service

    async def _record(name: str, args: dict, result: dict) -> None:
        behind = result.get("held_behind") or {}
        async with db_factory() as db:
            await trace_service.record_step(
                db, session_id, step_type="tool_call", tool_name=name, args=args,
                result_summary=f"not attempted: held behind {behind.get('error')}",
                evidence_refs=[], status="rejected", message_id=message_id,
            )
            await db.commit()
    return _record


def is_call_refusal(result: Any) -> bool:
    """An error that put nothing on the table: the CALL was refused, not the
    question it asked. The table is the wrapper's own attachment
    (registry.invoke step 4), so its absence is the wrapper saying so."""
    return (isinstance(result, dict) and bool(result.get("error"))
            and not isinstance(result.get("table"), dict))


def is_pool_empty(result: Any) -> bool:
    return (isinstance(result, dict) and result.get("error") == "budget_exceeded"
            and result.get("kind") in _EVIDENCE_POOLS)


def holds(refusal: dict, args: dict) -> bool:
    """Whether a refusal holds a later call to the same tool.

    V23 (the V21 §7 residual, met on the first live turn): a refusal that
    names the ARGUMENT it is about — `held_on: {"metric": "capital_expenditures"}`
    — holds only later calls that repeat that value; a call for another
    metric is a different question and goes out. A refusal that names no
    argument is about the call itself and holds by tool, as V21 did.
    """
    on = refusal.get("held_on")
    if not isinstance(on, dict) or not on:
        return True
    return all(args.get(k) == v for k, v in on.items())


def parse_args(tc: dict) -> dict:
    try:
        return json.loads(tc["function"]["arguments"] or "{}")
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def _held_behind_refusal(name: str, refusal: dict) -> dict:
    code = refusal.get("error")
    return {
        "error": NOT_ATTEMPTED,
        "tool": name,
        "held_behind": {"error": code,
                        **({"detail": refusal["detail"]} if isinstance(refusal.get("detail"), str) else {})},
        "detail": (
            f"an earlier {name} call in this same message was refused ({code}) and put "
            f"nothing on the table, so this one was not sent and cost nothing. Read that "
            f"refusal, then re-issue whichever of these calls still apply."),
    }


def _held_behind_budget(name: str, refusal: dict) -> dict:
    return {
        "error": NOT_ATTEMPTED,
        "tool": name,
        "held_behind": {"error": "budget_exceeded", "kind": refusal.get("kind"),
                        "used": refusal.get("used"), "limit": refusal.get("limit")},
        "detail": (
            f"the evidence budget was exhausted by an earlier call in this same message "
            f"({refusal.get('used')}/{refusal.get('limit')}), so this call was not sent. "
            f"Answer with the evidence already gathered."),
    }


async def dispatch(
    tools_session,
    tool_calls: list[dict],
    *,
    free: tuple[str, ...],
    record: Recorder | None = None,
) -> list[tuple[dict, dict, dict]]:
    """Send one assistant message's tool calls, in order, holding the ones an
    earlier refusal has already answered. Returns (tool_call, args, result)
    per call — every call gets exactly one result, so every tool_call_id gets
    its tool message.

    `record` is given each HELD call so the trace shows it: a held call never
    reaches the wrapper, and a turn whose steps were fewer than its calls with
    nothing saying why is the audit gap V7-Q2 was diagnosed through.
    """
    refused: dict[str, list[dict]] = {}
    pool_empty: dict | None = None
    out: list[tuple[dict, dict, dict]] = []
    for tc in tool_calls:
        name = tc["function"]["name"]
        args = parse_args(tc)
        behind = next((r for r in refused.get(name, ()) if holds(r, args)), None)
        if name in free:
            result = await tools_session.call(name, args)
        elif pool_empty is not None:
            result = _held_behind_budget(name, pool_empty)
        elif behind is not None:
            result = _held_behind_refusal(name, behind)
        else:
            result = await tools_session.call(name, args)
            if is_pool_empty(result):
                pool_empty = result
            elif is_call_refusal(result):
                refused.setdefault(name, []).append(result)
        if result.get("error") == NOT_ATTEMPTED and record is not None:
            try:
                await record(name, args, result)
            except Exception:  # noqa: BLE001 — the audit row must not cost the turn
                logger.exception("could not record a held call to %s", name)
        out.append((tc, args, result))
    return out
