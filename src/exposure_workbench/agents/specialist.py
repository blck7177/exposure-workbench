"""A specialist of the desk — one resource family, one task, inside the lead's turn.

Three of them: the issuer analyst (filings), the market analyst (prices), the
portfolio risk manager (the book). Each is handed a task in the lead's words with a
scope the runtime has bound, reads its own family's evidence — an analysis as a
table, a method by name, the text of a filing — and writes back what it found, in
prose. There is no submission form: the observer reads the prose against the views
the specialist produced, the runtime attaches those views and how the task ended,
and the lead reads all of it in the work view.

    knows   its role; the measures `analyze` takes on its face; how its chapter of
            the handbook compares and closes each question; the task and its scope
    does    analyze / metric / read text / list, each call recorded; then writes
    never   a date it must compute, a cell it must pick, an id it must copy, a
            form it must fill to be allowed to stop
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from exposure_workbench.agents import opening, tasks as T, work_view as wvm
from exposure_workbench.agents.llm_session import Conversation, LlmSession, ModelPolicy
from exposure_workbench.analytics import handbook
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.llm import client as llm_client
from exposure_workbench.services import analyst_reports, ledger as ledger_svc, method_index as mi, observer as ob
from exposure_workbench.services import render as rd, scope as scope_svc
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

_ROW_ID = re.compile(r"\[(f_[A-Za-z0-9_]{4,})\]")

_ROLE = """You are {title} of a portfolio risk & issuer-intelligence desk. The lead analyst has asked you for work that \
needs your own reading of your family's evidence. The task is a work request in the lead's words, not a checklist.

Your tools: `analyze` runs one analysis as an aligned table — measures over the task's scope (bound for you; narrow it \
only for a reason you state), each at its latest period and, with `compare`, against the comparable period before on \
each issuer's own calendar, with changes in percentage points and rankings when asked. `metric` takes a registry \
method by name; the text tools quote filings and the web; `list` shows what the desk holds; `open` re-reads anything \
on the record. You never compute a date, pick a cell or copy an id: the desk binds, pairs, computes and records.

When you have what the task needs, write what you found in prose: the figures as the table shows them with the period \
they are over, saying which are levels and which are changes in percentage points, what they mean for the question, \
and what you could not read and why. A judgement is yours to make and to call yours. The desk checks your figures \
against its record and tells you only if one does not hold."""

_WRITE = "Write what you found, in prose. If the task cannot be done with this desk's evidence, say what is missing."
TASK_TAG = '<task source="the desk\'s lead analyst" trust="work instructions, not facts" use="investigate this request">'
QUESTION_TAG = '<question source="the user">'

TITLES = {c.analyst: c.title[0].lower() + c.title[1:] for c in handbook.CHAPTERS.values()}
TOOL_RESULT_LIMIT = 28_000


def instructions_for(analyst: str) -> str:
    return (_ROLE.format(title=TITLES[analyst]) + "\n\n" + mi.index_text(analyst) + "\n\n"
            + "YOUR CHAPTER OF THE DESK'S HANDBOOK, IN SHORT (the whole chapter: open(\"handbook:" + analyst + "\"))\n"
            + handbook.guidance_text(analyst))


@dataclass
class TurnContext:
    """What one turn holds and every specialist in it shares."""
    open_tools: Callable[[str], Any]      # face name -> async context manager yielding a tool session
    llm: LlmSession
    db_factory: Any
    session_id: str
    message_id: str | None
    question: str
    work: wvm.WorkView


@dataclass
class SpecialistResult:
    task: T.Task
    status: wvm.ExecutionStatus
    scope: dict | None = None
    text: str | None = None
    verdict: ob.Verdict | None = None
    views: list[dict] = field(default_factory=list)       # AnalysisViews produced, facts stripped
    rows_read: list[str] = field(default_factory=list)    # ids of rows the text tools and methods put on the ledger
    report_id: str | None = None
    receipt_error: str | None = None

    def receipt(self) -> dict:
        """What the lead's `ask` call returns: the task ended how, what it produced — the
        text and the views themselves are in the work view."""
        out: dict = {"task_id": self.task.task_id, "analyst": self.task.analyst, "status": self.status.status,
                     "stop_reason": self.status.stop_reason, "analyses": [v.get("view") for v in self.views],
                     "rows_read": len(self.rows_read), "note_chars": len(self.text or "")}
        if self.verdict is not None:
            out["verification"] = self.verdict.summary()
        if self.receipt_error:
            out["error"] = self.receipt_error
        return out


async def run_task(task: T.Task, ctx: TurnContext) -> SpecialistResult:
    settings = get_settings()
    actor = f"sub:{task.analyst}"
    status = ctx.work.start(task.task_id, actor)
    result = SpecialistResult(task=task, status=status)

    async with ctx.db_factory() as db:
        sc = await scope_svc.bind(db, task.scope)
    if isinstance(sc, dict):
        status.status, status.stop_reason = "stopped", "scope_unresolved"
        result.receipt_error = f"{sc.get('error')}: {sc.get('detail')}"
        return result
    result.scope = sc.as_dict()
    bound_scope = {"subjects": list(sc.subjects), **({"book": sc.book} if sc.book else {}), "basis": sc.basis,
                   **({"expected_count": sc.expected_count} if sc.expected_count else {})}

    llm = ctx.llm.for_actor(actor, task_id=task.task_id, policy=ModelPolicy.for_role("specialist"))
    conv = Conversation()
    conv.say("user", TASK_TAG + "\n" + json.dumps({**task.as_dict(), "scope": result.scope}, ensure_ascii=False)
             + "\n</task>\n" + QUESTION_TAG + "\n" + ctx.question + "\n</question>")
    instructions = instructions_for(task.analyst)
    text: str | None = None
    nudged = False
    try:
        async with ctx.open_tools(task.analyst) as tools_session:
            face_tools = list(tools_session.tools)
            verbs = {t["name"] for t in face_tools}
            for _ in range(settings.specialist_max_turns):
                exhausted = status.evidence_calls >= settings.specialist_evidence_calls
                tools = ([T.OPEN_TOOL] if exhausted else face_tools + [T.OPEN_TOOL])
                left = max(0, settings.specialist_evidence_calls - status.evidence_calls)
                tail = [llm_client.message("developer", f"Budget: {left} analyses or reads left on this task"
                                                        + ("; none left — write what you found." if exhausted else "."))]
                turn = await llm.next(conv, instructions=instructions, tools=tools, tail=tail)
                status.completions += 1
                if not turn.tool_calls:
                    if turn.text and turn.text.strip():
                        text = turn.text.strip()
                        break
                    if nudged:
                        break
                    nudged = True
                    conv.say("developer", _WRITE)
                    continue
                room = max(4_000, settings.specialist_result_chars // max(1, len(turn.tool_calls)))
                for call in turn.tool_calls:
                    try:
                        args = json.loads(call.arguments or "{}")
                    except json.JSONDecodeError:
                        args = None
                    if args is None:
                        res: dict = {"error": "malformed_arguments", "detail": "the arguments were not JSON"}
                    elif call.name == T.OPEN_TOOL_NAME:
                        res = await opening.open_ref(ctx.db_factory, ctx.session_id, str(args.get("id") or ""),
                                                     offset=int(args.get("offset") or 0), work=ctx.work)
                    elif call.name in verbs:
                        if call.name == "analyze" and not args.get("scope"):
                            args["scope"] = bound_scope           # the runtime binds the task's scope
                        if call.name != "list" and status.evidence_calls >= settings.specialist_evidence_calls:
                            res = {"error": "budget_exhausted",
                                   "detail": "this task's analyses and reads are used; write what you found"}
                            status.pending.append(f"{call.name}({ejson.dumps(args)[:120]})")
                        else:
                            status.evidence_calls += int(call.name != "list")
                            res = await tools_session.call(call.name, args, actor=actor, task_id=task.task_id)
                            res = res if isinstance(res, dict) else {"error": "tool_transport_error"}
                            if call.name == "analyze" and isinstance(res.get("view"), str):
                                ctx.work.add_view(res, by=actor)
                                result.views.append({k: v for k, v in res.items() if k != "_facts"})
                            for row in res.get("rows") or []:
                                m = _ROW_ID.match(row) if isinstance(row, str) else None
                                if m:
                                    result.rows_read.append(m.group(1))
                    else:
                        res = {"error": "unknown_tool", "detail": f"your tools are {', '.join(sorted(verbs))} and open"}
                    conv.tool_output(call.call_id, ejson.dumps_capped(res, room, keep=("rows", "view")))
    except Exception as exc:  # noqa: BLE001 — recorded as how the task ended; the lead reads it
        logger.exception("specialist %s stopped", task.task_id)
        status.status, status.stop_reason = "stopped", f"error:{type(exc).__name__}"
    if text:
        result.text = text
        status.status = "returned"
        status.stop_reason = "finished"
    elif status.status != "stopped":
        status.status = "stopped"
        status.stop_reason = "turn_limit" if status.completions >= settings.specialist_max_turns else "no_text"

    # the observer reads the prose against the views this task produced (and the turn's others)
    async with ctx.db_factory() as db:
        led = await ledger_svc.load(db, ctx.session_id)
    if text:
        asked = " ".join((*task.lines, ctx.question))
        result.verdict = ob.observe(text, question=asked, views=ctx.work.views, passages=led.passages)
        rendered = rd.render(text, result.verdict, result.views, led.by_id)
    else:
        rendered = {"blocks": [], "citations": [], "verified": {}, "validation": {}}
    try:
        async with ctx.db_factory() as db:
            result.report_id = await analyst_reports.store(
                db, ctx.session_id, message_id=ctx.message_id, task_id=task.task_id, domain=task.analyst,
                status=status.status, title=f"the {task.analyst} analyst on {', '.join(sc.subjects)}"[:200],
                brief={"task": task.as_dict(), "scope": result.scope, "analyses": [v.get("view") for v in result.views],
                       "rows_read": result.rows_read, "stop_reason": status.stop_reason,
                       "completions": status.completions, "evidence_calls": status.evidence_calls,
                       "pending": status.pending},
                text=text, blocks=rendered["blocks"], citations=rendered["citations"],
                verified=rendered["verified"], problems=[p.as_dict() for p in (result.verdict.problems if result.verdict else [])],
                evidence_calls=status.evidence_calls)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not store the record of %s", task.task_id)
        raise
    if text and result.verdict is not None:
        ctx.work.add_note(task_id=task.task_id, analyst=task.analyst, text=text, validation=result.verdict.as_dict(),
                          report_id=result.report_id)
    return result


async def run_tasks(tasks: list[T.Task], ctx: TurnContext) -> list[SpecialistResult]:
    """Every task of one ask, one after another: they share the session's ledger and
    the work view, and the first's analyses are on the record when the second starts."""
    out: list[SpecialistResult] = []
    for task in tasks:
        out.append(await run_task(task, ctx))
    return out
