"""The agents' connection to the provider (V4-S2) — one completion, one row.

A completion produces three things: text, tool_calls and usage. Two of them have
something waiting for them. Text has to survive respond or submit_brief before a
user can see it; every tool call goes through MCP and invoke(), which records it
whether the loop wants that or not. usage had nothing waiting, so both loops
threw it away — meta_agent named it `_usage`, research_session unpacked it and
never read it — and the single action in this system that actually costs money
was the only one leaving no trace of having happened.

The fix is deliberately not "record the usage in both loops". That is a rule,
and a rule is kept until the third loop is written by someone who never read
this file. What this module does instead is take the discard away: `chat`
returns (content, tool_calls), so a caller has nothing to throw away and no
version of the loop can be written that spends money quietly. The import law in
tests/test_v2_audit.py is what keeps this the agents layer's only way to the
provider; without it the module is a convenience rather than a gate.

There is no connection here to open or close, and the `async with` is not
pretending there is. What it binds is a session id and a message id — the two
facts that decide whose ledger a row lands in — for exactly as long as the turn
they belong to, the same lifetime tool_session already has. A loop opening both
at the top reads as one turn holding one identity, which is what it is.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from exposure_workbench.llm import client as llm_client
from exposure_workbench.services import trace_service

logger = logging.getLogger(__name__)


class LlmSession:
    """What a loop holds for the length of a turn: one verb, returning two things."""

    def __init__(self, db_factory, session_id: str, message_id: str | None):
        self._db_factory = db_factory
        self._session_id = session_id
        self._message_id = message_id

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kw,
    ) -> tuple[str | None, list[dict] | None]:
        """One completion, recorded as an `llm_call` step.

        The row goes in its OWN database session, committed on its own. A
        completion is a fact the moment the provider answers, and hanging it off
        whatever transaction the loop happens to have open would make the record
        of a spend depend on whether the turn later succeeded — the rows that
        would go missing are exactly the expensive ones.

        prompt_peak (context_budget) is a different number and both stay: that
        is a tiktoken estimate bounding the NEXT turn, this is what the provider
        says it charged for the turn just taken. Reconciling them is a question
        someone can now ask, because both are written down.

        A call that never returns leaves no row, and deliberately: there is no
        usage to record and no completion to attribute one to. The provider
        raising still ends the turn at the caller exactly as it always has —
        this module made the successful path unskippable, not the failed one
        survivable.
        """
        content, tool_calls, usage = await llm_client.chat_with_tools(
            messages=messages, tools=tools, **kw,
        )

        # Unpacked BEFORE the try below, on purpose. A usage dict missing a key
        # is chat_with_tools having changed its shape — a code error, which must
        # stop the first turn that hits it rather than turn into a logged line
        # and a silently empty ledger. The try covers the write, not the shape.
        model = usage["model"]
        prompt_tokens = usage["prompt_tokens"]
        completion_tokens = usage["completion_tokens"]

        calls = len(tool_calls or [])
        try:
            async with self._db_factory() as db:
                await trace_service.record_step(
                    db, self._session_id,
                    step_type="llm_call",
                    tool_name=None,          # nothing was called; this IS the call
                    args=None,
                    result_summary=f"{model}: {calls} tool call{'' if calls == 1 else 's'}",
                    evidence_refs=[],
                    message_id=self._message_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
                await db.commit()
        except Exception:  # noqa: BLE001 — see below
            # The same choice invoke() makes about its own trace write, for the
            # same reason and with more at stake. The money is already spent and
            # the answer is in hand; raising here would throw away a turn the
            # user paid for in order to keep a book tidy, and the book would
            # still be missing the row. Loud in the log, whole to the caller.
            logger.exception(
                "could not record llm_call for session %s (model %s, %d/%d tokens)",
                self._session_id, model, prompt_tokens, completion_tokens,
            )

        return content, tool_calls


@asynccontextmanager
async def llm_session(db_factory, session_id: str, message_id: str | None = None):
    """The provider, bound to one session's ledger.

    db_factory rather than a session: the row is committed per completion, and a
    loop that handed its own open transaction in would be deciding, without
    meaning to, that a failed turn spends nothing.

    message_id is optional because a research run has no message to hang a step
    off — it is a session that IS one unit of work. A chat turn has one, and
    passing it is what lets a user's turn be costed rather than only their
    session.
    """
    yield LlmSession(db_factory, session_id, message_id)
