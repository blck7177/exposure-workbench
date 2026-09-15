"""The lead analyst (V36) — the single conversational entity the user talks to.

Three jobs have shared this loop over three versions. V33 took the transcription
out of it (the program, the claims list, the ids); V36 takes out the last one
that was never its own — deciding, in the desk's language, what would settle the
question. That belonged to nobody: the loop was a generalist, the domain
knowledge was pushed to it as text, and the compiler behind it read fields. Round
J's Q11 asked for "room to warning and breach" in a field the compiler did not
read, subtracted the room in prose, and was refused for it, twice.

So the lead decides and writes, and the desk's domain analysts do the rest:

    read : the role and one rule; the BRIEFING (the desk's map for the subjects
           the question names — names, dates, coverage, never a figure); the
           ROSTER (which analyst can be asked what); the briefs that come back
    write: delegate(tasks) — subjects and numbered lines of what it wants to
           know, in its own words; then prose

agents/sub_analyst runs each domain analyst INSIDE this turn, on the same
session and the same tool-face token, so everything they fetch is on the ledger
the answer check reads. agents/delegation holds the protocol and the check at
the boundary: a brief reaches this loop only if every line is accounted for and
every figure in it points at a fact. The answer check (services/answer_check)
then reads the prose against that ledger and refuses with every problem at once;
the lead gets one rewrite. Nothing reaches the user that the check did not
accept.

History is persisted as agent_messages so a session survives across turns.
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from sqlalchemy import update

from exposure_workbench.agents import delegation, sub_analyst
from exposure_workbench.agents.llm_session import llm_session
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.analytics import skill
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import AgentMessage, AgentSession
from exposure_workbench.services import analyst_reports, answer_check, briefing as briefing_svc, context_budget, \
    ledger as ledger_svc, trace_service
from exposure_workbench.tools import faces
from exposure_workbench.utils import json as ejson
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

_SYSTEM = """You are the lead analyst for a portfolio risk & issuer-intelligence desk. The analysis is your job: take \
the question apart, decide what has to be known to answer it, ask the desk's domain analysts for it, and say what it \
shows and what it means for the question asked — its implication for this book and what would change your reading.

You compute and fetch nothing yourself, and you do not speak the desk's language. delegate(tasks) is how you ask: pick \
from the ROSTER the analyst whose question this is, name the subjects from the BRIEFING, and write what you want to \
know as short, separate lines, one thing per line, in your own words. Say the arithmetic you want worked out rather \
than doing it yourself, and say how it must be compared where the question has a comparison. Several domains may be \
needed for one question: send them in one call. Ask again only for what the answer still lacks. Never name a measure, \
a program or a fact id — that is the analyst's job and the reason you have one. Check the question's premises against \
the BRIEFING first (which holdings are in which sector, what the desk holds).

Each analyst comes back with a finding for each of your lines, what it could not do — with the desk's own words \
for it beside the line as `said`, under an id — and a report id. Your reply is plain prose, and every number you write is one an analyst showed you, written exactly \
as it was shown, bracket included: 16.0% [f_2592baab170e]. The bracket is the desk's id for that reading; it is what \
lets the reader open the figure, and a figure written without it is refused. A table or a chart is [table: <node>] or \
[chart: <node>], naming a node from the evidence. Quotation marks are for text that came to you under an id: a passage's words, or \
the desk's own words for what it could not do — the `said` beside a not_done line, the `desk_said` beside a finding — \
cited with that id. An analyst's own sentences are not the desk's words: say what they say in yours, without \
quotation marks. A superlative rests on an ordering the desk computed. What the desk could not \
do or does not hold, say so and say what you gave instead — never an estimate, never a figure carried from one company \
or date to another, never a nearby figure under the asked-for name.

If your reply is not accepted, you are told which sentences did not pass and why. Call repair_answer with a replacement \
for exactly those sentences (an empty replacement drops one); delegate first if a fix needs a figure you were not \
shown. You have two attempts."""


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

# The lead's own tools. Kept as a tuple for the tests that pin the budget-free
# names: not one of them retrieves anything — `delegate` hands work to an
# analyst whose evidence calls are charged where they happen.
_BUDGET_FREE_TOOLS = (delegation.DELEGATE_TOOL_NAME, delegation.READ_REPORT_TOOL_NAME, "repair_answer")

_WRITE_OR_ASK = "Write the answer, or delegate for the evidence you still need."

# C — THE REPAIR IS A TOOL. Round G: 18 refused replies got a second chance, one
# used the tagged-lines protocol, four re-sent the refused text byte for byte and
# thirteen rewrote the whole reply; a whole-reply rewrite was "still allowed" and
# so was the path every model took. While a verdict stands, the analyst's turn is
# a tool call by construction (tool_choice=required): replacements for the
# sentences that failed, or an evidence request.
REPAIR_TOOL_NAME = "repair_answer"
REPAIR_TOOL = {"type": "function", "function": {
    "name": REPAIR_TOOL_NAME,
    "description": ("Replace the sentences of your reply that did not pass, by tag. Every other sentence is kept exactly "
                    "as you wrote it. An empty text drops the sentence. Request evidence first if a fix needs a figure "
                    "you were not shown."),
    "parameters": {"type": "object", "properties": {
        "replacements": {"type": "array", "minItems": 1, "items": {
            "type": "object", "properties": {"tag": {"type": "string", "description": "S1, S2, …"},
                                             "text": {"type": "string", "description": "the sentence as it should read; empty drops it"}},
            "required": ["tag", "text"], "additionalProperties": False}}},
        "required": ["replacements"], "additionalProperties": False}}}
_REPAIR_ONLY = ("A verdict stands on your reply: call repair_answer with replacements for the sentences named, "
                "or delegate for what a fix needs. A new reply is not read.")


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


async def _read_report(db_factory, session_id: str, report_id: str) -> dict:
    """A domain analyst's full reading, when the brief was not enough.

    The figures in it are already on this session's ledger — the check read them
    there before it was stored — so the lead may copy them exactly as it copies
    a finding's. A refused report comes back as its problems, not its prose:
    quoting unchecked analysis is the thing the store exists to prevent."""
    if not report_id:
        return {"error": "no_report_id", "detail": "read_report takes the report_id a delegate result gave you"}
    try:
        async with db_factory() as db:
            rep = await analyst_reports.load(db, session_id, report_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not read report %s", report_id)
        return {"error": "report_unavailable", "detail": "the desk could not open that report"}
    if rep is None:
        return {"error": "unknown_report",
                "detail": f"{report_id} is not a report from this conversation; the ids are in the delegate results"}
    if rep["status"] != "verified":
        return {"domain": rep["domain"], "status": rep["status"], "title": rep["title"],
                "detail": "this report did not pass the check; it is on the record but it is not yours to quote",
                "problems": [p.get("reason") for p in rep["problems"][:6]]}
    return {"domain": rep["domain"], "status": rep["status"], "title": rep["title"],
            "text": rep["text"], "citations": rep["citations"]}


async def _record_delegate(db_factory, session_id: str, message_id: str, tasks) -> None:
    """The lead's half of the handoff, as a step. The analysts record their own;
    without this one the trace shows work appearing with nobody having asked."""
    try:
        async with db_factory() as db:
            await trace_service.record_step(
                db, session_id, step_type="delegate", tool_name="delegate",
                args={"tasks": [t.as_dict() for t in tasks]}, evidence_refs=[],
                result_summary="; ".join(f"{t.domain} [{','.join(t.subjects)}] {len(t.want_to_know)} line(s)"
                                         for t in tasks),
                message_id=message_id)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record delegate step for %s", session_id)


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
    """C — SENTENCE REPAIR. Only the sentences that did not pass come back, and
    only replacements for them are asked for; everything else is kept exactly as
    written. A whole-reply rewrite re-rolled every sentence, and 17 of 20
    questions spent both attempts without landing (V33F). The replacements come
    through repair_answer, a tool: round G showed a text protocol is not one."""
    failed = verdict.failed
    lines = [f"{len(failed)} sentence(s) of your reply did not pass. Everything else is KEPT exactly as you wrote it.",
             "", "Replace only these:"]
    for x in failed:
        lines.append(f"[{x['tag']}] {x['text']}")
        for p in x["problems"][:6]:
            what = p.get("figure") or p.get("node") or p.get("quote") or p.get("word") or p.get("phrase") or ""
            line = f"      {p['reason']}" + (f" ({what!r})" if what else "")
            if p.get("fix"):
                line += f": {p['fix']}"
            if p.get("candidates"):
                line += " — the desk showed: " + "; ".join(
                    f"{c.get('measure')} {c.get('subject')} {c.get('as_of')} [{c.get('id')}]" for c in p["candidates"][:4])
            lines.append(line)
    other = [p for p in verdict.problems if not p.get("sentence")]
    for p in other[:6]:
        lines.append(f"      {p['reason']}: {p.get('fix') or p.get('detail') or ''}")
    lines += ["", "Call repair_answer with a replacement for each tag above (an empty text drops the sentence). "
                  "Delegate for the evidence you lack first if a fix needs a figure you were not shown."]
    return "\n".join(lines)


def _parse_replacements(args: dict, verdict) -> tuple[dict[str, str], list[str]]:
    """({tag: text} for the failed sentences named, tags that name no failed sentence)."""
    failed = {x["tag"] for x in verdict.failed}
    out: dict[str, str] = {}
    unknown: list[str] = []
    for r in (args or {}).get("replacements") or []:
        if not isinstance(r, dict):
            continue
        tag = str(r.get("tag") or "").strip().upper()
        if tag in failed:
            out[tag] = str(r.get("text") or "")
        elif tag:
            unknown.append(tag)
    return out, unknown


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
    # WHO CAN BE ASKED WHAT. Not the desk's knowledge — that is each domain
    # analyst's, and handing the lead the vocabulary is what let V35's analyst
    # write requests in a language it did not have to answer for. Ordered by the
    # lexical match so the two domains the question is most likely about are
    # read first; the other twelve still follow, because a question the match
    # scores badly is exactly the one whose domain has to be found by reading.
    roster = skill.roster(user_text if get_settings().push_domains else None)
    messages.append({"role": "system", "content":
                     "ROSTER — the desk's domain analysts: what each one can be asked for, and what is absent there. "
                     "Pick by what you need to know, not by the words of the question:\n"
                     + json.dumps(roster, ensure_ascii=False)})
    messages += history

    reply_text, reply_citations = None, []
    reply_verified: dict | None = None
    reply_blocks: list | None = None
    gate_refusals: list[str] = []
    prompt_peak = 0
    attempts = 0
    completions = 0
    delegated: list = []                   # every AnalystResult this turn produced
    answer, standing = "", None            # the reply being repaired, and the verdict naming its sentences

    async with tool_session(
        faces.FACE_NAME_META, session_id=session_id,
        user_id=current_user_id(), message_id=message_id, deny=deny,
    ) as tools_session, llm_session(db_factory, session_id, message_id) as llm:
        ctx = sub_analyst.TurnContext(tools_session=tools_session, llm=llm, db_factory=db_factory,
                                      session_id=session_id, message_id=message_id, briefing=brief)
        domains = {d["domain"] for d in roster}

        nudges = 0
        for _turn in range(max_turns):
            # while a verdict stands the turn is a tool call: a repair or a delegation
            tools = ([delegation.DELEGATE_TOOL]
                     + ([delegation.READ_REPORT_TOOL] if delegated else [])
                     + ([REPAIR_TOOL] if standing is not None else []))
            prompt_peak = max(prompt_peak, context_budget.count_prompt(messages, tools))
            content, tool_calls = await llm.chat(messages=messages, tools=tools,
                                                 **({"tool_choice": "required"} if standing is not None else {}))
            completions += 1
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
                    if name == delegation.DELEGATE_TOOL_NAME:
                        try:
                            tasks = delegation.parse_tasks(args, domains, new_id)
                        except delegation.BadDelegation as exc:
                            result: dict = {"error": "invalid_delegation", "detail": str(exc)}
                        else:
                            await _record_delegate(db_factory, session_id, message_id, tasks)
                            got = await sub_analyst.run_tasks(tasks, ctx)
                            delegated += got
                            result = delegation.for_lead(got)
                    elif name == delegation.READ_REPORT_TOOL_NAME:
                        result = await _read_report(db_factory, session_id,
                                                    str((args or {}).get("report_id") or ""))
                    elif name == REPAIR_TOOL_NAME and standing is not None:
                        repl, unknown = _parse_replacements(args, standing)
                        led = await _load_ledger(db_factory, session_id)
                        text = answer_check.repair(answer, standing, repl) if repl else answer
                        verdict = answer_check.check(text, led, question=user_text)
                        await _record_answer(db_factory, session_id, message_id, text, verdict)
                        if verdict.ok:
                            acc = answer_check.accepted(text, verdict, led)
                            reply_text, reply_citations = acc["text"], acc["citations"]
                            reply_verified, reply_blocks = acc["verified"], acc["blocks"]
                            result = {"accepted": True}
                        else:
                            attempts += 1
                            gate_refusals.append(verdict.error)
                            answer, standing = text, verdict
                            result = {"accepted": False, "refusal": _refusal_message(verdict),
                                      **({"tags_not_among_the_failed": unknown} if unknown else {})}
                    elif name == REPAIR_TOOL_NAME:
                        result = {"error": "nothing_to_repair", "detail": "no verdict stands on a reply; write the answer"}
                    else:
                        result = {"error": "unknown_tool",
                                  "detail": f"your tools are {delegation.DELEGATE_TOOL_NAME} and {REPAIR_TOOL_NAME}; "
                                            f"the answer is your reply text"}
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": ejson.dumps_capped(result, TOOL_RESULT_LIMIT)})
                if reply_text is not None or attempts >= MAX_ANSWER_ATTEMPTS:
                    break
                continue

            text = (content or "").strip()
            if not text:
                messages.append({"role": "user", "content": _WRITE_OR_ASK})
                continue

            if standing is not None:
                # a new reply while a verdict stands is not read: the repair is the
                # tool, and a provider that ignores tool_choice is told so once
                nudges += 1
                if nudges > 1:
                    gate_refusals.append("malformed_repair")
                    break
                messages.append({"role": "user", "content": _REPAIR_ONLY})
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
            answer, standing = text, verdict
            messages.append({"role": "user", "content": _refusal_message(verdict)})

    meta: dict = {"prompt_tokens": prompt_peak, "completions": completions,
                  "delegations": [{"domain": r.task.domain, "task_id": r.task.task_id, "status": r.status,
                                   "coverage": r.coverage, "cost": r.cost} for r in delegated],
                  "reports": [{"domain": r.task.domain, "report_id": r.report_id,
                               "status": (r.report or {}).get("status", r.status),
                               "title": (r.report or {}).get("title")}
                              for r in delegated if r.report_id],
                  "briefing_subjects": brief.get("subjects") if isinstance(brief, dict) else None}
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
