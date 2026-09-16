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

from exposure_workbench.agents import delegation as dl, repeats as rp
from exposure_workbench.services import answer_check
from exposure_workbench.analytics import skill
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.services import analyst_reports, digest as dg, facts as F, ledger as ledger_svc, \
    program_builder as pb, program_service as ps, trace_service
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

# The evidence tools a domain analyst may reach, by name off the face. `compile`
# and `submit` are in-process and are not on any face: one retrieves nothing and
# the other is the analyst's exit.
EVIDENCE_TOOLS = ("run", "read_filings", "search_web", "start")
# Of those, the ones that return evidence. `start` is on the face and reachable,
# and is counted apart (V36.1): it returns a task id, never a figure.
_EVIDENCE_BUDGETED = ("run", "read_filings", "search_web")

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
read_filings reads a filing's text, search_web the web; start puts an issuer on the desk after your turn — it \
returns a task id, never a figure, and once per name is enough. A subject written as a calc_… id is a book \
another analyst built this turn — the scenario after a trade: read it where a run goes, never the base book in \
its place. Every figure a tool shows you \
carries the id it is shown under — 16.0% [f_2592baab170e] — and `place` of `of` is where it sits in the ordering its \
node built: a superlative rests on that, never on reading a list. Never compute in your head: a number you worked out \
yourself is a number no fact stands behind, and it is refused.

The brief is one entry per numbered line, and an entry is one of two things. Settled: the ids it rests on and \
one to three sentences with every figure written exactly as the desk showed it, bracket included. Not settled: `why`, \
one line in your words, and the id of the boundary the desk stated — its own words travel with that id, so `why` is a \
reading, not a quotation. Never both for one line; never an estimate, never a nearby figure under the asked-for name. What you had to assume or leave out goes in caveats; the lead states those to the reader. The report is \
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
        elif s.startswith("calc_"):
            # a book another analyst built this turn (V36.1): not in the
            # briefing, because it did not exist when the briefing was written
            out[s] = {"kind": "scenario", "note": "a book built this turn by another analyst; read it where a "
                                                  "run goes: column(run=id, …), figure(run=id, …), sell(run=id, …)"}
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
    start_calls = 0
    started: dict[tuple[str, str], str] = {}            # (kind, subject) -> the task it enqueued
    made: dict[str, dict] = {}                          # the books this analyst's programs built, by id
    shown_series: dict[str, dict] = {}                  # the series it was shown, by id (V37/T2)
    completions = 0
    llm = ctx.llm.for_actor(actor) if hasattr(ctx.llm, "for_actor") else ctx.llm

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM.format(domain=task.domain)
         + "\n\nDOMAIN " + (skill.system_text(procedure) if procedure else task.domain)
         + "\n\nTHE LANGUAGE\n" + ps.signature_text()
         # V37/T5: the citing rule is standing knowledge. It rode on every tool
         # result — 726 characters that `book_market_risk` read nine times in one
         # turn of round B — which dilutes the reading and breaks the prompt's
         # stable prefix without saying anything new.
         + "\n\nHOW EVERY RESULT IS READ\n" + dg.HOW_TO_CITE},
        {"role": "user", "content": json.dumps(
            {"task": task.as_dict(), "subjects": _subjects_of(task, ctx.briefing),
             "boundaries": list(ps.BOUNDARIES)}, ensure_ascii=False, default=str)},
    ]
    tools = [COMPILE_TOOL] + _face_tools(ctx.tools_session) + [dl.SUBMIT_TOOL]
    standing: dl.HandoffVerdict | None = None           # a verdict on a submission, awaiting its replacement
    attempts = 0
    nudges = 0
    read = {"chars": 0, "results": 0}                   # what the next completion reads (V36.1, recorded on its row)
    # A PROGRAM RE-SENT UNCHANGED IS NOT A SECOND TRY (V37/A2, the V31 rule).
    # Given the same program the type report is the same report, and it cost a
    # slot of this analyst's eight evidence calls to read it again: round B's Q08
    # sent one program four times, two of them byte for byte, and the turn ended
    # with no answer. The repeat is answered from what the desk already said, told
    # that it repeated itself, and NOT charged — the budget counts calls that could
    # bring something back, and a repeat cannot. One byte's difference is a new
    # program, however many times it is sent.
    sent = rp.Repeats()
    last: dict[str, dict] = {}                         # payload digest -> the result it got

    def _append(msg: dict) -> None:
        messages.append(msg)
        read["chars"] += len(str(msg.get("content") or ""))
        read["results"] += int(msg.get("role") == "tool")

    for _turn in range(settings.sub_analyst_max_turns):
        content, tool_calls = await llm.chat(
            messages=messages, tools=tools, note=({"read": dict(read)} if read["chars"] else None),
            **({"tool_choice": "required"} if standing is not None else {}))
        read = {"chars": 0, "results": 0}
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
        # ONE COMPLETION'S READING IS BOUNDED (V37/T5). The cap was per RESULT, so
        # three calls in one completion could hand it 48k characters: round B did
        # 43.5k once and answered with three tokens, and five of its empty replies
        # came straight after a read of more than 9k. The budget is the
        # completion's, shared by the results it will read, with a floor so a
        # single call is never starved.
        room = max(4_000, settings.sub_analyst_result_chars // max(1, len(tool_calls)))
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

            elif name == "start":
                # A START IS NOT EVIDENCE. It enqueues work that finishes after
                # the turn and returns an id, never a figure. Round A's Q14 spent
                # its whole evidence budget starting readiness for eight held
                # names and filed nothing; Q04 started the same name four times.
                # Counted apart, and once per subject: the same start twice is
                # the same task, answered here without a second enqueue.
                key = (str(args.get("kind") or ""), str(args.get("subject") or "").upper())
                if key in started:
                    res = {"already_started": started[key], "kind": key[0], "subject": key[1],
                           "detail": "you started this already; it runs after your turn and does not return to you "
                                     "— file your brief with what you have and put it in follow_ups"}
                elif start_calls >= settings.sub_analyst_start_calls:
                    res = {"error": "analyst_budget",
                           "detail": f"you have started {settings.sub_analyst_start_calls} background tasks; none of "
                                     f"them returns within your turn — file your brief and put the rest in follow_ups"}
                else:
                    start_calls += 1
                    raw = await ctx.tools_session.call(name, args, actor=actor)
                    raw = raw if isinstance(raw, dict) else {"error": "tool_transport_error", "detail": str(raw)[:200]}
                    res = dg.render(raw, mint=minter, seen=seen, cap=room,
                                    call={"tool": name, "args": args})
                    started[key] = str(raw.get("task_id") or raw.get("run_id") or "")
                    minted = minter.take()
                    if minted:
                        await _record(ctx, actor, "boundary", name, {"of": name},
                                      f"{len(minted)} boundary fact(s) stated", facts=minted)

            elif name in _EVIDENCE_BUDGETED:
                key = rp.digest({"tool": name, "args": args})
                if key in last:
                    again = sent.record({"tool": name, "args": args})
                    res = {**last[key],
                           "repeated": (f"That {name} call was byte-identical to one this analyst already made, and the "
                                        f"desk answered it the same way. It is not charged, and it will not change: "
                                        f"change the program, or file what you have."
                                        if again <= rp.STOP else
                                        f"Sent unchanged again. The desk will not answer differently; file your brief.")}
                elif evidence_calls >= settings.sub_analyst_evidence_calls:
                    res = {"error": "analyst_budget",
                           "detail": f"you have used this analyst's {settings.sub_analyst_evidence_calls} evidence "
                                     f"calls; file your brief with what you have and say what is missing in not_done"}
                else:
                    evidence_calls += 1
                    raw = await ctx.tools_session.call(name, args, actor=actor)
                    raw = raw if isinstance(raw, dict) else {"error": "tool_transport_error", "detail": str(raw)[:200]}
                    res = dg.render(raw, mint=minter, seen=seen, cap=room,
                                    call={"tool": name, "args": args})
                    for m in res.get("made") or []:
                        made[m["id"]] = m
                    for sr in res.get("series") or []:
                        if sr.get("id") and sr["id"] not in shown_series:
                            shown_series[sr["id"]] = sr
                    minted = minter.take()
                    if minted:
                        # SHOWN MEANS ON THE LEDGER. The desk's own words for what
                        # it could not do are quotable only if they are recorded
                        # (round G refused an analyst for quoting one).
                        await _record(ctx, actor, "boundary", name, {"of": name},
                                      f"{len(minted)} boundary fact(s) stated", facts=minted)
                    sent.record({"tool": name, "args": args})
                    last[key] = res

            elif name == dl.SUBMIT_TOOL_NAME and standing is not None and rp.digest(args) in last:
                # THE SAME SUBMISSION AGAIN (V37/A2). The check returns the same
                # verdict on the same brief, and hearing it twice is not the repair
                # it asked for. Answered from the verdict that already stands, and
                # not counted as the attempt it is not.
                res = {"accepted": False, "refusal": dl.refusal_message(task, standing),
                       "repeated": "That submission was byte-identical to the one refused. Replace the entries "
                                   "named, or file the lines you can settle and say what stopped the rest."}

            elif name == dl.SUBMIT_TOOL_NAME:
                try:
                    brief, report = dl.parse_submission(args)
                except dl.BadDelegation as exc:
                    res = {"accepted": False, "error": "malformed_submission", "detail": str(exc)}
                else:
                    attempts += 1
                    last[rp.digest(args)] = {}
                    led = await _ledger(ctx)
                    verdict = dl.handoff_check(task, brief, report, led)
                    # the verdict rides on the step (V36.1): the retort the analyst
                    # read is otherwise nowhere on the record and had to be replayed
                    await _record(ctx, actor, "brief", "submit",
                                  {"brief": brief, "report": {**report, "text": report["text"][:4000]},
                                   "coverage": verdict.coverage,
                                   **({"problems": verdict.problems[:20]} if verdict.problems else {})},
                                  ("accepted" if verdict.ok else
                                   f"refused: {len(verdict.problems)} problem(s); "
                                   f"{(verdict.problems[0] or {}).get('reason')}"),
                                  status="completed" if verdict.ok else "rejected")
                    _fill(result, task, brief, report, verdict, led)
                    if verdict.ok or attempts >= 2:
                        result.cost = {"completions": completions, "evidence_calls": evidence_calls,
                                       "starts": start_calls}
                        result.report_id = await _store_report(ctx, actor, task, result)
                        done = True
                        res = {"accepted": verdict.ok, "coverage": verdict.coverage,
                               **({"report_id": result.report_id} if result.report_id else {})}
                    else:
                        standing = verdict
                        res = {"accepted": False, "refusal": dl.refusal_message(task, verdict)}

            else:
                res = {"error": "unknown_tool",
                       "detail": f"your tools are compile, {', '.join(EVIDENCE_TOOLS)} and submit"}

            _append({"role": "tool", "tool_call_id": tc["id"],
                     "content": ejson.dumps_capped(res, room)})
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
        # THE BOUNDARY GOES ON ITS OWN STEP, and the brief step says only that
        # none was filed. V36.1's T1 hands the lead this fact's id and its
        # words; `ledger.load` reads the facts of COMPLETED steps, and this one
        # used to ride on the `brief` step, which is rejected — so the lead was
        # invited to quote something the gate could not look up, and round B
        # lost Q10 and Q18 to exactly that (not_on_ledger, twice each, both
        # turns otherwise answerable). Every other boundary this analyst states
        # is already recorded this way: the analyst did say what stopped it,
        # which is a completed piece of work, and the brief it never filed is
        # the rejected one.
        await _record(ctx, actor, "boundary", "submit", {"of": "submit"},
                      "1 boundary fact(s) stated", facts=[fact])
        await _record(ctx, actor, "brief", "submit", {"task_id": task.task_id}, text, status="rejected")
        result.status = "refused"
        result.not_done = [{"want": i, "why": text, "boundary": fact.id, "said": fact.text}
                           for i in range(1, len(task.want_to_know) + 1)]
        # WHAT IT DID GET, HANDED OVER (V37/T2). Round B had three analysts run
        # their eight turns out and file nothing — one of them after nine tool
        # calls — and all the lead was told is "did not file a brief within its
        # turns". Those figures are on the ledger and the lead may write them; the
        # most expensive part of the turn used to fall on the floor. It is not a
        # brief and is not offered as one: no line is claimed answered.
        result.shown = ([{k: v for k, v in f.items() if k in
                          ("value", "subject", "measure", "as_of", "place", "of", "node", "unit")}
                         for f in list(seen.values())[:40]]
                        + [{k: v for k, v in sr.items() if k in
                            ("id", "subject", "measure", "spacing", "span", "n", "first", "last")}
                           for sr in list(shown_series.values())[:10]])
        result.coverage = {"asked": len(task.want_to_know), "done": 0,
                           "not_done": len(task.want_to_know), "refused": 0}
    result.cost = result.cost or {"completions": completions, "evidence_calls": evidence_calls, "starts": start_calls}
    result.made = list(made.values())
    return result


async def _store_report(ctx: TurnContext, actor: str, task: dl.Task, result: dl.AnalystResult) -> str | None:
    """The analyst's reading, on the record.

    A refused report is stored too, marked, with its problems and without its
    blocks: dropping it would lose what was tried, and showing its prose as if
    it had passed is the one thing the store must not do."""
    rep = result.report or {}
    try:
        async with ctx.db_factory() as db:
            report_id = await analyst_reports.store(
                db, ctx.session_id, message_id=ctx.message_id, task_id=task.task_id, domain=task.domain,
                status=rep.get("status", "refused"), title=rep.get("title"),
                brief={"findings": result.findings, "not_done": result.not_done, "caveats": result.caveats,
                       "follow_ups": result.follow_ups, "refused": result.refused},
                text=rep.get("text"), blocks=rep.get("blocks") or [], citations=rep.get("citations") or [],
                verified=rep.get("verified") or {}, problems=rep.get("problems") or [],
                evidence_calls=result.cost.get("evidence_calls"))
            await db.commit()
    except Exception:  # noqa: BLE001 — a lost record beats a lost turn
        logger.exception("could not store the report for %s in session %s", task.domain, ctx.session_id)
        return None
    await _record(ctx, actor, "report", "report", {"report_id": report_id, "status": rep.get("status")},
                  f"{rep.get('status')}: {str(rep.get('title') or '')[:120]}")
    return report_id


def _said(ledger, fid: str | None) -> str | None:
    """The desk's words behind a boundary id, if the ledger holds them."""
    rec = (getattr(ledger, "by_id", None) or {}).get(fid) if fid else None
    if not rec or rec.get("kind") != F.ABSENCE:
        return None
    text = rec.get("text") if isinstance(rec.get("text"), str) else None
    return text or None


def _with_said(entry: dict, ledger) -> dict:
    said = _said(ledger, entry.get("boundary"))
    return {**entry, "said": said} if said else dict(entry)


def _with_desk_said(finding: dict, ledger) -> dict:
    """A finding that cites a boundary carries the boundary's words beside it."""
    said = [{"id": fid, "said": s} for fid in (finding.get("facts") or []) if (s := _said(ledger, fid))]
    return {**finding, "desk_said": said} if said else dict(finding)


def _fill(result: dl.AnalystResult, task: dl.Task, brief: dict, report: dict, verdict: dl.HandoffVerdict,
          ledger=None) -> None:
    """What survives the check reaches the lead; what did not is named as
    refused. A brief that half passes is half a brief, not a lost one — the lead
    can still answer the lines that came back."""
    # THE DESK'S OWN WORDS TRAVEL WITH THE ID. Round A lost four questions to
    # unverified_quote, every one of them the lead quoting an analyst's sentence
    # as if it were the desk's: the brief carried the analyst's `why` and a
    # boundary id, and never the boundary's text. `said` is that text, read off
    # the ledger — so what the lead can quote is what the gate can look up.
    result.findings = [_with_desk_said(f, ledger) for f in verdict.accepted]
    result.not_done = [_with_said(d, ledger) for d in (brief.get("not_done") or [])]
    result.caveats = list(brief.get("caveats") or [])
    result.follow_ups = list(brief.get("follow_ups") or [])
    result.refused = list(verdict.rejected)
    result.coverage = verdict.coverage
    rv = verdict.report_verdict
    # V36.1: a report is verified only when the WHOLE brief passed. Round A's
    # Q11 refused "nearest" twice at the handoff, the report said the same thing
    # without a figure, was stored verified, and the lead read it from there
    # (read_report) into the answer. One bar for both channels.
    ok = rv is not None and rv.ok and verdict.ok
    rendered: dict = {}
    if ok and ledger is not None:
        try:
            acc = answer_check.accepted(report.get("text") or "", rv, ledger)
            rendered = {"blocks": acc["blocks"], "citations": acc["citations"], "verified": acc["verified"]}
        except Exception:  # noqa: BLE001 — a report that will not render is a report, not a lost brief
            logger.exception("could not render the report for %s", task.domain)
    result.report = {**report, "status": "verified" if ok else "refused",
                     "problems": [] if ok else list(verdict.problems),
                     **rendered}
    # The word the lead reads has to mean what happened. The smoke round produced
    # a brief that passed every check while answering nothing — five lines, five
    # not_done — and called it "verified", which is true of the check and false
    # of the work.
    if verdict.ok and result.findings:
        result.status = "verified"
    elif verdict.ok:
        result.status = "absent"            # nothing settled, and properly said so
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
