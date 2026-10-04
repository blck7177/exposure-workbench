"""The agents' connection to the provider: one request, one recorded row, one conversation.

A loop holds a Conversation — the native input items of its own exchange with the
model: what it said, what the model answered (reasoning included), what each tool
returned — and asks `next` for the model's next turn. Two things are decided here
and nowhere else:

  * THE MUTABLE TAIL. The desk's current work view changes between requests, and a
    changed block anywhere before the stable history invalidates the provider's
    prefix cache for everything after it (the Q07 live runs: six lead requests of
    18–21k tokens each, none cached). So the conversation is append-only and the
    view travels as a tail the caller passes per request, placed last and never
    kept.
  * THE RECORD. Every request writes an `llm_call` step with what was sent since the
    last one (the appended items and the tail), what came back (every output item),
    the usage the provider charged and the configuration in force. A completion
    that cannot be recorded does not count as having happened: the write failing
    ends the turn, loudly. Nothing is discarded in order to keep an answer.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from exposure_workbench.llm import client as llm_client
from exposure_workbench.llm.client import ModelTurn
from exposure_workbench.services import trace_service

logger = logging.getLogger(__name__)

ROLES = ("lead", "specialist", "research", "report")


@dataclass(frozen=True)
class ModelPolicy:
    """Which model a role spends on, and how it thinks. Read from settings once per
    turn; a combination the provider refuses is a configuration error it raises."""
    model: str
    reasoning_effort: str | None
    max_output_tokens: int

    @classmethod
    def for_role(cls, role: str) -> "ModelPolicy":
        from exposure_workbench.app_state.settings import get_settings
        s = get_settings()
        if role not in ROLES:
            raise ValueError(f"role {role!r} is not one of {ROLES}")
        model = {"lead": s.lead_model, "specialist": s.analyst_model, "research": s.research_model,
                 "report": s.report_model}[role] or s.openai_model
        effort = {"lead": s.lead_reasoning_effort, "specialist": s.analyst_reasoning_effort,
                  "research": s.research_reasoning_effort, "report": s.report_reasoning_effort}[role]
        return cls(model=model, reasoning_effort=effort or None, max_output_tokens=s.max_output_tokens)

    def as_dict(self) -> dict:
        return {"model": self.model, "reasoning_effort": self.reasoning_effort, "max_output_tokens": self.max_output_tokens}


@dataclass
class Conversation:
    """The native items of one exchange, append-only."""
    items: list[dict] = field(default_factory=list)
    recorded: int = 0                 # how many items the last llm_call step has seen

    def say(self, role: str, text: str) -> None:
        self.items.append(llm_client.message(role, text))

    def tool_output(self, call_id: str, output: str) -> None:
        self.items.append(llm_client.tool_output(call_id, output))

    def extend(self, output_items: list[dict]) -> None:
        self.items.extend(output_items)

    @property
    def unanswered_calls(self) -> list[str]:
        """Function calls the model made that have no output yet — a request sent with
        one of these is refused by the provider."""
        answered = {i.get("call_id") for i in self.items if i.get("type") == "function_call_output"}
        return [i["call_id"] for i in self.items if i.get("type") == "function_call" and i.get("call_id") not in answered]


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


class LlmSession:
    """What a loop holds for a turn: identity for the record, policy for the model."""

    def __init__(self, db_factory, session_id: str, message_id: str | None, *, policy: ModelPolicy,
                 actor: str | None = None, task_id: str | None = None):
        self._db_factory = db_factory
        self._session_id = session_id
        self._message_id = message_id
        self._actor = actor
        self._task_id = task_id
        self.policy = policy

    def for_actor(self, actor: str, task_id: str | None = None, policy: ModelPolicy | None = None) -> "LlmSession":
        """The same session and message, spending under another agent's name, with its
        own conversation (the caller makes one) and, if given, its own policy."""
        return LlmSession(self._db_factory, self._session_id, self._message_id, policy=policy or self.policy,
                          actor=actor, task_id=task_id)

    async def next(self, conversation: Conversation, *, instructions: str, tools: list[dict] | None,
                   tail: list[dict] | None = None, tool_choice: str | dict | None = None,
                   note: dict | None = None) -> ModelTurn:
        """The model's next turn over `conversation` plus the mutable `tail`, recorded."""
        pending = conversation.unanswered_calls
        if pending:
            raise RuntimeError(f"a request was about to be sent with function calls unanswered: {pending}")
        appended = conversation.items[conversation.recorded:]
        turn = await llm_client.respond(
            model=self.policy.model, instructions=instructions, input_items=[*conversation.items, *(tail or [])],
            tools=tools or None, reasoning_effort=self.policy.reasoning_effort,
            max_output_tokens=self.policy.max_output_tokens, tool_choice=tool_choice)
        conversation.extend(turn.output)
        conversation.recorded = len(conversation.items)
        record = {
            "request": {**self.policy.as_dict(), "instructions_sha": _sha(instructions), "instructions_chars": len(instructions or ""),
                        "tools": [t.get("name") for t in (tools or [])], "items_appended": appended, "tail": tail or [],
                        "conversation_items": len(conversation.items) - len(turn.output)},
            "response": {"output": turn.output, "status": turn.status, "incomplete_reason": turn.incomplete_reason,
                         "response_id": turn.response_id, "model": turn.model},
            "usage": turn.usage,
            **({"note": note} if note else {}),
        }
        calls = len(turn.tool_calls)
        async with self._db_factory() as db:
            await trace_service.record_step(
                db, self._session_id, step_type="llm_call", tool_name=None, args=record,
                result_summary=f"{turn.model or self.policy.model}: {calls} tool call{'' if calls == 1 else 's'}"
                               + ("" if turn.complete else f"; {turn.status}: {turn.incomplete_reason}"),
                evidence_refs=[], message_id=self._message_id,
                prompt_tokens=turn.usage.get("input_tokens"), completion_tokens=turn.usage.get("output_tokens"),
                actor=self._actor, task_id=self._task_id)
            await db.commit()
        return turn
