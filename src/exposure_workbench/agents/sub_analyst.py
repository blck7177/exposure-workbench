"""An analyst of the desk (V1) — one resource family, one task, inside the lead's turn.

There are three: the issuer analyst (filings), the market analyst (prices) and
the portfolio risk manager (the book). Each is handed a task in the lead's own
words and comes back with an entry for every numbered line of it.

    knows  four things, all given before it starts: what its family of data is
           and what the desk holds for the task's subjects; the task; its tools —
           the list itself, each verb saying what it does; and its chapter of the
           handbook (analytics/handbook), which says what a measure is, how it
           reads, what to set against what and what the desk does not say
    does   pulls rows with its own face's verbs (tools/primitives), every call
           saying WHY; then `submit` — settled with the ids, or not settled with
           the boundary's id
    never  a program, a number worked out in its head, a sentence a reader sees.
           The lead writes the answer.

WHY THE FACE IS ITS OWN SESSION. Until V1 every domain analyst borrowed the
lead's tool session and all fourteen held the same four tools; what kept a
filings question away from the book was a sentence. Now an analyst opens the
mount of its own face (tools/faces.ANALYST_FACES), and another family's verb is
not in its list to be called.

WHY IT RUNS INSIDE THE LEAD'S TURN. Same session, same message (D3, V36). That is
what puts its rows on the ledger the answer check reads: an analyst in a session
of its own would leave the lead unable to cite anything it pulled.

THE LOG IS ITS CALLS. Each call's `why` is recorded with the call, so what it
did and why is read off the trace; `delegation.log_text` renders it for the lead
and for the record. Nobody writes a report.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from exposure_workbench.agents import delegation as dl, delivery, repeats as rp
from exposure_workbench.analytics import handbook, registry
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.services import analysis_state as AS, analyst_reports, answer_check, fact_adapters as fa, facts as F, \
    ledger as ledger_svc, style_guide, trace_service
from exposure_workbench.tools import faces
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

# `start` is on the face and reachable, and is counted apart (V36.1): it returns a
# task id, never a row. Every other verb is an evidence call.
LIST_TOOL = "list"
START_TOOL = "start"

# what the row says when a task's evidence calls are used (the row is the boundary of
# every line the analyst did not reach)
_BUDGET_STOP = "this task's {n} evidence calls are used; what was not read by then was not reached"

_SYSTEM = """You are {title} of a portfolio risk & issuer-intelligence desk. One task from the desk's lead analyst is in \
front of you: numbered lines of what it wants to know about the subjects it names. Settle each line from your own family of \
evidence, and file a brief that answers the task line by line.

Your tools are verbs over that evidence: see what the desk holds, read one thing, take a measure by its name, do one \
operation on figures you were already shown. Every call says WHY — which line it serves and why this verb; your log is made \
of those sentences, and it is the only record of your reading. Every result is rows. A row says what it is, whose, over \
what period, the value, what it means, and where it came from, under the id you cite it by. A refusal is a row too: it says \
why, and the way out where there is one.

The brief is one entry per numbered line, and an entry is one of two things. Settled: one to three sentences, written to \
the desk's style guide below, with the ids of the rows they rest on. Not settled: why, in a line of your own, and the id of \
the absence row that says so — a tool's refusal, or one of the desk's standing policies: {policies}. Never both, never \
neither.

You write for the lead analyst, never for the reader, and you answer the task you were given rather than the one you would \
have asked. If your brief is refused you are told which entries and why: submit again with those replaced, pulling the row a \
fix needs first if you were not shown it."""

_WRITE_OR_ASK = "File your brief with submit, or pull the rows you still need."

# THE TWO BLOCKS HANDED TO AN ANALYST, each saying what it is, where it came from
# and what to do with it (V37/A3) — named, so the wording sheet reads the object
# the turn sends.
TASK_TAG = ('<task source="the desk\'s lead analyst" use="settle every numbered line, or say what stopped it">')
COVERAGE_TAG = ('<coverage source="the desk\'s catalogue" trust="names, dates and coverage only — no figure here" '
                'use="what the desk holds for the task\'s subjects, and up to when">')
# V2 P2.3 (design v0.4 §07, G4): what the task this one follows up left on the record —
# the entries that passed every check, with the desk's rows under them, and what stopped
# the rest. Nothing refused is here, and nothing here is read again by a tool.
PRIOR_TAG = ('<prior source="the desk\'s record of the task this one follows up" use="what that task settled, with '
             'its rows, and what stopped the rest; ask for what is still missing rather than pulling these again">')

_TITLES = {c.analyst: c.title[0].lower() + c.title[1:] for c in handbook.CHAPTERS.values()}
_POLICIES = "; ".join(f"{p['id']} ({p['measure'].split('.', 1)[1].replace('_', ' ')})" for p in registry.POLICY_ABSENCES)


def system_text(analyst: str) -> str:
    """One analyst's standing text: its role, the desk's style guide — once, from
    the one place its rules are written (services/style_guide) — then its chapter
    of the handbook."""
    return (_SYSTEM.format(title=_TITLES[analyst], policies=_POLICIES)
            + "\n\n" + style_guide.text()
            + "\n\nYOUR CHAPTER OF THE DESK'S HANDBOOK\n" + handbook.chapter_text(analyst))


@dataclass
class TurnContext:
    """What one turn holds and every analyst in it shares (D3)."""
    open_tools: Callable[[str], Any]     # face name -> an async context manager yielding a tool session
    llm: object                          # agents.llm_session.LlmSession
    db_factory: object
    session_id: str
    message_id: str | None
    briefing: dict = field(default_factory=dict)
    state_version: int | None = None        # V2 P2: the analysis state the task was cut from, for input_version
    question: str = ""


def _coverage_of(task: dl.Task, briefing: dict) -> dict:
    """The desk's map for this task's subjects only."""
    issuers, ports = briefing.get("issuers") or {}, briefing.get("portfolios") or {}
    out: dict = {}
    for s in task.subjects:
        d = issuers.get(s) or issuers.get(s.upper()) or ports.get(s)
        if d is not None:
            out[s] = d
        elif s.startswith("calc_"):
            # a book another analyst built this turn: not in the briefing, because
            # it did not exist when the briefing was written
            out[s] = {"kind": "a book a scenario built this turn: it is read where a book's id goes"}
    return out


def _face_tools(tools_session, analyst: str) -> list[dict]:
    by_name = {t["function"]["name"]: t for t in getattr(tools_session, "tools", []) or []}
    return [by_name[n] for n in faces.ANALYST_FACES[analyst] if n in by_name]


async def _record(ctx: TurnContext, actor: str, step_type: str, tool_name: str | None, args: dict,
                  summary: str, facts: list | None = None, status: str = "completed",
                  task_id: str | None = None) -> None:
    try:
        async with ctx.db_factory() as db:
            step_id = await trace_service.record_step(
                db, ctx.session_id, step_type=step_type, tool_name=tool_name, args=args,
                result_summary=summary, status=status, message_id=ctx.message_id, actor=actor,
                task_id=task_id, evidence_refs=[ledger_svc.step_entry(facts)] if facts else [])
            for row in ledger_svc.rows_for(facts or [], session_id=ctx.session_id, step_id=step_id,
                                           message_id=ctx.message_id):
                db.add(row)
            await db.commit()
    except Exception:  # noqa: BLE001 — a hole in the audit trail beats a lost turn
        logger.exception("could not record %s step for session %s", step_type, ctx.session_id)


async def _ledger(ctx: TurnContext):
    async with ctx.db_factory() as db:
        return await ledger_svc.load(db, ctx.session_id)


_asked = dl.asked_of


def _got(res: dict) -> str:
    """What came back, in the words the trace uses for the same call (fact_adapters.came_back), so
    the log an analyst keeps and the log rebuilt from `agent_steps` are one text."""
    if isinstance(res.get("head"), str):
        return dl.got_of(fa.came_back(res, []))
    return (f"{res.get('error')}" + (f": {str(res['detail'])[:120]}" if res.get("detail") else "")) if res.get("error") else "done"


async def _prior_block(task: dl.Task, ctx: TurnContext) -> str:
    """The `<prior>` block for a follow-up (V2 P2.3): the record of `task.follow_up_of`
    as TaskState kept it — accepted lines with their rows read off the ledger, and the
    unsettled lines with their boundary rows. A task of another session, or one that
    left no record, gives an empty string; a refused entry is never here (A3)."""
    if not task.follow_up_of:
        return ""
    try:
        async with ctx.db_factory() as db:
            rep = await analyst_reports.load_by_task(db, ctx.session_id, task.follow_up_of)
    except Exception:  # noqa: BLE001 — a follow-up without its record is a task like any other
        logger.exception("could not read the record of %s", task.follow_up_of)
        return ""
    if not rep:
        return ""
    led = await _ledger(ctx)
    scope = AS.scope_of(ctx.briefing, ctx.question)
    settled, not_settled = [], []
    for e in rep.get("accepted_lines") or []:
        refs = (e.get("facts") or []) if e.get("settled") else [e.get("boundary")]
        text = e.get("finding") if e.get("settled") else e.get("why")
        if not AS.reusable(text or "", refs, e.get("validation"), scope, led, ctx.question,
                           channel="finding" if e.get("settled") else "why"):
            continue
        if e.get("settled"):
            settled.append({"n": e.get("n"), "finding": e.get("finding"),
                            "rows": [F.line(led.by_id[fid]) for fid in e.get("facts") or [] if fid in led.by_id]})
        else:
            b = e.get("boundary")
            not_settled.append({"n": e.get("n"), "why": e.get("why"),
                                "boundary": F.line(led.by_id[b]) if b in led.by_id else b})
    if not settled and not not_settled:
        return ""
    prior = {"task_id": task.follow_up_of, "settled": settled, "not_settled": not_settled}
    return "\n" + PRIOR_TAG + "\n" + json.dumps(prior, ensure_ascii=False, default=str) + "\n</prior>"


async def run_sub_analyst(task: dl.Task, ctx: TurnContext) -> dl.AnalystResult:
    """One analyst, start to brief, on its own face."""
    async with ctx.open_tools(task.analyst) as tools_session:
        return await _run(task, ctx, tools_session)


async def _run(task: dl.Task, ctx: TurnContext, tools_session) -> dl.AnalystResult:
    settings = get_settings()
    actor = f"sub:{task.analyst}"
    result = dl.AnalystResult(task=task)
    evidence_calls = start_calls = completions = 0
    budget_stop = None
    started: dict[tuple[str, str], str] = {}            # (kind, subject) -> the task it enqueued
    llm = ctx.llm.for_actor(actor) if hasattr(ctx.llm, "for_actor") else ctx.llm

    messages: list[dict] = [
        {"role": "system", "content": system_text(task.analyst)},
        {"role": "user", "content":
         TASK_TAG + "\n" + json.dumps(task.as_dict(), ensure_ascii=False, default=str) + "\n</task>\n"
         + COVERAGE_TAG + "\n" + json.dumps(_coverage_of(task, ctx.briefing), ensure_ascii=False, default=str)
         + "\n</coverage>" + await _prior_block(task, ctx)},
    ]
    face = _face_tools(tools_session, task.analyst)
    verbs = [t["function"]["name"] for t in face]
    tools = face + [dl.SUBMIT_TOOL]
    standing: dl.HandoffVerdict | None = None           # a verdict on a brief, awaiting its replacement
    kept_brief: dict | None = None                       # what that verdict kept (V2 P1.2: the patch contract)
    attempts = nudges = 0
    read = delivery.Delivered()                         # what the next completion reads, and the ids in it (V36.1, V2 P2)
    # A CALL RE-SENT UNCHANGED IS NOT A SECOND TRY (V37/A2, the V31 rule). The same
    # call gets the same rows, and it cost a slot of the analyst's evidence calls
    # to read them again. The repeat is answered from what the desk already said,
    # told that it repeated itself, and NOT charged. One byte's difference — the
    # `why` aside — is a new call.
    sent = rp.Repeats()
    last: dict[str, dict] = {}                         # call digest -> the result it got

    def _append(msg: dict) -> None:
        messages.append(msg)
        read.add(msg)

    for _turn in range(settings.sub_analyst_max_turns):
        read.project(messages)
        content, tool_calls = await llm.chat(
            messages=messages, tools=tools, note=read.note(),
            **({"tool_choice": "required"} if standing is not None else {}))
        read.reset()
        completions += 1
        msg: dict = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)

        if not tool_calls:
            nudges += 1
            if nudges > 2:
                break
            _append({"role": "user", "content": _WRITE_OR_ASK})
            continue

        done = False
        # ONE COMPLETION'S READING IS BOUNDED (V37/T5): the budget is the completion's,
        # shared by the results it will read, with a floor so one call is never starved.
        room = max(4_000, settings.sub_analyst_result_chars // max(1, len(tool_calls)))
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == START_TOOL and name in verbs:
                # A START IS NOT EVIDENCE. It enqueues work that finishes after the
                # turn and returns an id, never a row — counted apart, and once per
                # subject: the same start twice is the same task.
                key = (str(args.get("kind") or ""), str(args.get("subject") or "").upper())
                if key in started:
                    res = {"already_started": started[key], "kind": key[0], "subject": key[1],
                           "detail": "you started this already; it runs after your turn and does not return to you — "
                                     "file your brief with what you have and put it in follow_ups"}
                elif start_calls >= settings.sub_analyst_start_calls:
                    res = {"error": "analyst_budget",
                           "detail": f"you have started {settings.sub_analyst_start_calls} background tasks; none of "
                                     f"them returns within your turn — file your brief and put the rest in follow_ups"}
                else:
                    start_calls += 1
                    res = await tools_session.call(name, args, actor=actor, task_id=task.task_id)
                    res = res if isinstance(res, dict) else {"error": "tool_transport_error", "detail": str(res)[:200]}
                    started[key] = str(res.get("task_id") or res.get("run_id") or "")
                    result.log.append({"step": len(result.log) + 1, "tool": name, "asked": _asked(args),
                                       "why": str(args.get("why") or ""), "got": _got(res)})

            elif name in verbs:
                key = rp.digest({"tool": name, "args": {k: v for k, v in args.items() if k != "why"}})
                if key in last:
                    again = sent.record({"tool": name, "key": key})
                    res = {**last[key],
                           "repeated": (f"That {name} call was the same as one you already made, and the desk answered it "
                                        f"the same way. It is not charged, and it will not change: ask for something "
                                        f"else, or file what you have."
                                        if again <= rp.STOP else
                                        "Sent unchanged again. The desk will not answer differently; file your brief.")}
                elif name == LIST_TOOL:
                    # LOOKING AT WHAT THE DESK HOLDS IS NOT EVIDENCE. `list` returns names and dates
                    # and never a figure, so it is not charged against the evidence budget: the
                    # issuer analyst, asked about nine names, looked at what each one files — eight
                    # calls — and had eight left for the reading itself (V1 live smoke). The turn
                    # cap still bounds it, and the same `list` twice is answered from before.
                    res = await tools_session.call(name, args, actor=actor, task_id=task.task_id)
                    res = res if isinstance(res, dict) else {"error": "tool_transport_error", "detail": str(res)[:200]}
                    sent.record({"tool": name, "key": key})
                    last[key] = res
                    result.log.append({"step": len(result.log) + 1, "tool": name, "asked": _asked(args),
                                       "why": str(args.get("why") or ""), "got": _got(res)})
                elif evidence_calls >= settings.sub_analyst_evidence_calls:
                    # THE STOP IS A ROW (V1 live smoke). A line the budget kept the analyst from
                    # is "not settled, with the id of the absence row that says so" — and nothing
                    # minted one: the risk analyst wrote the error's name where an id goes, was
                    # refused, and then pointed at a policy that had nothing to do with it.
                    if budget_stop is None:
                        budget_stop = fa.refusal_fact(name, {"subject": task.subjects[0] if task.subjects else None}, {
                            "error": "analyst_budget",
                            "detail": _BUDGET_STOP.format(n=settings.sub_analyst_evidence_calls)})
                        await _record(ctx, actor, "boundary", name, {"of": "analyst_budget"}, "1 boundary row stated",
                                      facts=[budget_stop], task_id=task.task_id)
                    res = {"error": "analyst_budget", "rows": [F.line(budget_stop)],
                           "detail": "file your brief with what you have: a line you did not reach is not settled, and "
                                     "this row is its boundary"}
                else:
                    evidence_calls += 1
                    res = await tools_session.call(name, args, actor=actor, task_id=task.task_id)
                    res = res if isinstance(res, dict) else {"error": "tool_transport_error", "detail": str(res)[:200]}
                    if isinstance(res.get("made"), str) and res["made"] not in result.made:
                        result.made.append(res["made"])
                    sent.record({"tool": name, "key": key})
                    last[key] = res
                    result.log.append({"step": len(result.log) + 1, "tool": name, "asked": _asked(args),
                                       "why": str(args.get("why") or ""), "got": _got(res)})

            elif name == dl.SUBMIT_TOOL_NAME and standing is not None and rp.digest(args) in last:
                # THE SAME BRIEF AGAIN (V37/A2): the same verdict, answered from the
                # one that stands, and not counted as the attempt it is not.
                res = {"accepted": False, "refusal": dl.refusal_message(task, standing),
                       "repeated": "That brief was byte-identical to the one refused. Replace the entries named, or file "
                                   "the lines you can settle and say what stopped the rest."}

            elif name == dl.SUBMIT_TOOL_NAME:
                try:
                    brief = dl.parse_submission(args)
                except dl.BadDelegation as exc:
                    res = {"accepted": False, "error": "malformed_brief", "detail": str(exc)}
                else:
                    attempts += 1
                    last[rp.digest(args)] = {}
                    led = await _ledger(ctx)
                    brief = dl.merge_brief(kept_brief, brief)          # a resubmission replaces only what it names
                    verdict = dl.handoff_check(task, brief, led)
                    # the verdict rides on the step (V36.1): the retort the analyst
                    # read is otherwise nowhere on the record
                    await _record(ctx, actor, "brief", "submit",
                                  {"task_id": task.task_id, "brief": brief, "coverage": verdict.coverage,
                                   **({"problems": verdict.problems[:20]} if verdict.problems else {})},
                                  ("accepted" if verdict.ok else
                                   f"refused: {len(verdict.problems)} problem(s); {(verdict.problems[0] or {}).get('reason')}"),
                                  status="completed" if verdict.ok else "rejected", task_id=task.task_id)
                    _fill(result, brief, verdict)
                    if verdict.ok or attempts >= 2:
                        result.cost = {"completions": completions, "evidence_calls": evidence_calls,
                                       "starts": start_calls}
                        result.report_id = await _store_report(ctx, actor, task, result, verdict, led,
                                                               attempts=attempts, receipts=list(started.values()))
                        done = True
                        res = {"accepted": verdict.ok, "coverage": verdict.coverage}
                    else:
                        standing = verdict
                        kept_brief = {"lines": list(verdict.kept), "caveats": list(verdict.caveats_ok),
                                      "follow_ups": list(verdict.follow_ups_ok)}
                        res = {"accepted": False, "refusal": dl.refusal_message(task, verdict)}

            else:
                res = {"error": "unknown_tool", "detail": f"your tools are {', '.join(verbs)} and submit"}

            _append({"role": "tool", "tool_call_id": tc["id"], "content": ejson.dumps_capped(res, room, keep=("rows",))})
        if done:
            break

    if not result.lines:
        # No brief at all: the lead is told which lines went unanswered and why, in
        # the shape an unsettled line takes. The boundary goes on its own COMPLETED
        # step — the ledger reads completed steps only, and the brief that was never
        # filed is the rejected one (round B lost Q10 and Q18 to exactly that).
        text = ("the analyst did not file a brief within its turns"
                if completions >= settings.sub_analyst_max_turns else "the analyst stopped without filing a brief")
        fact = fa.refusal_fact("submit", {"subject": task.subjects[0]}, {"error": "no_brief", "detail": text})
        await _record(ctx, actor, "boundary", "submit", {"of": "submit"}, "1 boundary row stated", facts=[fact],
                      task_id=task.task_id)
        await _record(ctx, actor, "brief", "submit", {"task_id": task.task_id}, text, status="rejected",
                      task_id=task.task_id)
        result.status = "refused"
        result.lines = [{"n": i, "settled": False, "why": text, "boundary": fact.id}
                        for i in range(1, len(task.lines) + 1)]
        result.coverage = {"asked": len(task.lines), "settled": 0, "unsettled": len(task.lines), "refused": 0}
        result.cost = {"completions": completions, "evidence_calls": evidence_calls, "starts": start_calls}
        result.report_id = await _store_report(ctx, actor, task, result, None, None,
                                               attempts=attempts, receipts=list(started.values()))
    result.cost = result.cost or {"completions": completions, "evidence_calls": evidence_calls, "starts": start_calls}
    return result


def _fill(result: dl.AnalystResult, brief: dict, verdict: dl.HandoffVerdict) -> None:
    """What survives the check reaches the lead; what did not is named as refused.
    A brief that half passes is half a brief, not a lost one."""
    result.lines = list(brief["lines"])
    # V2 P1.1: only what passed the check is handed on; a refused caveat or follow-up
    # is in the verdict's problems and nowhere else
    result.caveats = list(verdict.caveats_ok)
    result.follow_ups = list(verdict.follow_ups_ok)
    result.refused = [{"n": x["n"], "finding": x.get("finding"), "problems": x.get("problems") or []}
                      for x in verdict.rejected]
    result.coverage = verdict.coverage
    settled, unsettled = len(verdict.accepted), verdict.coverage.get("unsettled", 0)
    # THE WORD THE LEAD READS MEANS WHAT HAPPENED: a brief that passed every check
    # while settling nothing is `unsettled`, not a success (V36 smoke round).
    if verdict.ok and settled and not unsettled:
        result.status = "settled"
    elif verdict.ok and settled:
        result.status = "partial"
    elif verdict.ok:
        result.status = "unsettled"
    elif settled or unsettled:
        result.status = "partial"
    else:
        result.status = "refused"


async def _store_report(ctx: TurnContext, actor: str, task: dl.Task, result: dl.AnalystResult,
                        verdict: dl.HandoffVerdict | None, ledger, *, attempts: int = 0,
                        receipts: list[str] | None = None) -> str | None:
    """The analyst's work, on the record: the brief in the shape the page reads,
    and the LOG as the text — what it did and why, built from its calls.

    A brief the check refused is stored too, marked, with its problems and without
    blocks: dropping it would lose what was tried, and showing its findings as if
    they had passed is the one thing the store must not do."""
    ok = verdict is not None and verdict.ok
    refused = {x["n"] for x in result.refused}
    findings = [{"want": e["n"], "finding": e["finding"]} for e in result.lines if e["settled"] and e["n"] not in refused]
    not_done = [{"want": e["n"], "why": e["why"], "boundary": e["boundary"]}
                for e in result.lines if not e["settled"] and e["n"] not in refused]
    rendered: dict = {}
    if ok and ledger is not None and findings:
        try:
            text = "\n\n".join(f["finding"] for f in findings)
            acc = answer_check.accepted(text, answer_check.check(text, ledger, question=task.asked_text()), ledger)
            rendered = {"blocks": acc["blocks"], "citations": acc["citations"], "verified": acc["verified"]}
        except Exception:  # noqa: BLE001 — findings that will not render are findings, not a lost brief
            logger.exception("could not render the findings of %s", task.task_id)
    try:
        async with ctx.db_factory() as db:
            report_id = await analyst_reports.store(
                db, ctx.session_id, message_id=ctx.message_id, task_id=task.task_id, domain=task.analyst,
                status="verified" if ok else "refused",
                title=f"the {task.analyst} analyst on {', '.join(task.subjects)}"[:200],
                brief={"findings": findings, "not_done": not_done,
                       "caveats": [f"line {c['line']}: {c['text']}" for c in result.caveats],
                       "follow_ups": result.follow_ups,
                       "refused": [{"want": x["n"], "reason": ((x.get("problems") or [{}])[0]).get("reason")}
                                   for x in result.refused]},
                text=dl.log_text(result), blocks=rendered.get("blocks") or [],
                citations=rendered.get("citations") or [], verified=rendered.get("verified") or {},
                problems=[] if ok else list((verdict.problems if verdict is not None else [])[:20]),
                evidence_calls=result.cost.get("evidence_calls"),
                # V2 P2: TaskState — what the task was cut from, what it kept, what it started
                requirement_ids=list(getattr(task, "requirement_ids", ()) or ()),
                input_version={"state_version": ctx.state_version, "scope": AS.scope_of(ctx.briefing, ctx.question),
                               "boundary_version": AS.BOUNDARY_VERSION,
                               "ledger_rows": len(ledger.shown) if ledger is not None else None},
                accepted_lines=[{**e, "validation": AS.validation_context(
                    AS.scope_of(ctx.briefing, ctx.question), e.get("facts") if e.get("settled") else [e.get("boundary")],
                    ledger)} for e in verdict.kept] if verdict is not None else [],
                attempts=attempts, receipts=[r for r in (receipts or []) if r])
            await db.commit()
    except Exception:  # noqa: BLE001 — a lost record beats a lost turn
        logger.exception("could not store the record of %s in session %s", task.task_id, ctx.session_id)
        return None
    await _record(ctx, actor, "report", "report", {"report_id": report_id, "task_id": task.task_id,
                                                    "status": "verified" if ok else "refused"},
                  f"{'verified' if ok else 'refused'}: {len(result.log)} call(s), {len(findings)} line(s) settled",
                  task_id=task.task_id)
    return report_id


async def run_tasks(tasks: list[dl.Task], ctx: TurnContext) -> list[dl.AnalystResult]:
    """Every task of one ask. Serial until Phase 3: the three things parallelism
    needs — seq allocation under a lock, a concurrency-tested MCP session, a
    per-analyst budget — are measured before they are assumed."""
    settings = get_settings()
    if settings.parallel_analysts and len(tasks) > 1:
        import asyncio
        return list(await asyncio.gather(*(run_sub_analyst(t, ctx) for t in tasks)))
    out: list[dl.AnalystResult] = []
    for task in tasks:
        out.append(await run_sub_analyst(task, ctx))
    return out
