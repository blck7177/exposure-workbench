"""The lead analyst's turn: choose what to know, have the desk compute it, write the answer.

The lead is the one the user talks to. It reads the desk's catalogue, decides the
scope — and says so when the question's premise and the book disagree — picks the
measures and the comparison, runs them as one analysis, asks a specialist for the
work that needs an independent reading, and writes the answer in prose. The desk
binds dates, pairs numerators with denominators, computes, ranks and records; the
observer reads the draft against that record and comes back only when a figure
does not hold. The lead never fills a pointer, a tag or a form.

One user turn, in order: the catalogue and the method index go into the
instructions; the conversation so far and the question are the input; the work
view travels as the mutable tail of every request; tool calls are executed and
answered; a draft is observed; a draft with a problem gets one round of business
feedback (bounded); what is delivered carries its verification and completion as
data, never as a canned sentence.
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from sqlalchemy import select, update

from exposure_workbench.agents import opening, specialist, tasks as T, work_view as wvm
from exposure_workbench.agents.llm_session import Conversation, LlmSession, ModelPolicy
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import AgentMessage, AgentSession
from exposure_workbench.llm import client as llm_client
from exposure_workbench.services import ledger as ledger_svc, method_index as mi, observer as ob, render as rd
from exposure_workbench.services import scope as scope_svc
from exposure_workbench.tools import faces
from exposure_workbench.utils import json as ejson
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

TOOL_RESULT_LIMIT = 28_000

_ROLE = """You are the lead analyst of a portfolio risk & issuer-intelligence desk, and the one the user talks to. \
The analysis is yours: take the question apart, decide what has to be known, have the desk compute it, and say what \
it shows and what it means for this book.

Before anything else, check the question's premises against the DESK block: which names are in which sector, what \
the book holds, which runs exist. A premise the desk contradicts is corrected with the desk's own catalogue before \
the question is answered; a premise the desk holds nothing on is neither agreed with nor denied.

`analyze` runs one analysis as an aligned table: the measures you name over a scope you choose — named subjects, or \
a book's holdings in a sector — each at its latest period and, with `compare`, against the comparable period before \
on each issuer's own calendar, with changes in percentage points and rankings when you ask. Say the scope in business \
terms and, when the question states a count, say it as expected_count: a mismatch comes back as a mismatch. You \
never compute a date, pick a cell or copy an id; the desk binds, pairs, computes and records every cell, and a cell \
that could not be read says why.

`ask` hands work to a specialist when it needs an independent reading of its family's evidence — the text of a \
filing, a method that is not a measure over subjects, an interpretation by the analyst who holds the data. The \
specialist writes back in prose; its analyses and notes appear in the STATE block, with the desk's verification. \
`open` re-reads anything on the record by id. Ask only for what the answer still lacks.

When you have what the question needs, write the answer in prose. State the figures as the table shows them, with \
the period they are over; say which are levels, which are changes in percentage points and which relative changes; \
when you order names, say the ordering. Keep a qualification with the claim it qualifies. A judgement is yours to make \
and to say as yours; a figure the desk does not hold is said to be absent, with what was given instead. The desk \
checks your figures against its record and tells you only when one does not hold; revise that and keep the rest."""

DESK_TAG = ('<desk source="the desk\'s catalogue" trust="names, dates and holdings only — no figure here may be stated '
            'until an analysis returns it" use="choose the scope; check the question\'s premises">')
_WRITE_OR_ANALYZE = "Write the answer, or analyze or ask for what you still need."


async def _record_answer(db_factory, session_id: str, message_id: str, text: str, verdict: ob.Verdict) -> None:
    """Every draft the observer read, as an `answer` step: the whole text, what did not
    hold, and the completion — the round's record of what was written and refused."""
    from exposure_workbench.services import trace_service
    summary = verdict.summary()
    async with db_factory() as db:
        await trace_service.record_step(
            db, session_id, step_type="answer", tool_name="answer",
            args={"text": text, "verified": summary, "completion": verdict.completion,
                  "problems": [p.as_dict() for p in verdict.problems]
                              + [s for s in verdict.superlatives if s.get("status") == ob.CONTRADICTED]},
            result_summary=("accepted" if verdict.ok else
                            f"problems: {summary['contradicted']} contradicted, {summary['unsourced']} unsourced, "
                            f"{summary['ambiguous']} ambiguous") + f"; completion {summary['completion']}",
            evidence_refs=[], status="completed" if verdict.ok else "rejected", message_id=message_id,
            unbounded=("text",))
        await db.commit()


async def _load_history(db, session_id: str) -> list[dict]:
    rows = (await db.execute(
        select(AgentMessage).where(AgentMessage.session_id == session_id).order_by(AgentMessage.created_at)
    )).scalars().all()
    return [{"role": m.role, "content": m.content or ""} for m in rows]


def instructions_for(catalogue: dict) -> str:
    return (_ROLE + "\n\n" + mi.index_text(None) + "\n\n" + T.roster_text() + "\n\n"
            + DESK_TAG + "\n" + json.dumps(catalogue, ensure_ascii=False, default=str) + "\n</desk>")


async def handle_message(db_factory, session_id: str, user_text: str, *, deny: Sequence[str] = (),
                         message_id: str | None = None) -> dict:
    """Run one user turn. Persists the user and assistant messages; returns the reply.

    `message_id` lets the caller mint the turn's id before the loop runs, so a turn
    that dies in an exception still has an id its steps hang off."""
    settings = get_settings()
    message_id = message_id or new_id("msg_")
    async with db_factory() as db:
        db.add(AgentMessage(id=new_id("msg_"), session_id=session_id, role="user", content=user_text))
        await db.commit()
        history = await _load_history(db, session_id)
        catalogue = await scope_svc.catalogue(db)

    instructions = instructions_for(catalogue)
    conv = Conversation()
    for m in history[:-1]:
        if m["role"] in ("user", "assistant") and m["content"]:
            conv.say(m["role"], m["content"])
    conv.say("user", user_text)
    work = wvm.WorkView(session_id=session_id, message_id=message_id, question=user_text)
    user_id = current_user_id()
    policy = ModelPolicy.for_role("lead")
    llm = LlmSession(db_factory, session_id, message_id, policy=policy)

    def _open_tools(face: str):
        return tool_session(face, session_id=session_id, user_id=user_id, message_id=message_id, deny=deny)

    draft: str | None = None
    verdict: ob.Verdict | None = None
    feedback_rounds = 0
    completions = 0
    analyses = 0
    nudged = False
    last_usage: dict = {}
    async with tool_session(faces.FACE_NAME_LEAD, session_id=session_id, user_id=user_id, message_id=message_id,
                            deny=deny) as lead_tools:
        ctx = specialist.TurnContext(open_tools=_open_tools, llm=llm, db_factory=db_factory, session_id=session_id,
                                     message_id=message_id, question=user_text, work=work)
        verbs = {t["name"] for t in lead_tools.tools}
        for _ in range(settings.lead_max_turns):
            work.budget = {"completions_used": completions, "completions_limit": settings.lead_max_turns,
                           "analyses_used": analyses, "analyses_limit": settings.lead_evidence_calls}
            tail = [llm_client.message("developer", work.tail_text())]
            turn = await llm.next(conv, instructions=instructions, tools=lead_tools.tools + [T.ASK_TOOL, T.OPEN_TOOL], tail=tail)
            work.mark_seen()
            completions += 1
            last_usage = turn.usage
            if turn.tool_calls:
                for call in turn.tool_calls:
                    try:
                        args = json.loads(call.arguments or "{}")
                    except json.JSONDecodeError:
                        args = None
                    if args is None:
                        result: dict = {"error": "malformed_arguments", "detail": "the arguments were not JSON"}
                    elif call.name == T.ASK_TOOL_NAME:
                        try:
                            asked = T.parse_tasks(args)
                        except T.BadAsk as exc:
                            result = {"error": "invalid_ask", "detail": str(exc)}
                        else:
                            got = await specialist.run_tasks(asked, ctx)
                            result = {"returns": [r.receipt() for r in got]}
                            async with db_factory() as db:
                                await wvm.save(db, work)
                                await db.commit()
                    elif call.name == T.OPEN_TOOL_NAME:
                        result = await opening.open_ref(db_factory, session_id, str(args.get("id") or ""),
                                                        offset=int(args.get("offset") or 0), work=work)
                    elif call.name in verbs:
                        if call.name == "analyze" and not args.get("scope"):
                            result = {"error": "scope_required",
                                      "detail": "say which subjects: {subjects: [...]} or {book, sector} or {book, holdings: 'all'}"}
                        elif call.name != "list" and analyses >= settings.lead_evidence_calls:
                            result = {"error": "budget_exhausted",
                                      "detail": "this turn's analyses are used; write the answer from what is on the record"}
                        else:
                            analyses += int(call.name != "list")
                            result = await lead_tools.call(call.name, args, actor="lead")
                            result = result if isinstance(result, dict) else {"error": "tool_transport_error"}
                            if call.name == "analyze" and isinstance(result.get("view"), str):
                                work.add_view(result, by="lead")
                                work.seen_views.add(result["view"])
                    else:
                        result = {"error": "unknown_tool", "detail": f"your tools are {', '.join(sorted(verbs))}, ask and open"}
                    conv.tool_output(call.call_id, ejson.dumps_capped(result, TOOL_RESULT_LIMIT, keep=("rows", "view")))
                continue
            text = (turn.text or "").strip()
            if not text:
                if nudged:
                    break
                nudged = True
                conv.say("developer", _WRITE_OR_ANALYZE)
                continue
            async with db_factory() as db:
                led = await ledger_svc.load(db, session_id)
            verdict = ob.observe(text, question=user_text, views=work.views, passages=led.passages)
            draft = text
            await _record_answer(db_factory, session_id, message_id, text, verdict)
            if verdict.ok or feedback_rounds >= settings.observer_feedback_rounds:
                break
            feedback_rounds += 1
            conv.say("developer", verdict.feedback() or "")

    async with db_factory() as db:
        led = await ledger_svc.load(db, session_id)
    if draft is not None and verdict is not None:
        rendered = rd.render(draft, verdict, work.views, led.by_id)
        reply_text = draft
        delivery = "answered" if verdict.ok else "answered_with_problems"
    else:
        rendered = {"blocks": [], "citations": [], "verified": {}, "validation": {}}
        reply_text = ""
        delivery = "not_answered"
    work.budget = {"completions_used": completions, "completions_limit": settings.lead_max_turns,
                   "analyses_used": analyses, "analyses_limit": settings.lead_evidence_calls}
    meta: dict = {
        "delivery": delivery,
        "completion": (verdict.completion if verdict is not None else {"status": "unknown", "requests": []}),
        "verified": rendered["verified"],
        "validation": rendered["validation"],
        "blocks": rendered["blocks"], "format": "blocks",
        "analyses": [{"view": v.get("view"), "by": v.get("by"), "measures": [r["measure"] for r in v.get("requests") or []],
                      "subjects": (v.get("scope") or {}).get("subjects"), "scope_status": (v.get("coverage") or {}).get("scope_status")}
                     for v in work.views],
        "tasks": [e.as_dict() for e in work.execution],
        "reports": [{"domain": n["analyst"], "task_id": n["task_id"], "report_id": n.get("report_id"),
                     "status": (work.status_of(n["task_id"]).status if work.status_of(n["task_id"]) else "returned"),
                     "title": f"the {n['analyst']} analyst"} for n in work.notes if n.get("report_id")],
        "work_view": work.id,
        "feedback_rounds": feedback_rounds, "completions": completions, "analyses_run": analyses,
        "prompt_tokens": last_usage.get("input_tokens"), "model": policy.model, "reasoning_effort": policy.reasoning_effort,
    }
    async with db_factory() as db:
        await wvm.save(db, work)
        db.add(AgentMessage(id=message_id, session_id=session_id, role="assistant", content=reply_text,
                            citations=rendered["citations"], meta=meta))
        if last_usage.get("input_tokens") is not None:
            await db.execute(update(AgentSession).where(AgentSession.id == session_id)
                             .values(last_prompt_tokens=last_usage["input_tokens"]))
        await db.commit()
    return {"session_id": session_id, "message_id": message_id, "text": reply_text,
            "citations": rendered["citations"], "meta": meta}

