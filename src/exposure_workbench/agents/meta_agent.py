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

from exposure_workbench.agents import delegation, repeats as rp, sub_analyst
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
from the ROSTER the analyst whose question this is, name the subjects from the BRIEFING — or a book an analyst built this turn, by the id under `made` — and write \
what you want to know as short, separate lines, one thing per line, in your own words. Say the arithmetic you want worked out rather \
than doing it yourself, and say how it must be compared where the question has a comparison. Several domains may be \
needed for one question: send them in one call. Ask again only for what the answer still lacks. Never name a measure, \
a program or a fact id — that is the analyst's job and the reason you have one. Check the question's premises against \
the BRIEFING first (which holdings are in which sector, what the desk holds).

Each analyst comes back under a `<analysts>` tag, and every part of it is named: `coverage` counts the lines it \
settled, `findings` holds one finding per line it settled, `not_done` says what stopped each line it could not — with the \
desk's own words for it beside the line as `said`, under an id — `refused` names a line whose figures did not pass \
the desk's check, `caveats` say where a finding is not quite the line you asked (readings on other dates, another \
spacing, a proxy in place of the thing you named), `follow_ups` are what it would ask next, `made` is a book it built \
this turn, `shown` appears only when it filed nothing and lists the figures it was shown anyway, and `status` and \
`report_id` say how it ended and where its full reading is. A CAVEAT BELONGS BESIDE THE FIGURE IT QUALIFIES: a \
finding stated without its caveat is not what the analyst found, and saying so is not a hedge — it is the reading. \
Your reply is plain prose, and every number you write is one an analyst showed you, written exactly \
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

# THE TWO BLOCKS PUSHED TO THE LEAD (V37/A3). Each was a one-line heading over raw
# JSON, which leaves the reading of a block to the field names inside it — and a
# field nobody is told about is a field nobody reads (delegation.FOR_THE_LEAD_TO_
# READ). A tag with `source` and `use` is what the current prompting guidance asks
# for when one prompt mixes instructions, context and variable input, which this
# one does. Named rather than inlined so the wording sheet reads the same object
# the turn sends (scripts/v36_wording.py), and so a reviewer has one thing to read.
BRIEFING_TAG = ('<briefing source="the desk\'s catalogue" trust="names, dates and coverage only — no figure here may '
                'be stated until an analyst returns it" use="pick the subjects; check the question\'s premises">')
ROSTER_TAG = ('<roster source="the desk\'s own knowledge, by domain" use="pick the analyst by what you need to know, '
              'not by the words of the question; each entry says what it can be asked for and what is absent there">')

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


async def _record_bad_delegate(db_factory, session_id: str, message_id: str, args, detail: str) -> None:
    """A delegation the protocol refused, as a rejected step. Round A had three
    of these on the first completion of a turn and the trace showed a completion
    with one tool call and nothing after it (V36.1)."""
    try:
        async with db_factory() as db:
            await trace_service.record_step(
                db, session_id, step_type="delegate", tool_name="delegate",
                args={"raw": ejson.dumps_capped(args, 2000)}, evidence_refs=[],
                result_summary=f"invalid_delegation: {detail[:300]}", status="rejected", message_id=message_id)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record the rejected delegate step for %s", session_id)


async def _record_read_report(db_factory, session_id: str, message_id: str, report_id: str, result: dict) -> None:
    """The lead opening a report, as a step: the one edge of round A's table
    that had to be inferred from a 26-token completion (V36.1)."""
    try:
        async with db_factory() as db:
            await trace_service.record_step(
                db, session_id, step_type="read_report", tool_name="read_report",
                args={"report_id": report_id}, evidence_refs=[],
                result_summary=(f"{result.get('error')}: {str(result.get('detail') or '')[:160]}" if result.get("error")
                                else f"{result.get('status')}: {str(result.get('title') or '')[:120]}"
                                     f" · {len(str(result.get('text') or ''))} chars"),
                status="rejected" if result.get("error") else "completed", message_id=message_id)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record the read_report step for %s", session_id)


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
    # EVERY BLOCK SAYS WHAT IT IS, WHO IT CAME FROM AND WHAT TO DO WITH IT
    # (V37/A3). Each was a one-line heading over raw JSON, which leaves the
    # reading of a block to the field names inside it — and a field nobody is told
    # about is a field nobody reads (see delegation.FOR_THE_LEAD_TO_READ). A tag
    # with `source` and `use` is what the current prompting guidance asks for when
    # one prompt mixes instructions, context and variable input, which this one
    # does; no template engine, because the thing to fix is what is said about a
    # block, not how the string is built.
    messages: list[dict] = [{"role": "system", "content": _SYSTEM},
                            {"role": "system", "content":
                             BRIEFING_TAG + "\n" + json.dumps(brief, ensure_ascii=False, default=str)
                             + "\n</briefing>"}]
    # WHO CAN BE ASKED WHAT. Not the desk's knowledge — that is each domain
    # analyst's, and handing the lead the vocabulary is what let V35's analyst
    # write requests in a language it did not have to answer for. Ordered by the
    # lexical match so the two domains the question is most likely about are
    # read first; the other twelve still follow, because a question the match
    # scores badly is exactly the one whose domain has to be found by reading.
    roster = skill.roster(user_text if get_settings().push_domains else None)
    messages.append({"role": "system", "content":
                     ROSTER_TAG + "\n" + json.dumps(roster, ensure_ascii=False) + "\n</roster>"})
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
        # A REPLY RE-SENT UNCHANGED IS NOT A SECOND ATTEMPT (V37/A2, the V31 rule
        # this loop never had). Given the same prose and the same ledger the check
        # returns the same refusal, and it cost one of the two attempts to hear it
        # again: round B's Q03 and Q18 each sent their answer twice, word for word,
        # and ended on the gate-exhausted text. The first repeat is told it
        # repeated itself, with the tokens the check named; the second ends the
        # turn, because a third identical payload has never once been the one that
        # passed. A reply that changed by one byte goes out however many times it
        # is sent — the bound is on repetition, never on effort.
        repeated = rp.Repeats()
        read = {"chars": 0, "results": 0}          # what the next completion reads (V36.1, recorded on its row)

        def _append(msg: dict) -> None:
            messages.append(msg)
            read["chars"] += len(str(msg.get("content") or ""))
            read["results"] += int(msg.get("role") == "tool")

        for _turn in range(max_turns):
            # while a verdict stands the turn is a tool call: a repair or a delegation
            tools = ([delegation.DELEGATE_TOOL]
                     + ([delegation.READ_REPORT_TOOL] if delegated else [])
                     + ([REPAIR_TOOL] if standing is not None else []))
            prompt_peak = max(prompt_peak, context_budget.count_prompt(messages, tools))
            content, tool_calls = await llm.chat(messages=messages, tools=tools,
                                                 note=({"read": dict(read)} if read["chars"] else None),
                                                 **({"tool_choice": "required"} if standing is not None else {}))
            read = {"chars": 0, "results": 0}
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
                            await _record_bad_delegate(db_factory, session_id, message_id, args, str(exc))
                        else:
                            await _record_delegate(db_factory, session_id, message_id, tasks)
                            got = await sub_analyst.run_tasks(tasks, ctx)
                            delegated += got
                            result = delegation.for_lead(got)
                    elif name == delegation.READ_REPORT_TOOL_NAME:
                        rid = str((args or {}).get("report_id") or "")
                        result = await _read_report(db_factory, session_id, rid)
                        await _record_read_report(db_factory, session_id, message_id, rid, result)
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
                            again = repeated.record({"text": text})
                            if again > rp.STOP:
                                gate_refusals.append("repeated_answer")
                                answer, standing = text, verdict
                                break
                            if again < rp.STOP:
                                # a repeat earns no attempt and logs no second
                                # refusal: it is the same refusal, already logged
                                attempts += 1
                                gate_refusals.append(verdict.error)
                            answer, standing = text, verdict
                            result = {"accepted": False, "refusal": _refusal_message(verdict),
                                      **({"repeated": rp.nudge("your reply", verdict.as_refusal())} if again == rp.STOP else {}),
                                      **({"tags_not_among_the_failed": unknown} if unknown else {})}
                    elif name == REPAIR_TOOL_NAME:
                        result = {"error": "nothing_to_repair", "detail": "no verdict stands on a reply; write the answer"}
                    else:
                        result = {"error": "unknown_tool",
                                  "detail": f"your tools are {delegation.DELEGATE_TOOL_NAME} and {REPAIR_TOOL_NAME}; "
                                            f"the answer is your reply text"}
                    # A TOOL RESULT KEEPS ITS OWN SHAPE. The two system blocks are
                    # prose and take a tag; this is JSON, and the thing that says
                    # what to do with it is a field IN it — `how_to_cite`, which
                    # E10 has carried since V36 and which now names `caveats` and
                    # `shown`. Wrapping it in a tag would make every reader of a
                    # tool result unwrap one, to say what the payload can say.
                    _append({"role": "tool", "tool_call_id": tc["id"],
                             "content": ejson.dumps_capped(result, TOOL_RESULT_LIMIT)})
                if reply_text is not None or attempts >= MAX_ANSWER_ATTEMPTS:
                    break
                continue

            text = (content or "").strip()
            if not text:
                _append({"role": "user", "content": _WRITE_OR_ASK})
                continue

            if standing is not None:
                # a new reply while a verdict stands is not read: the repair is the
                # tool, and a provider that ignores tool_choice is told so once
                nudges += 1
                if nudges > 1:
                    gate_refusals.append("malformed_repair")
                    break
                _append({"role": "user", "content": _REPAIR_ONLY})
                continue
            led = await _load_ledger(db_factory, session_id)
            verdict = answer_check.check(text, led, question=user_text)
            await _record_answer(db_factory, session_id, message_id, text, verdict)
            if verdict.ok:
                acc = answer_check.accepted(text, verdict, led)
                reply_text, reply_citations = acc["text"], acc["citations"]
                reply_verified, reply_blocks = acc["verified"], acc["blocks"]
                break
            again = repeated.record({"text": text})
            if again > rp.STOP:
                gate_refusals.append("repeated_answer")
                break
            if again < rp.STOP:
                attempts += 1
                gate_refusals.append(verdict.error)
            if attempts >= MAX_ANSWER_ATTEMPTS:
                break
            answer, standing = text, verdict
            _append({"role": "user", "content": _refusal_message(verdict)
                     + (f"\n\n{rp.nudge('your reply', verdict.as_refusal())}" if again == rp.STOP else "")})

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
