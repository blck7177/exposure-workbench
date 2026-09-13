"""The analyst (V33) — the single conversational entity the user talks to.

Two jobs used to share this loop's context: deciding what to look at, and
transcribing that decision into a typed program and a typed claims list. The
20-question round (docs/spikes/v33) measured the cost — 8 completions a turn,
68% of exits refused, and twelve of nineteen accepted answers false to a reader
for reasons the transcription hid. Here the loop holds ONE tool, request_evidence,
and its exit is plain text.

    read : the role and one rule; the briefing (the desk's map for the subjects
           the question names — names, dates, coverage, never a figure); the
           skill's domain knowledge for the question; the digests that come back
    write: request_evidence(items), decision-level (subjects, the desk's names
           for what is wanted, a window, a comparison); then prose

The evidence broker (agents/evidence_broker.py) does the tools: it compiles or
writes the program, runs it under the same session's token, and returns every
figure with its id. The answer check (services/answer_check.py) reads the prose
against the session ledger and refuses with every problem at once; the analyst
gets one rewrite. Nothing reaches the user that the check did not accept.

History is persisted as agent_messages so a session survives across turns.
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from sqlalchemy import update

from exposure_workbench.agents import evidence_broker, evidence_request
from exposure_workbench.agents.llm_session import llm_session
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.analytics import skill
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import AgentMessage, AgentSession
from exposure_workbench.services import answer_check, briefing as briefing_svc, context_budget, ledger as ledger_svc, trace_service
from exposure_workbench.tools import faces
from exposure_workbench.utils import json as ejson
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

_SYSTEM = """You are the analyst for a portfolio risk & issuer-intelligence desk. The analysis is your job: take \
the question apart, decide what to look at and what to compare, ask the desk for the evidence, and say what it \
shows and what it means for the question asked — its implication for this book and what would change your reading.

You compute and fetch nothing yourself. request_evidence(items) is how you ask: name the subjects (tickers, port_… \
ids) and what you want about them in the desk's own names from the BRIEFING, with a window and a comparison where \
the question has one. The desk returns every figure with its id and identity, passages to quote, and what it could \
not do. Ask for everything a first pass needs in one request; ask again only for what the answer still lacks. \
Check the question's premises against the briefing first (which holdings are in which sector, what the desk holds).

Your reply is plain prose, and every number you write is one the desk showed you, written as it was shown \
(16.0%, $10.63M, 0.78×). When one number stands under two ids, put the id after it in brackets [f_…]. A table or a \
chart is [table: <node>] or [chart: <node>], naming a node from the evidence. Quote a passage's words verbatim \
inside quotation marks. A superlative rests on an ordering the desk computed (compare: rank). What the desk could \
not do or does not hold, say so in words and say what you gave instead — never an estimate, never a figure carried \
from one company or date to another, never a nearby figure under the asked-for name.

If your reply is not accepted, you are told every problem and its fix; fix them all in one rewrite. You have two."""


# What the user is told when the turn ended without an accepted answer. ONE
# wording for every path to it (the model never wrote an answer, or every
# answer it wrote was refused); it states the bar, not a cause, because the
# cause is in meta where it cannot mislead a reader (V7-Q2).
_GATE_EXHAUSTED_TEXT = (
    "I could not produce an answer I can stand behind for this turn — everything "
    "I state has to trace back to evidence I actually retrieved, and I did not "
    "get there. Ask again, or narrow the question to one issuer or one metric."
)
_GATE_EXHAUSTED_META = {"gate": "exhausted"}

# How much of one tool result reaches the model (research_session reads this too).
TOOL_RESULT_LIMIT = 28_000

# The rewrites an answer gets: the first refusal lists every problem, the
# second ends the turn. Decided 2026-09-13 with the natural-language exit.
MAX_ANSWER_ATTEMPTS = 2

# The only tool on the analyst's face. Kept as a tuple for the tests that pin
# the budget-free names: the analyst's tool retrieves nothing itself.
_BUDGET_FREE_TOOLS = (evidence_request.TOOL_NAME,)

_WRITE_OR_ASK = "Write the answer, or request the evidence you still need."


async def _load_history(db, session_id: str) -> list[dict]:
    from sqlalchemy import select
    rows = (await db.execute(
        select(AgentMessage).where(AgentMessage.session_id == session_id).order_by(AgentMessage.created_at)
    )).scalars().all()
    return [{"role": m.role, "content": m.content or ""} for m in rows]


async def _briefing(db_factory, text: str) -> dict:
    """The desk's map for the question's subjects; a failure to build it is a
    turn without a map, not a lost turn."""
    try:
        async with db_factory() as db:
            return await briefing_svc.for_question(db, text)
    except Exception as exc:  # noqa: BLE001 — logged; the analyst can still request evidence by name
        logger.exception("briefing failed")
        return {"unavailable": type(exc).__name__}


async def _load_ledger(db_factory, session_id: str):
    async with db_factory() as db:
        return await ledger_svc.load(db, session_id)


async def _record_answer(db_factory, session_id: str, message_id: str, text: str, verdict) -> None:
    try:
        async with db_factory() as db:
            await trace_service.record_step(
                db, session_id, step_type="answer", tool_name="answer", args={"text": text[:4000]},
                result_summary=("accepted" if verdict.ok else f"refused: {verdict.error}; {verdict.detail}"),
                evidence_refs=[], status="completed" if verdict.ok else "rejected", message_id=message_id)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record answer step for %s", session_id)


def _refusal_message(verdict) -> str:
    lines = [f"Your reply was not accepted: {len(verdict.problems)} problem(s), each with its fix. "
             f"Rewrite the whole reply once, fixing all of them — or request the evidence you lack first."]
    for p in verdict.problems[:20]:
        what = p.get("figure") or p.get("id") or p.get("node") or p.get("quote") or p.get("word") or p.get("phrase") or ""
        line = f"- {p['at']} {p['reason']}" + (f" ({what!r})" if what else "")
        if p.get("fix"):
            line += f": {p['fix']}"
        if p.get("candidates"):
            line += " candidates: " + "; ".join(f"[{c['id']}] {c.get('measure')} {c.get('subject')} {c.get('as_of')}" for c in p["candidates"][:4])
        lines.append(line)
    return "\n".join(lines)


async def handle_message(
    db_factory,
    session_id: str,
    user_text: str,
    max_turns: int = 16,
    deny: Sequence[str] = (),
) -> dict:
    """Run one user turn. Persists the user + assistant messages; returns the reply."""
    message_id = new_id("msg_")
    async with db_factory() as db:
        db.add(AgentMessage(id=new_id("msg_"), session_id=session_id, role="user", content=user_text))
        await db.commit()
        history = await _load_history(db, session_id)

    brief = await _briefing(db_factory, user_text)
    messages: list[dict] = [{"role": "system", "content": _SYSTEM},
                            {"role": "system", "content": "BRIEFING — the desk's map for this question (names, dates and coverage; "
                                                          "no figure here may be stated until it is requested):\n"
                                                          + json.dumps(brief, ensure_ascii=False, default=str)}]
    pushed: list[str] = []
    matched = skill.match_domains(user_text)
    examples = [ex for p in matched for ex in (p.programs or ())][:4]
    if get_settings().push_domains:
        if matched:
            pushed = [p.name for p in matched]
            messages.append({"role": "system", "content": "The desk's own knowledge for this kind of question (how it compares and "
                                                          "closes; the example programs show which names go together — you do not "
                                                          "write programs, you request by name):\n\n" + skill.push_text(matched)})
    messages += history

    reply_text, reply_citations = None, []
    reply_verified: dict | None = None
    reply_blocks: list | None = None
    gate_refusals: list[str] = []
    prompt_peak = 0
    attempts = 0
    requests = 0

    async with tool_session(
        faces.FACE_NAME_META, session_id=session_id,
        user_id=current_user_id(), message_id=message_id, deny=deny,
    ) as tools_session, llm_session(db_factory, session_id, message_id) as llm:
        broker = evidence_broker.Broker(tools_session, llm, db_factory, session_id, message_id, brief, examples=examples)
        tools = [evidence_request.REQUEST_TOOL]

        for _turn in range(max_turns):
            prompt_peak = max(prompt_peak, context_budget.count_prompt(messages, tools))
            content, tool_calls = await llm.chat(messages=messages, tools=tools)
            assistant_msg: dict = {"role": "assistant", "content": content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if tool_calls:
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    if name == evidence_request.TOOL_NAME:
                        try:
                            items = evidence_request.parse(args)
                        except ValueError as exc:
                            result: dict = {"error": "invalid_request", "detail": str(exc)}
                        else:
                            requests += 1
                            result = await broker.fulfil(items)
                    else:
                        result = {"error": "unknown_tool",
                                  "detail": f"the analyst has one tool, {evidence_request.TOOL_NAME}; the answer is your reply text"}
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": ejson.dumps_capped(result, TOOL_RESULT_LIMIT)})
                continue

            text = (content or "").strip()
            if not text:
                messages.append({"role": "user", "content": _WRITE_OR_ASK})
                continue

            led = await _load_ledger(db_factory, session_id)
            verdict = answer_check.check(text, led, question=user_text)
            await _record_answer(db_factory, session_id, message_id, text, verdict)
            if verdict.ok:
                acc = answer_check.accepted(text, verdict, led)
                reply_text, reply_citations = acc["text"], acc["citations"]
                reply_verified, reply_blocks = acc["verified"], acc["blocks"]
                break
            attempts += 1
            gate_refusals.append(verdict.error)
            if attempts >= MAX_ANSWER_ATTEMPTS:
                break
            messages.append({"role": "user", "content": _refusal_message(verdict)})

    meta: dict = {"prompt_tokens": prompt_peak, "pushed": pushed, "requests": requests,
                  "briefing_subjects": brief.get("subjects") if isinstance(brief, dict) else None,
                  "writer_calls": getattr(broker, "writer_calls", 0)}
    if reply_verified is not None:
        meta["verified"] = reply_verified
    if reply_blocks is not None:
        meta["blocks"] = reply_blocks
        meta["format"] = "blocks"
    if reply_text is None:
        reply_text, reply_citations = _GATE_EXHAUSTED_TEXT, []
        meta |= _GATE_EXHAUSTED_META | {"gate_refusals": gate_refusals}

    async with db_factory() as db:
        db.add(AgentMessage(id=message_id, session_id=session_id, role="assistant",
                            content=reply_text, citations=reply_citations, meta=meta))
        await db.execute(
            update(AgentSession).where(AgentSession.id == session_id)
            .values(last_prompt_tokens=prompt_peak)
        )
        await db.commit()

    return {"session_id": session_id, "message_id": message_id,
            "text": reply_text, "citations": reply_citations, "meta": meta}
