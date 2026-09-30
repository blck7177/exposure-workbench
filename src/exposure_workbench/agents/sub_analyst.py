"""An analyst of the desk (V1) — one resource family, one task, inside the lead's turn.

There are three: the issuer analyst (filings), the market analyst (prices) and
the portfolio risk manager (the book). Each is handed a task in the lead's own
words and returns evidence with optional checked analysis notes.

    knows  four things, all given before it starts: what its family of data is
           and what the desk holds for the task's subjects; the task; its tools —
           the list itself, each verb saying what it does; and its chapter of the
           handbook (analytics/handbook), which says what a measure is, how it
           reads, what to set against what and what the desk does not say
    does   pulls rows with its own face's verbs (tools/primitives), every call
           saying WHY; then `submit` — evidence ids and optional text/refs notes.
           Already obtained evidence survives an interrupted execution.
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
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from exposure_workbench.agents import delegation as dl, delivery, handoff, repeats as rp
from exposure_workbench.analytics import handbook, registry
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.services import analysis_state as AS, analyst_reports, answer_check, fact_boundary, fact_adapters as fa, facts as F, \
    ledger as ledger_svc, style_guide, trace_service
from exposure_workbench.tools import faces
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

# `start` is on the face and reachable, and is counted apart (V36.1): it returns a
# task id, never a row. Every other verb is an evidence call.
LIST_TOOL = "list"
START_TOOL = "start"

# The actual execution budget stop; it does not close unvisited task lines.
_BUDGET_STOP = "this task's {n} evidence calls are used; what was not read by then was not reached"

_SYSTEM = """You are {title} of a portfolio risk & issuer-intelligence desk. The lead's task is a work request, not a
checklist that every line must be certified closed. Read and analyse your own family's evidence for that task.

Your tools read resources and calculate from existing rows. Every call says WHY. Each row carries its subject, period,
value, meaning and source. Use tool arithmetic, not mental arithmetic. A tool refusal describes that operation; it does
not prove that the whole business question is unanswerable. The standing policies are {policies}.

Submit evidence row ids and optional notes. Evidence alone is useful; do not transcribe rows just to satisfy a form.
A note has text and refs. Figures are checked only against those refs; narrow the note or use an explicit pointer when
the same value belongs to several rows or dates. Keep limitations beside the claim they qualify. All note text passes
the same factual check as the final answer. Task instructions are not factual evidence; only the original user question
can supply user-given assumptions.

When an item fails, accepted evidence and notes remain. Use the returned note id to replace it, or submit empty text for
that id to withdraw it. You may return partial work without inventing an absence row for what you did not reach. The
runtime records actual calls, failures and stop reasons. Returning work does not certify that the question is complete."""

_WRITE_OR_ASK = "Submit evidence and optional notes, or read the rows you still need."

# THE TWO BLOCKS HANDED TO AN ANALYST, each saying what it is, where it came from
# and what to do with it (V37/A3) — named, so the wording sheet reads the object
# the turn sends.
TASK_TAG = ('<task source="the desk\'s lead analyst" trust="work instructions, not facts" use="investigate this request">')
COVERAGE_TAG = ('<coverage source="the desk\'s catalogue" trust="names, dates and coverage only — no figure here" '
                'use="what the desk holds for the task\'s subjects, and up to when">')
# V2 P2.3 (design v0.4 §07, G4): what the task this one follows up left on the record —
# the entries that passed every check, with the desk's rows under them, and what stopped
# the rest. Nothing refused is here, and nothing here is read again by a tool.
PRIOR_TAG = ('<prior source="the desk\'s record of the task this one follows up" use="checked notes and evidence from that task, with '
             'its rows and actual stop reason; ask for what is still missing rather than pulling these again">')

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
                task_id=task_id, evidence_refs=[ledger_svc.step_entry(facts)] if facts else [],
                unbounded=("submission", "notes", "result") if step_type == "brief" else ())
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
    """Restore scoped evidence and checked notes for a follow-up; read legacy
    line reports through their historical adapter. Recheck provenance and text
    against the current ledger, never trust the persisted rendered row."""
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
    if (rep.get("input_version") or {}).get("protocol") == handoff.PROTOCOL:
        prior = {"task_id": task.follow_up_of, "notes": [], "evidence": [],
                 "stop_reason": (rep.get("brief") or {}).get("stop_reason")}
        for note in rep.get("accepted_lines") or []:
            if (AS.reusable(note["text"], note["refs"], note.get("validation"), scope, led, ctx.question)
                    and fact_boundary.check_block("finding", note["text"], note["refs"], led, question=ctx.question)[1].ok):
                prior["notes"].append({"id": note["id"], "text": note["text"],
                                       "rows": [F.line(led.by_id[f]) for f in note["refs"]]})
        evidence = rep.get("brief", {}).get("evidence") or []
        refs = [e["id"] for e in evidence]
        if AS.evidence_reusable(refs, rep["input_version"].get("evidence_validation"), scope, led):
            prior["evidence"] = [{"id": fid, "row": F.line(led.by_id[fid])} for fid in refs]
        if not prior["notes"] and not prior["evidence"]:
            return ""
        return "\n" + PRIOR_TAG + "\n" + json.dumps(prior, ensure_ascii=False) + "\n</prior>"
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
    """One analyst, start to evidence handoff, on its own face."""
    async with ctx.open_tools(task.analyst) as tools_session:
        return await _run(task, ctx, tools_session)


async def _run(task: dl.Task, ctx: TurnContext, tools_session) -> dl.AnalystResult:
    settings = get_settings()
    actor = f"sub:{task.analyst}"
    result = dl.AnalystResult(task=task, protocol=handoff.PROTOCOL, status="stopped")
    evidence_calls = start_calls = completions = 0
    budget_stop = None
    started: dict[tuple[str, str], str] = {}            # (kind, subject) -> the task it enqueued
    llm = ctx.llm.for_actor(actor) if hasattr(ctx.llm, "for_actor") else ctx.llm

    messages: list[dict] = [
        {"role": "system", "content": system_text(task.analyst)},
        {"role": "user", "content":
         TASK_TAG + "\n" + json.dumps(task.as_dict(), ensure_ascii=False, default=str) + "\n</task>\n"
         + COVERAGE_TAG + "\n" + json.dumps(_coverage_of(task, ctx.briefing), ensure_ascii=False, default=str)
         + "\n</coverage>\n<question source=\"the user\">\n" + ctx.question + "\n</question>"
         + await _prior_block(task, ctx)},
    ]
    face = _face_tools(tools_session, task.analyst)
    verbs = [t["function"]["name"] for t in face]
    tools = face + [dl.SUBMIT_TOOL]
    standing = False
    submission = handoff.Submission()
    submission_reply: dict = {}
    collected_ids: set[str] = set()
    pulls: set[str] = set()
    phase = "provider"

    async def invoke(name, args):
        operation = {"tool": name, "params": {k: v for k, v in args.items() if k != "why"}}
        result.operations.append(operation)
        try:
            reply = await tools_session.call(name, args, actor=actor, task_id=task.task_id)
        except Exception as exc:
            operation.update(status="error", error=type(exc).__name__)
            raise
        reply = reply if isinstance(reply, dict) else {"error": "tool_transport_error"}
        operation.update(status="error" if reply.get("error") else "returned")
        for key in ("pull", "error", "task_id", "run_id"):
            if reply.get(key):
                operation[key] = reply[key]
        if reply.get("pull"):
            pulls.add(str(reply["pull"]))
        for row in reply.get("rows") or []:
            match = re.match(r"\[(f_[A-Za-z0-9_]+)\]", row) if isinstance(row, str) else None
            if match:
                collected_ids.add(match.group(1))
        return reply
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

    try:
        for _turn in range(settings.sub_analyst_max_turns):
            phase = "provider"
            read.project(messages)
            content, tool_calls = await llm.chat(
                messages=messages, tools=tools, note=read.note(),
                **({"tool_choice": "required"} if standing else {}))
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

            phase = "tool"
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
                                         "submit what you have; the runtime records this receipt"}
                    elif start_calls >= settings.sub_analyst_start_calls:
                        res = {"error": "analyst_budget",
                               "detail": f"you have started {settings.sub_analyst_start_calls} background tasks; none of "
                                         f"them returns within your turn — submit what you have; the runtime records these receipts"}
                    else:
                        start_calls += 1
                        res = await invoke(name, args)
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
                                            "Sent unchanged again. The desk will not answer differently; submit your evidence and notes.")}
                    elif name == LIST_TOOL:
                        # LOOKING AT WHAT THE DESK HOLDS IS NOT EVIDENCE. `list` returns names and dates
                        # and never a figure, so it is not charged against the evidence budget: the
                        # issuer analyst, asked about nine names, looked at what each one files — eight
                        # calls — and had eight left for the reading itself (V1 live smoke). The turn
                        # cap still bounds it, and the same `list` twice is answered from before.
                        res = await invoke(name, args)
                        res = res if isinstance(res, dict) else {"error": "tool_transport_error", "detail": str(res)[:200]}
                        sent.record({"tool": name, "key": key})
                        last[key] = res
                        result.log.append({"step": len(result.log) + 1, "tool": name, "asked": _asked(args),
                                           "why": str(args.get("why") or ""), "got": _got(res)})
                    elif evidence_calls >= settings.sub_analyst_evidence_calls:
                        # Record an actual budget refusal. It describes this
                        # execution, not a boundary closing any requested line.
                        if budget_stop is None:
                            budget_stop = fa.refusal_fact(name, {"subject": task.subjects[0] if task.subjects else None}, {
                                "error": "analyst_budget",
                                "detail": _BUDGET_STOP.format(n=settings.sub_analyst_evidence_calls)})
                            await _record(ctx, actor, "boundary", name, {"of": "analyst_budget"}, "1 boundary row stated",
                                          facts=[budget_stop], task_id=task.task_id)
                        res = {"error": "analyst_budget", "rows": [F.line(budget_stop)],
                               "detail": "submit the evidence and notes you have; this row records an execution budget limit"}
                    else:
                        evidence_calls += 1
                        res = await invoke(name, args)
                        res = res if isinstance(res, dict) else {"error": "tool_transport_error", "detail": str(res)[:200]}
                        if isinstance(res.get("made"), str) and res["made"] not in result.made:
                            result.made.append(res["made"])
                        sent.record({"tool": name, "key": key})
                        last[key] = res
                        result.log.append({"step": len(result.log) + 1, "tool": name, "asked": _asked(args),
                                           "why": str(args.get("why") or ""), "got": _got(res)})

                elif name == dl.SUBMIT_TOOL_NAME and standing and rp.digest(args) in last:
                    res = {**submission_reply, "repeated": "Unchanged submission: repair or withdraw the named items."}

                elif name == dl.SUBMIT_TOOL_NAME:
                    try:
                        payload = handoff.parse(args)
                    except handoff.BadSubmission as exc:
                        res = {"accepted": False, "error": "malformed_submission", "detail": str(exc)}
                        await _record(ctx, actor, "brief", "submit", {"protocol": handoff.PROTOCOL, "submission": args},
                                      "refused: malformed_submission", status="rejected", task_id=task.task_id)
                    else:
                        attempts += 1
                        last[rp.digest(args)] = {}
                        led = await _ledger(ctx)
                        res = submission.apply(payload, led, ctx.question)
                        submission_reply = res
                        await _record(ctx, actor, "brief", "submit",
                                      {"task_id": task.task_id, "protocol": handoff.PROTOCOL, "submission": payload,
                                       "result": res, "notes": list(submission.notes.values()), "problems": res["problems"]},
                                      "accepted" if submission.ok else
                                      f"refused: {len(res['problems'])} problem(s); {res['problems'][0]['reason']}",
                                      status="completed" if submission.ok else "rejected", task_id=task.task_id)
                        standing = not submission.ok
                        if submission.ok or attempts >= 2:
                            result.status = "returned" if submission.ok else "stopped"
                            result.stop_reason = "submitted" if submission.ok else "submission_rejected"
                            done = True

                else:
                    res = {"error": "unknown_tool", "detail": f"your tools are {', '.join(verbs)} and submit"}

                _append({"role": "tool", "tool_call_id": tc["id"], "content": ejson.dumps_capped(res, room, keep=("rows",))})
                if done:
                    break
            if done:
                break
    except Exception as exc:
        logger.exception("analyst %s stopped during %s", task.task_id, phase)
        result.stop_reason = "provider_error" if phase == "provider" else "execution_error"
        result.operations.append({"status": "error", "phase": phase, "error": type(exc).__name__})
    result.stop_reason = result.stop_reason or ("turn_limit" if completions >= settings.sub_analyst_max_turns else "no_submission")
    result.cost = {"completions": completions, "evidence_calls": evidence_calls, "starts": start_calls}
    result.evidence = list(submission.evidence)
    result.notes = list(submission.notes.values())
    result.diagnostics = submission.diagnostics()
    result.receipts = [r for r in started.values() if r]
    led = await _ledger(ctx)
    result.available_evidence = [fid for fid, rec in led.by_id.items()
                                 if fid in collected_ids or (rec.get("params") or {}).get("pull") in pulls]
    if budget_stop is not None and led.holds(budget_stop.id) and budget_stop.id not in result.available_evidence:
        result.available_evidence.append(budget_stop.id)
    result.report_id = await _store_report(ctx, actor, task, result, None, led,
                                           attempts=attempts, receipts=result.receipts)
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
    if result.protocol == handoff.PROTOCOL:
        return await _store_evidence_report(ctx, actor, task, result, ledger, attempts=attempts)
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


async def _store_evidence_report(ctx, actor, task, result, ledger, *, attempts):
    """Record checked items even when another item or a later call failed."""
    scope = AS.scope_of(ctx.briefing, ctx.question)
    refs = list(dict.fromkeys([*result.evidence, *result.available_evidence,
                               *(fid for note in result.notes for fid in note["refs"])]))
    rows = [{"id": fid, "row": F.line(ledger.by_id[fid]), "selected": fid in result.evidence} for fid in refs]
    try:
        async with ctx.db_factory() as db:
            report_id = await analyst_reports.store(
                db, ctx.session_id, message_id=ctx.message_id, task_id=task.task_id, domain=task.analyst,
                status=result.status, title=f"the {task.analyst} analyst on {', '.join(task.subjects)}"[:200],
                brief={"protocol": handoff.PROTOCOL, "evidence": rows,
                       "notes": [{"id": n["id"], "text": n["text"], "refs": n["refs"]} for n in result.notes],
                       "stop_reason": result.stop_reason, "operations": result.operations, "receipts": result.receipts},
                text=dl.log_text(result), blocks=[b for n in result.notes for b in n["blocks"]],
                citations=refs, verified={"checked_notes": len(result.notes)}, problems=result.diagnostics,
                evidence_calls=result.cost.get("evidence_calls"), requirement_ids=[],
                input_version={"protocol": handoff.PROTOCOL, "state_version": ctx.state_version, "scope": scope,
                               "boundary_version": AS.BOUNDARY_VERSION,
                               "ledger_rows": len(ledger.shown),
                               "evidence_validation": AS.validation_context(scope, refs, ledger)},
                accepted_lines=[{**n, "kind": "note", "validation": AS.validation_context(scope, n["refs"], ledger)}
                                for n in result.notes], attempts=attempts, receipts=result.receipts)
            await db.commit()
    except Exception:
        logger.exception("could not store evidence report for %s", task.task_id)
        return None
    await _record(ctx, actor, "report", "report", {"report_id": report_id, "task_id": task.task_id, "protocol": handoff.PROTOCOL,
                  "status": result.status, "stop_reason": result.stop_reason},
                  f"{len(refs)} evidence rows; {len(result.notes)} checked notes; {result.stop_reason}", task_id=task.task_id)
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
