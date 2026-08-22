"""Meta-agent (M10) — the single conversational entity the user talks to.

A thin tool-calling loop: it answers directly with the read tools when data is
ready, delegates heavy/unready work (non-blocking) and reports the run id, and
exits by calling respond. The system prompt states the role and the evidence
discipline's WHY — it is not a rulebook, because the architecture (ids required
to cite, wrapper-enforced budget/trace) is what actually constrains behaviour.

Its tools arrive over an MCP client from the resident tool face (MCP_PLAN P3,
R4): the same registry behind the same wrapper, reached the way this
architecture has said the agent face is reached since M10 — which until P3 it
was not, and which since R4 is a request to a container of its own.

History is persisted as agent_messages so a session survives across turns.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import update

from exposure_workbench.agents.llm_session import llm_session
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import AgentMessage, AgentSession
from exposure_workbench.services import context_budget
from exposure_workbench.tools import faces
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

_SYSTEM = """You are the analyst assistant for a portfolio risk & issuer-intelligence desk.

You can answer questions about the portfolio's issuers using financial facts and \
calculations, filing search/read, market stats and portfolio alerts. State no \
number you did not get from a tool, and cite the evidence ids (fact_/calc_/chunk_/\
src_/run_/alert_) behind any factual claim — because a claim the desk can't trace \
back to a filing, a calculation, a source or a run is not usable.

For a question about the portfolio as a whole — its holdings, largest exposures, \
overall risk — call get_portfolio_snapshot first: it gives you the portfolio, its \
top sector/issuer weights and active alerts, with the run_id behind the numbers. \
Discover the holdings from there and then dig into the issuers that matter; never \
ask the user for an internal portfolio id or as-of date. The snapshot may include \
a shared demo portfolio (is_own=false); when the user has their own (is_own=true), \
answer about theirs unless they clearly mean the demo.

If an issuer's data isn't ready yet, call ensure_company_ready and tell the user \
it's being prepared (this runs in the background — don't wait). For a full written \
brief, call start_issuer_research and give the user the run id to follow. These \
return immediately; never block waiting for them.

Finish every turn by calling respond. A reply with no numbers in it — a greeting, \
a clarifying question — needs no citations; any reply that states a number must \
cite the evidence that number came from. If respond rejects a citation, fix that \
id — never invent one. If it says citations_required, you stated a number you did \
not fetch: call the tool that produces it, then cite what comes back."""


# What the user is told when the loop ended without the gate ever accepting an
# answer. TWO paths reach it and both must, because they are the same event: the
# model stopped calling tools on the last turn, or it spent every turn without a
# respond the gate would take. The first used to substitute the model's raw
# content as the answer — an ungated reply, with citations=[], indistinguishable
# from a verified one — and the second used to emit "(no response produced)",
# which reads like a bug rather than a refusal.
# ONE wording for both paths — that convergence is the property above, and it
# stays. What this sentence must NOT do is diagnose: it used to end "every
# attempt either cited evidence I had not actually retrieved or stated a figure
# I could not trace back to a source", which is a claim about a cause, asserted
# by the one code path nothing checks. On the first path there is no attempt to
# describe. And in the turn that prompted this (V7-Q2) the real cause was an
# exhausted tool budget, so the user was pointed at citations that were never
# the problem — a system whose whole claim is that it does not say what it
# cannot support, saying exactly that, in its failure message.
#
# So it states the BAR and that the turn did not clear it, which is true however
# the turn ended. The cause is not lost, it moves to meta, where it is machine
# readable and cannot mislead a reader.
_GATE_EXHAUSTED_TEXT = (
    "I could not produce an answer I can stand behind for this turn — everything "
    "I state has to trace back to evidence I actually retrieved, and I did not "
    "get there. Ask again, or narrow the question to one issuer or one metric."
)
_GATE_EXHAUSTED_META = {"gate": "exhausted"}


async def _load_history(db, session_id: str) -> list[dict]:
    from sqlalchemy import select
    rows = (await db.execute(
        select(AgentMessage).where(AgentMessage.session_id == session_id).order_by(AgentMessage.created_at)
    )).scalars().all()
    return [{"role": m.role, "content": m.content or ""} for m in rows]


async def handle_message(
    db_factory,
    session_id: str,
    user_text: str,
    max_turns: int = 16,
) -> dict:
    """Run one user turn. Persists the user + assistant messages; returns the reply."""
    message_id = new_id("msg_")
    async with db_factory() as db:
        db.add(AgentMessage(id=new_id("msg_"), session_id=session_id, role="user", content=user_text))
        await db.commit()
        history = await _load_history(db, session_id)

    messages = [{"role": "system", "content": _SYSTEM}, *history]
    reply_text, reply_citations = None, []
    # What the gate refused, in order. Empty is a fact, not a gap: it means the
    # turn never reached the gate, which is a different failure from one the gate
    # turned away, and the two must not read the same afterwards.
    gate_refusals: list[str] = []

    # The PEAK, not the first: messages grow with every tool result inside the
    # turn, so the largest request is the last one, and the largest request is
    # what a ceiling is about. B1 reads this back to decide the next turn.
    prompt_peak = 0

    # One connection for the turn, carrying the identity the turn runs under.
    # That identity used to be fixed when the pair was built and is now minted
    # into a token and sent with every request, which is what a resident face
    # requires: the server outlives the turn, so it cannot hold the turn's
    # tenant. The tenant still does not depend on which task the transport
    # schedules a handler in — the door binds it per request instead.
    async with tool_session(
        faces.FACE_NAME_META, session_id=session_id,
        user_id=current_user_id(), message_id=message_id,
    ) as tools_session, llm_session(db_factory, session_id, message_id) as llm:
        tools = tools_session.tools

        for turn in range(max_turns):
            prompt_peak = max(prompt_peak, context_budget.count_prompt(messages, tools))
            # No usage comes back. It used to, under the name `_usage`, and the
            # underscore was the whole problem: the turn's only real cost was a
            # value this loop was free to ignore. It is an llm_call row now,
            # written on the way through (V4-S2). prompt_peak above stays exactly
            # as it is — a tiktoken estimate bounding the NEXT turn is a different
            # number from what the provider says it charged for this one, and
            # B1 refuses on the estimate.
            content, tool_calls = await llm.chat(messages=messages, tools=tools)
            assistant_msg: dict = {"role": "assistant", "content": content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if not tool_calls:
                if turn >= max_turns - 1:
                    # Deliberately NOT `reply_text = content`. Substituting the raw
                    # model text here handed the user an answer that had passed no
                    # gate, with citations=[], rendered exactly like a verified one.
                    break
                messages.append({"role": "user", "content": "Call respond to reply to the user."})
                continue

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await tools_session.call(name, args)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(result, default=str)[:6000]})
                if name == "respond":
                    if result.get("responded"):
                        reply_text, reply_citations = result["text"], result.get("citations", [])
                    elif result.get("error"):
                        # Every refusal, in order. Diagnosing V7-Q2 meant
                        # rebuilding the turn out of agent_steps by hand, because
                        # the marker recorded that the gate never opened and
                        # never what it said.
                        gate_refusals.append(str(result["error"]))

            if reply_text is not None:
                break

    # The single convergence point for both ungated paths. The turn is still a
    # 200 and the message is still persisted: the chat_turn quota was charged and
    # committed before the loop started (routes/agent.py), the work really was
    # done, and hiding the failure from the transcript would leave the user's
    # question sitting there with no reply and no explanation.
    meta: dict = {"prompt_tokens": prompt_peak}
    if reply_text is None:
        reply_text, reply_citations = _GATE_EXHAUSTED_TEXT, []
        meta |= _GATE_EXHAUSTED_META | {"gate_refusals": gate_refusals}

    async with db_factory() as db:
        db.add(AgentMessage(id=message_id, session_id=session_id, role="assistant",
                            content=reply_text, citations=reply_citations, meta=meta))
        # Session-level, so the next turn can be refused before it is charged
        # without reading the whole message history back first.
        await db.execute(
            update(AgentSession).where(AgentSession.id == session_id)
            .values(last_prompt_tokens=prompt_peak)
        )
        await db.commit()

    return {"session_id": session_id, "message_id": message_id,
            "text": reply_text, "citations": reply_citations, "meta": meta}
