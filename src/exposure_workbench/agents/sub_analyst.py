"""The domain analyst (V36) — one domain, one task, inside the lead's turn.

It is handed a task in the lead's own words and comes back with a finding for
each numbered line of it. In between it does the thing that had no owner in
V35: turning an intent into the desk's language. It holds that domain's
procedure — what the question is, what this desk knows about it, how it
compares and closes, and the programs that answer it — and the language's
signatures, and it writes the program itself.

    read : the domain's procedure, the language, the task, the desk's map for
           the task's subjects, and every tool result, with each figure shown
           the way it must be written
    write: compile / run / read_filings / search_web / start, then submit —
           a brief for the lead and a report for the record
    never: a sentence a reader sees. The lead writes the answer.

WHY IT IS A SECOND AGENT AND NOT A SECOND FUNCTION. The V35 broker compiled
decision-level fields into a program deterministically and handed anything it
could not compile to a writer that saw only the signatures. That is the right
shape for a request whose fields say everything, and round J's Q11 is what
happens when they do not: "measure room to warning and breach" sat in the `ask`
field, the compiler read fields, and the room was never computed. Deterministic
compilation is still here — it is this analyst's first tool — but the thing
that decides what to compile now reads the sentence.

WHY IT RUNS INSIDE THE LEAD'S TURN. Same session, same message, same tool-face
token (D3). That is what puts its facts on the ledger the answer check reads: a
domain analyst in a session of its own would leave the lead unable to cite
anything it fetched, and every figure of the answer would be refused as
not_on_ledger.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from exposure_workbench.agents import delegation as dl
from exposure_workbench.analytics import skill
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.services import digest as dg, ledger as ledger_svc, program_builder as pb, \
    program_service as ps, trace_service
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

# The evidence tools a domain analyst may reach, by name off the face. `compile`
# and `submit` are in-process and are not on any face: one retrieves nothing and
# the other is the analyst's exit.
EVIDENCE_TOOLS = ("run", "read_filings", "search_web", "start")

COMPILE_TOOL = {"type": "function", "function": {
    "name": "compile",
    "description": (
        "Turn a request in the desk's names into a typed program, without running it. Say the subjects, the names you "
        "want about them (methods, filed lines, run table columns), a window and a comparison, and the arithmetic you "
        "want derived; you get back the program that says it, plus any name this desk does not hold. Edit the program "
        "it gives you — add a division, a filter, a node the fields cannot say — then call run. A name the desk does "
        "not hold costs that name and nothing else."),
    "parameters": {"type": "object", "properties": {"request": {"type": "object", "properties": {
        "subjects": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "want": {"type": "array", "minItems": 1, "items": {"type": "string"},
                 "description": "method names, filed lines, table.column, 'book', 'scenario:sell <T> <fraction>'"},
        "window": {"type": ["string", "null"], "description": "12m | last 8 quarters | last 5 years | at YYYY-MM-DD | 1y | 30d | vs prev run | vs SPY"},
        "compare": {"type": ["string", "null"], "description": "rank | rank lowest | change | versus | share_of:<name> | filter:<op><level>"},
        "derive": {"type": ["array", "null"], "items": {"type": "string"},
                   "description": "'<result> = <name> <+-*/> <name|number>', over the names in `want`"}},
        "required": ["subjects", "want"], "additionalProperties": False}},
        "required": ["request"], "additionalProperties": False}}}

_SYSTEM = """You are the desk's {domain} analyst. One task from the desk's lead analyst is in front of you. Decide which \
of the desk's figures settle each numbered line of it, produce them with the desk's tools, read what came back, and file \
a brief that answers the task line by line, plus a report of your reading for the record.

The figures are yours to produce and the language is yours to write. compile(request) turns names into a typed program \
without running it — edit what it gives you and run that, or write the program yourself. run(program) executes one \
program: every node comes back typed, dated, and on the ledger as a fact, or the type report lists every problem at once. \
read_filings reads a filing's text, search_web the web, start puts an issuer on the desk. Every figure a tool shows you \
carries the id it is shown under — 16.0% [f_2592baab170e] — and `place` of `of` is where it sits in the ordering its \
node built: a superlative rests on that, never on reading a list. Never compute in your head: a number you worked out \
yourself is a number no fact stands behind, and it is refused.

The brief is one entry per numbered line: the line's number, the ids it rests on, and one to three sentences with every \
figure written exactly as the desk showed it, bracket included. A line this desk cannot settle goes in not_done with the \
desk's own words for why and the id of the boundary it stated — never an estimate, never a nearby figure under the \
asked-for name. What you had to assume or leave out goes in caveats; the lead states those to the reader. The report is \
your full reading in prose, same rule for figures, and [table: <node>] or [chart: <node>] shows a node's figures.

You write for the lead analyst, never for the user, and you answer the task you were given rather than the one you would \
have asked. If your submission is refused you are told which entries and why: submit again with those replaced, and \
request the evidence a fix needs first if you were not shown the figure."""

_WRITE_OR_ASK = "File your brief with submit, or get the evidence you still need."


@dataclass
class TurnContext:
    """What one turn holds and every analyst in it shares (D3)."""
    tools_session: object
    llm: object                      # agents.llm_session.LlmSession
    db_factory: object
    session_id: str
    message_id: str | None
    briefing: dict = field(default_factory=dict)


def _subjects_of(task: dl.Task, briefing: dict) -> dict:
    """The desk's map for this task's subjects only. The lead read the whole
    briefing to decide whom to ask; the analyst needs the names, dates and
    coverage of what it was pointed at."""
    issuers, ports = briefing.get("issuers") or {}, briefing.get("portfolios") or {}
    out: dict = {}
    for s in task.subjects:
        d = issuers.get(s) or issuers.get(s.upper()) or ports.get(s)
        if d is not None:
            out[s] = d
    return out


def _held_in(briefing: dict) -> dict:
    return {tk: [h.get("portfolio_id") for h in (d.get("held_in") or []) if isinstance(h, dict) and h.get("portfolio_id")]
            for tk, d in (briefing.get("issuers") or {}).items() if isinstance(d, dict)}


def _face_tools(tools_session) -> list[dict]:
    by_name = {t["function"]["name"]: t for t in getattr(tools_session, "tools", []) or []}
    return [by_name[n] for n in EVIDENCE_TOOLS if n in by_name]


async def _record(ctx: TurnContext, actor: str, step_type: str, tool_name: str | None, args: dict,
                  summary: str, facts: list | None = None, status: str = "completed") -> None:
    try:
        async with ctx.db_factory() as db:
            step_id = await trace_service.record_step(
                db, ctx.session_id, step_type=step_type, tool_name=tool_name, args=args,
                result_summary=summary, status=status, message_id=ctx.message_id, actor=actor,
                evidence_refs=[ledger_svc.step_entry(facts)] if facts else [])
            for row in ledger_svc.rows_for(facts or [], session_id=ctx.session_id, step_id=step_id,
                                           message_id=ctx.message_id):
                db.add(row)
            await db.commit()
    except Exception:  # noqa: BLE001 — a hole in the audit trail beats a lost turn
        logger.exception("could not record %s step for session %s", step_type, ctx.session_id)


async def _ledger(ctx: TurnContext):
    async with ctx.db_factory() as db:
        return await ledger_svc.load(db, ctx.session_id)


async def run_sub_analyst(task: dl.Task, ctx: TurnContext) -> dl.AnalystResult:
    """One domain analyst, start to brief."""
    settings = get_settings()
    actor = f"sub:{task.domain}"
    procedure = skill.PROCEDURES.get(task.domain)
    result = dl.AnalystResult(task=task)
    minter = dg.Minter()
    seen: dict = {}                                     # one reading is shown once, across the whole session
    evidence_calls = 0
    completions = 0
    llm = ctx.llm.for_actor(actor) if hasattr(ctx.llm, "for_actor") else ctx.llm

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM.format(domain=task.domain)
         + "\n\nDOMAIN " + (skill.system_text(procedure) if procedure else task.domain)
         + "\n\nTHE LANGUAGE\n" + ps.signature_text()},
        {"role": "user", "content": json.dumps(
            {"task": task.as_dict(), "subjects": _subjects_of(task, ctx.briefing),
             "boundaries": list(ps.BOUNDARIES)}, ensure_ascii=False, default=str)},
    ]
    tools = [COMPILE_TOOL] + _face_tools(ctx.tools_session) + [dl.SUBMIT_TOOL]
    standing: dl.HandoffVerdict | None = None           # a verdict on a submission, awaiting its replacement
    attempts = 0
    nudges = 0

    for _turn in range(settings.sub_analyst_max_turns):
        content, tool_calls = await llm.chat(
            messages=messages, tools=tools,
            **({"tool_choice": "required"} if standing is not None else {}))
        completions += 1
        msg: dict = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        messages.append(msg)

        if not tool_calls:
            nudges += 1
            if nudges > 2:
                break
            messages.append({"role": "user", "content": _WRITE_OR_ASK})
            continue

        done = False
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "compile":
                out = pb.compile_request(args.get("request") or {}, held_in=_held_in(ctx.briefing))
                await _record(ctx, actor, "tool_call", "compile", {"request": args.get("request")},
                              ("no program: " + str(out.get("reason"))[:180]) if out.get("program") is None
                              else f"{len(out['program']['let'])} binding(s), {len(out.get('skipped') or [])} skipped")
                res = out

            elif name in EVIDENCE_TOOLS:
                if evidence_calls >= settings.sub_analyst_evidence_calls:
                    res = {"error": "analyst_budget",
                           "detail": f"you have used this analyst's {settings.sub_analyst_evidence_calls} evidence "
                                     f"calls; file your brief with what you have and say what is missing in not_done"}
                else:
                    evidence_calls += 1
                    raw = await ctx.tools_session.call(name, args)
                    raw = raw if isinstance(raw, dict) else {"error": "tool_transport_error", "detail": str(raw)[:200]}
                    res = dg.render(raw, mint=minter, seen=seen, cap=settings.sub_analyst_result_chars)
                    minted = minter.take()
                    if minted:
                        # SHOWN MEANS ON THE LEDGER. The desk's own words for what
                        # it could not do are quotable only if they are recorded
                        # (round G refused an analyst for quoting one).
                        await _record(ctx, actor, "digest", "digest", {"of": name},
                                      f"{len(minted)} boundary fact(s) stated", facts=minted)

            elif name == dl.SUBMIT_TOOL_NAME:
                try:
                    brief, report = dl.parse_submission(args)
                except dl.BadDelegation as exc:
                    res = {"accepted": False, "error": "malformed_submission", "detail": str(exc)}
                else:
                    attempts += 1
                    led = await _ledger(ctx)
                    verdict = dl.handoff_check(task, brief, report, led)
                    await _record(ctx, actor, "brief", "submit",
                                  {"brief": brief, "report": {**report, "text": report["text"][:4000]},
                                   "coverage": verdict.coverage},
                                  ("accepted" if verdict.ok else
                                   f"refused: {len(verdict.problems)} problem(s); "
                                   f"{(verdict.problems[0] or {}).get('reason')}"),
                                  status="completed" if verdict.ok else "rejected")
                    _fill(result, task, brief, report, verdict)
                    if verdict.ok or attempts >= 2:
                        result.cost = {"completions": completions, "evidence_calls": evidence_calls}
                        done = True
                        res = {"accepted": verdict.ok, "coverage": verdict.coverage}
                    else:
                        standing = verdict
                        res = {"accepted": False, "refusal": dl.refusal_message(task, verdict)}

            else:
                res = {"error": "unknown_tool",
                       "detail": f"your tools are compile, {', '.join(EVIDENCE_TOOLS)} and submit"}

            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": ejson.dumps_capped(res, settings.sub_analyst_result_chars)})
        if done:
            break

    if not result.findings and not result.not_done:
        # No brief at all: the lead is told which lines went unanswered and why,
        # in the same shape a refused line takes, rather than an empty result it
        # has to interpret.
        text = ("the domain analyst did not file a brief within its turns"
                if completions >= settings.sub_analyst_max_turns
                else "the domain analyst stopped without filing a brief")
        entry, fact = dg.boundary(text, want=list(task.want_to_know), subject=task.subjects[0], cls="error")
        await _record(ctx, actor, "brief", "submit", {"task_id": task.task_id}, text, facts=[fact], status="rejected")
        result.status = "refused"
        result.not_done = [{"want": i, "why": text, "boundary": fact.id} for i in range(1, len(task.want_to_know) + 1)]
        result.coverage = {"asked": len(task.want_to_know), "done": 0,
                           "not_done": len(task.want_to_know), "refused": 0}
    result.cost = result.cost or {"completions": completions, "evidence_calls": evidence_calls}
    return result


def _fill(result: dl.AnalystResult, task: dl.Task, brief: dict, report: dict, verdict: dl.HandoffVerdict) -> None:
    """What survives the check reaches the lead; what did not is named as
    refused. A brief that half passes is half a brief, not a lost one — the lead
    can still answer the lines that came back."""
    result.findings = list(verdict.accepted)
    result.not_done = list(brief.get("not_done") or [])
    result.caveats = list(brief.get("caveats") or [])
    result.follow_ups = list(brief.get("follow_ups") or [])
    result.refused = list(verdict.rejected)
    result.coverage = verdict.coverage
    rv = verdict.report_verdict
    result.report = {**report, "status": "verified" if (rv is not None and rv.ok) else "refused",
                     "problems": [] if (rv is not None and rv.ok) else [p for p in (rv.problems if rv else [])],
                     "verdict": rv}
    if verdict.ok:
        result.status = "verified"
    elif result.findings or result.not_done:
        result.status = "partial"
    else:
        result.status = "refused"


async def run_tasks(tasks: list[dl.Task], ctx: TurnContext) -> list[dl.AnalystResult]:
    """Every task of one delegate call. Serial until Phase 3: the three things
    parallelism needs — seq allocation under a lock, a concurrency-tested MCP
    session, a per-analyst budget — are measured before they are assumed."""
    settings = get_settings()
    if settings.parallel_analysts and len(tasks) > 1:
        import asyncio
        return list(await asyncio.gather(*(run_sub_analyst(t, ctx) for t in tasks)))
    out: list[dl.AnalystResult] = []
    for task in tasks:
        out.append(await run_sub_analyst(task, ctx))
    return out
