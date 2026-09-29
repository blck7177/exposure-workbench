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

import copy
import json
import logging
from typing import Sequence

from sqlalchemy import update

from exposure_workbench.agents import delegation, delivery, repeats as rp, sub_analyst
from exposure_workbench.agents.llm_session import llm_session
from exposure_workbench.agents.tool_session import tool_session
from exposure_workbench.analytics import handbook
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import AgentMessage, AgentSession
from exposure_workbench.services import analysis_state as AS, analyst_reports, answer_check, \
    briefing as briefing_svc, context_budget, fact_boundary, facts as F, ledger as ledger_svc, style_guide, \
    trace_service
from exposure_workbench.utils import json as ejson
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

# THE ROLE, and then the desk's style guide, ONCE (V1 step 6). How a figure is cited and how a
# statement stands — the id in brackets, the superlative's ordering, quotation marks, the caveat, what
# is never written — was told here in the role's own words and again in the analysts' and in a tool
# schema; the rules' text lives in services/style_guide now, and this role says only what is the lead's.
_ROLE = """You are the lead analyst of a portfolio risk & issuer-intelligence desk, and the one the user talks to. \
The analysis is your job: take the question apart, decide what has to be known to answer it, ask the desk's analysts for \
it, and say what it shows and what it means for the question asked — its implication for this book and what would change \
your reading.

You pull no figure yourself. The desk has three analysts, each reading one family of evidence, and the ROSTER says what \
each answers, what it can be asked for and what is absent there. `ask` is how you ask: pick the analyst by the evidence a \
line turns on, name the subjects from the DESK block — or a book an analyst built this turn, by its id — and write what you \
want to know as short, separate lines, one thing per line, in financial language: say the period, and say what is set \
against what where the line is a comparison. Ask independent work together; read a prerequisite result before asking \
work that depends on it. Ask again only for \
what the answer still lacks. Check the question's premises against the DESK block first (which holdings are in which sector, \
what the desk holds): a premise the user asserts is checked against the desk's figure and corrected with it before the \
question is answered, and one the desk holds no figure for is neither agreed with nor denied. Keep the user's original \
question in view as you learn and revise what you ask. The STATE block holds the checked findings with their evidence, \
what was tried, actual failures and your remaining budget. An ask returns a receipt; read the results in STATE. Open \
another page using its id and next_offset when needed. Neither an accepted finding nor a tool's refusal settles the \
whole question by itself. Decide what the evidence supports, what still needs work, and explain any remaining limits \
in your answer.

What comes back is, for each numbered line, one of three things: a finding with the desk's rows under it; why the line \
could not be settled, with the desk's own row that says so; or that the analyst's finding did not pass the desk's check. A \
row says what it is, whose, over what period, the value, what it means and where it came from, under its id. The READINGS \
block says what the desk's readings mean in finance, and the implication you write rests on it. A caveat comes back on the \
line it qualifies. `open` reads anything already on the record — a row, the rows of one call, an analyst's log of what it \
did and why, a book a scenario built; it cannot pull a new figure.

Your reply is plain prose, written to the desk's style guide below. A table or a chart is [table: <id>] or [chart: <id>], \
naming the call whose rows it shows.

If your reply is not accepted, you are told which sentences did not pass and why. Call repair_answer with a replacement for \
exactly those sentences (an empty replacement drops one); ask first if a fix needs a figure you were not shown. You have two \
attempts."""

_SYSTEM = _ROLE + "\n\n" + style_guide.text()


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
# V2 P1.3 (design v0.4 G3): `open` reads a call's rows a page at a time and says
# the total and the range, instead of the first 80 with nothing said of the rest.
OPEN_PAGE_ROWS = 80

# The rewrites an answer gets: the first refusal lists every problem, the
# second ends the turn. Decided 2026-09-13 with the natural-language exit.
MAX_ANSWER_ATTEMPTS = 2

# The lead's own tools. Kept as a tuple for the tests that pin the budget-free
# names: not one of them retrieves anything — `delegate` hands work to an
# analyst whose evidence calls are charged where they happen.
_BUDGET_FREE_TOOLS = (delegation.ASK_TOOL_NAME, delegation.OPEN_TOOL_NAME, "repair_answer")

_WRITE_OR_ASK = "Write the answer, or ask for the evidence you still need."

# THE TWO BLOCKS PUSHED TO THE LEAD (V37/A3). Each was a one-line heading over raw
# JSON, which leaves the reading of a block to the field names inside it — and a
# field nobody is told about is a field nobody reads (delegation.FOR_THE_LEAD_TO_
# READ). A tag with `source` and `use` is what the current prompting guidance asks
# for when one prompt mixes instructions, context and variable input, which this
# one does. Named rather than inlined so the wording sheet reads the same object
# the turn sends (scripts/v36_wording.py), and so a reviewer has one thing to read.
BRIEFING_TAG = ('<desk source="the desk\'s catalogue" trust="names, dates and coverage only — no figure here may '
                'be stated until an analyst returns it" use="pick the subjects; check the question\'s premises">')
ROSTER_TAG = ('<roster source="the desk\'s handbook" use="pick the analyst by the evidence a line turns on, not by the '
              'words of the question; each entry says what it answers, what it can be asked for and what is absent there">')
# V1: THE MEANING LAYER. The lead was forbidden the desk's vocabulary and lost its
# finance with it — what a reading MEANS sat in the same domain text as the key it
# was read under. The handbook holds the two apart; the lead is given the meaning.
READINGS_TAG = ('<readings source="the desk\'s handbook" use="what the desk\'s readings mean in finance, and what the '
                'desk does not say: write implications from these, never a figure">')
# One current work view. Execution records and checked findings are not a
# semantic completion certificate; the original question stays in the view.
STATE_TAG = ('<state source="the desk\'s execution record and checked findings" '
             'trust="checked findings and evidence; task requests are instructions, not facts" '
             'use="decide the next step against the original question; read more with open(id, offset)">')

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
                    "as you wrote it. An empty text drops the sentence. Ask first if a fix needs a figure you were not "
                    "shown."),
    "parameters": {"type": "object", "properties": {
        "replacements": {"type": "array", "minItems": 1, "items": {
            "type": "object", "properties": {"tag": {"type": "string", "description": "S1, S2, …"},
                                             "text": {"type": "string", "description": "the sentence as it should read; empty drops it"}},
            "required": ["tag", "text"], "additionalProperties": False}}},
        "required": ["replacements"], "additionalProperties": False}}}
_REPAIR_ONLY = ("A verdict stands on your reply: call repair_answer with replacements for the sentences named, "
                "or ask for what a fix needs. A new reply is not read.")


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


def _page(items: list, offset: int, size: int, key: str) -> dict:
    """One page of a long list, with the total and the range, and where the next
    page starts while there is one (V2 P1.3). Nothing is dropped in silence."""
    start = max(0, int(offset or 0))
    page = items[start:start + size]
    if not page:
        return {"error": "past_the_end", "detail": f"offset {start} is past the end: {len(items)} {key} in all"}
    out = {key: page, "total": len(items), "shown": [start, start + len(page)]}
    if start + len(page) < len(items):
        out["next_offset"] = start + len(page)
    return out


async def _open(db_factory, session_id: str, ref: str, delegated: list, offset: int = 0,
                state: AS.State | None = None, work_views: dict | None = None) -> dict:
    """ANYTHING ALREADY ON THE RECORD, BY ITS ID (V1): a row, the rows one call
    pulled, an analyst's log, a book a scenario built, or a work-view page. It reads the session's own
    ledger and its analysts' records — nothing here can pull a figure nobody
    pulled, which is the whole of the lead's relation to the desk's data.

    `offset` (V2 P1.3) reads on: a call's rows come OPEN_PAGE_ROWS at a time, a
    series' points SERIES_POINTS_INLINE at a time, each page saying the total,
    the range it shows and where the next one starts."""
    ref = (ref or "").strip()
    if not ref:
        return {"error": "no_id", "detail": "open takes the id of a row (f_…), a call (r_…), a task, or a built book (calc_…)"}
    if ref.startswith("ast_"):
        if ref in (work_views or {}):
            snapshot, ledger = work_views[ref]
            return AS.view(snapshot, ledger, offset=offset)
        if state is None or ref != state.id:
            return {"error": "unknown_state", "detail": "open the current STATE id; other analysis records are not exposed"}
        return AS.view(state, await _load_ledger(db_factory, session_id), offset=offset)
    if ref.startswith("tsk_"):
        mine = next((r for r in delegated if r.task.task_id == ref), None)
        if mine is not None:
            return {"log": delegation.log_text(mine)}
        try:
            async with db_factory() as db:
                rep = await analyst_reports.load_by_task(db, session_id, ref)
        except Exception:  # noqa: BLE001
            logger.exception("could not open the log of %s", ref)
            return {"error": "unavailable", "detail": "the desk could not open that log"}
        return {"log": rep["text"]} if rep else {"error": "unknown_task",
                                                 "detail": f"{ref} is not a task of this conversation"}
    led = await _load_ledger(db_factory, session_id)
    if ref.startswith("f_"):
        rec = led.by_id.get(ref)
        if not rec:
            return {"error": "not_on_the_record", "detail": f"{ref} is not a row this conversation was shown"}
        out: dict = {"row": F.line(rec)}
        points = [[str(p[0]), p[1]] for p in (rec.get("points") or []) if isinstance(p, (list, tuple)) and len(p) == 2]
        if rec.get("kind") == F.SERIES and len(points) > F.SERIES_POINTS_INLINE:
            # the row shows a thinned series; the record holds every point, and here they are, paged
            paged = _page(points, offset, F.SERIES_POINTS_INLINE, "points")
            return paged if paged.get("error") else {"id": ref, **out, **paged}
        return out
    if ref.startswith(("r_", "calc_")):
        rows = [F.line(r) for r in led.shown.values()
                if ref in ((r.get("params") or {}).get("pull"), r.get("subject"), *(r.get("sources") or []),
                           (r.get("params") or {}).get("of"), (r.get("params") or {}).get("book"))]
        if not rows:
            return {"error": "not_on_the_record", "detail": f"no row of this conversation came from {ref}"}
        return {"id": ref, **_page(rows, offset, OPEN_PAGE_ROWS, "rows")}
    return {"error": "unknown_id", "detail": "open takes the id of a row (f_…), a call (r_…), a task, or a built book (calc_…)"}


async def _record_delegate(db_factory, session_id: str, message_id: str, tasks) -> None:
    """The lead's half of the handoff, as a step. The analysts record their own;
    without this one the trace shows work appearing with nobody having asked."""
    try:
        async with db_factory() as db:
            await trace_service.record_step(
                db, session_id, step_type="delegate", tool_name="ask",
                args={"tasks": [t.as_dict() for t in tasks]}, evidence_refs=[],
                result_summary="; ".join(f"{t.analyst} [{','.join(t.subjects)}] {len(t.lines)} line(s)"
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
                db, session_id, step_type="delegate", tool_name="ask",
                args={"raw": ejson.dumps_capped(args, 2000)}, evidence_refs=[],
                result_summary=f"invalid_delegation: {detail[:300]}", status="rejected", message_id=message_id)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record the rejected delegate step for %s", session_id)


async def _record_open(db_factory, session_id: str, message_id: str, ref: str, result: dict, offset: int = 0) -> None:
    """The lead opening something on the record, as a step."""
    try:
        async with db_factory() as db:
            await trace_service.record_step(
                db, session_id, step_type="open", tool_name="open",
                args={"id": ref, **({"offset": offset} if offset else {})}, evidence_refs=[],
                result_summary=(f"{result.get('error')}: {str(result.get('detail') or '')[:160]}" if result.get("error")
                                else f"{len(result.get('rows') or [])} row(s) of {result.get('total')}, "
                                     f"shown {result.get('shown')}" if "rows" in result
                                else f"a row, {len(result.get('points') or [])} of {result.get('total')} points" if "points" in result
                                else f"work view: {result.get('total')} cards, shown {result.get('shown')}" if ref.startswith("ast_")
                                else "a row" if "row" in result else "a log"),
                status="rejected" if result.get("error") else "completed", message_id=message_id)
            await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("could not record the open step for %s", session_id)


async def _record_answer(db_factory, session_id: str, message_id: str, text: str, verdict) -> None:
    try:
        async with db_factory() as db:
            # EVERY PROBLEM, not the first: the summary below names one reason, and a round that
            # counts refusals by kind — how many sentences contradicted the word on their row —
            # read only the ones that happened to come first (V1 step 7). The brief step has
            # always kept its list; this keeps the answer's, by reason and sentence.
            named = [{k: p[k] for k in ("reason", "rule", "sentence") if p.get(k) is not None}
                     for p in (getattr(verdict, "problems", None) or [])[:40]]
            # THE WHOLE DRAFT (V2 P0a). A refused reply lives only on this step — the
            # accepted one is agent_messages.content — and round E reads refusals
            # back in full; text[:4000] cut long drafts short of what was refused.
            await trace_service.record_step(
                db, session_id, step_type="answer", tool_name="answer",
                args={"text": text, **({"problems": named} if named else {})},
                result_summary=("accepted" if verdict.ok else f"refused: {verdict.error}; {verdict.detail}"),
                evidence_refs=[], status="completed" if verdict.ok else "rejected", message_id=message_id,
                unbounded=("text",))
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
            line = "      " + (f"rule {p['rule']} — " if p.get("rule") else "") + p["reason"] + (f" ({what!r})" if what else "")
            if p.get("way_out"):
                line += f": {p['way_out']}"
            if p.get("candidates"):
                line += " — the desk showed: " + "; ".join(
                    f"{c.get('measure')} {c.get('subject')} {c.get('as_of')} [{c.get('id')}]" for c in p["candidates"][:4])
            lines.append(line)
    other = [p for p in verdict.problems if not p.get("sentence")]
    for p in other[:6]:
        lines.append(f"      {p['reason']}: {p.get('way_out') or p.get('detail') or ''}")
    lines += ["", "Call repair_answer with a replacement for each tag above (an empty text drops the sentence). "
                  "Ask for the evidence you lack first if a fix needs a figure you were not shown."]
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


async def _open_state(db_factory, session_id: str, message_id: str, question: str, brief: dict) -> AS.State:
    """This turn's analysis state, inheriting from the session's last one what is
    still inside scope (V2 P3). The record is owed but the turn is not: a database
    that cannot be read or written leaves an unsaved state in memory and a line in
    the log, never a lost turn."""
    previous = None
    try:
        async with db_factory() as db:
            previous = await AS.load_latest(db, session_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not read the analysis state of %s", session_id)
    led = await _load_ledger(db_factory, session_id)
    state = AS.new_turn(session_id, message_id, question, brief if isinstance(brief, dict) else {}, previous, ledger=led)
    await _save_state(db_factory, state)
    return state


async def _save_state(db_factory, state: AS.State) -> None:
    try:
        async with db_factory() as db:
            await AS.save(db, state)
            await db.commit()
    except AS.StaleState:
        # A conflicting record must be reconciled by its owner. Never borrow its
        # version to overwrite it with this turn's stale contents.
        raise
    except Exception:  # noqa: BLE001
        logger.exception("could not save the analysis state of %s", state.session_id)


def _state_block(state: AS.State, led) -> str:
    return STATE_TAG + "\n" + json.dumps(AS.view(state, led), ensure_ascii=False, default=str) + "\n</state>"


async def handle_message(
    db_factory,
    session_id: str,
    user_text: str,
    max_turns: int = 16,
    deny: Sequence[str] = (),
    message_id: str | None = None,
) -> dict:
    """Run one user turn. Persists the user + assistant messages; returns the reply.

    `message_id` (V2 P0a) lets the caller mint the turn's id before the loop runs, so a
    turn that dies in an exception still has an id its steps hang off and the caller
    can name in its own record of the failure. None keeps the old behaviour."""
    message_id = message_id or new_id("msg_")
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
                             BRIEFING_TAG + "\n" + json.dumps(briefing_svc.for_lead(brief), ensure_ascii=False, default=str)
                             + "\n</desk>"}]
    # WHO CAN BE ASKED WHAT, AND WHAT THE READINGS MEAN. Three analysts, from the
    # handbook (analytics/handbook): the roster carries no measure, no verb and no
    # figure; the readings carry the finance the lead writes implications from.
    roster = handbook.roster()
    messages.append({"role": "system", "content":
                     ROSTER_TAG + "\n" + json.dumps(roster, ensure_ascii=False) + "\n</roster>"})
    messages.append({"role": "system", "content": READINGS_TAG + "\n" + handbook.meaning_layer() + "\n</readings>"})
    # V2 P3: the state, projected from the record and refreshed before every completion
    # (one block in the array, replaced in place, never appended to)
    state = await _open_state(db_factory, session_id, message_id, user_text, brief)
    led = await _load_ledger(db_factory, session_id)
    messages.append({"role": "system", "content": _state_block(state, led)})
    state_at = len(messages) - 1
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
    handed: set[str] = set()               # every row id a completion of this turn was handed (V2 P3)
    # One immutable projection per completion, bounded by max_turns. Opening a
    # page changes receipt diagnostics; it must not shift the cursor being read.
    # These snapshots are turn-local, not a new persisted state store.
    work_views: dict = {}

    # THE LEAD HOLDS NO TOOL FACE (V1). Each analyst opens the mount of its own
    # family for its own task, on this turn's session and message, so what it pulls
    # lands on the ledger the answer check reads (D3).
    user_id = current_user_id()

    def _open_tools(face: str):
        return tool_session(face, session_id=session_id, user_id=user_id, message_id=message_id, deny=deny)

    async with llm_session(db_factory, session_id, message_id) as llm:
        ctx = sub_analyst.TurnContext(open_tools=_open_tools, llm=llm, db_factory=db_factory,
                                      session_id=session_id, message_id=message_id, briefing=brief,
                                      state_version=state.version, question=user_text)

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
        read = delivery.Delivered()                # what the next completion reads, and the ids in it (V36.1, V2 P2)

        def _append(msg: dict) -> None:
            messages.append(msg)
            read.add(msg)

        for _turn in range(max_turns):
            # while a verdict stands the turn is a tool call: a repair or a delegation
            tools = ([delegation.ASK_TOOL]
                     + ([delegation.OPEN_TOOL] if delegated or led.shown or state.findings or state.gaps else [])
                     + ([REPAIR_TOOL] if standing is not None else []))
            state.budget = {"lead_completions_used": completions, "lead_completions_limit": max_turns}
            AS.mark_delivery_missing(state, led, handed | read.facts)
            snapshot = copy.deepcopy(state)
            snapshot.id = f"{state.id}_view{completions}"
            work_views[snapshot.id] = (snapshot, led)
            messages[state_at] = {"role": "system", "content": _state_block(snapshot, led)}
            read.project(messages)
            prompt_peak = max(prompt_peak, context_budget.count_prompt(messages, tools))
            content, tool_calls = await llm.chat(messages=messages, tools=tools, note=read.note(),
                                                 **({"tool_choice": "required"} if standing is not None else {}))
            handed |= read.facts
            AS.mark_delivery_missing(state, led, handed)
            read.reset()
            completions += 1
            assistant_msg: dict = {"role": "assistant", "content": content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if tool_calls:
                ended = False
                for tc in tool_calls:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"].get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    if name == delegation.ASK_TOOL_NAME:
                        try:
                            tasks = delegation.parse_tasks(args, new_id)
                        except delegation.BadDelegation as exc:
                            result: dict = {"error": "invalid_ask", "detail": str(exc)}
                            await _record_bad_delegate(db_factory, session_id, message_id, args, str(exc))
                        else:
                            AS.start_tasks(state, tasks)
                            await _save_state(db_factory, state)
                            ctx.state_version = state.version
                            await _record_delegate(db_factory, session_id, message_id, tasks)
                            got = await sub_analyst.run_tasks(tasks, ctx)
                            delegated += got
                            # the rows under each finding are read off the ledger, by id
                            led = await _load_ledger(db_factory, session_id)
                            result = delegation.for_lead(got, led)
                            # V2 P3: the record moves — checked lines in, gaps typed, delivery and
                            # conflicts recomputed — and the STATE block is rebuilt from it next
                            for task, r in zip(tasks, got):
                                AS.merge_task(state, task, r, led)
                            AS.mark_delivery_missing(state, led, handed)
                            AS.conflicts(state, led)
                            await _save_state(db_factory, state)
                    elif name == delegation.OPEN_TOOL_NAME:
                        ref = str((args or {}).get("id") or "")
                        try:
                            offset = int((args or {}).get("offset") or 0)
                        except (TypeError, ValueError):
                            offset = 0
                        result = await _open(db_factory, session_id, ref, delegated, offset,
                                             state=state, work_views=work_views)
                        await _record_open(db_factory, session_id, message_id, ref, result, offset)
                    elif name == REPAIR_TOOL_NAME and standing is not None:
                        repl, unknown = _parse_replacements(args, standing)
                        led = await _load_ledger(db_factory, session_id)
                        text = answer_check.repair(answer, standing, repl) if repl else answer
                        verdict = fact_boundary.check_text("answer", text, led, question=user_text)
                        await _record_answer(db_factory, session_id, message_id, text, verdict)
                        if verdict.ok:
                            acc = answer_check.accepted(text, verdict, led)
                            reply_text, reply_citations = acc["text"], acc["citations"]
                            reply_verified, reply_blocks = acc["verified"], acc["blocks"]
                            result = {"accepted": True}
                        else:
                            again = repeated.record({"text": text})
                            if again > rp.STOP:
                                # THE SECOND REPEAT ENDS THE TURN HERE TOO (V38/A-R1),
                                # not just this loop over tool calls. With one attempt
                                # spent the lead used to be asked again, this call left
                                # without its tool message, and the provider refused
                                # the request: round C's Q13 ended in a 400 and the
                                # reader got no reply. Nothing is asked after this.
                                gate_refusals.append("repeated_answer")
                                answer, standing = text, verdict
                                ended = True
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
                                  "detail": f"your tools are {delegation.ASK_TOOL_NAME}, {delegation.OPEN_TOOL_NAME} and "
                                            f"{REPAIR_TOOL_NAME}; the answer is your reply text"}
                    # Work-view pages are already bounded by whole cards. A generic
                    # character cap could separate a finding from its caveat.
                    _append({"role": "tool", "tool_call_id": tc["id"],
                             "content": (json.dumps(result, ensure_ascii=False) if name == delegation.OPEN_TOOL_NAME
                                         and result.get("id") in work_views else ejson.dumps_capped(result, TOOL_RESULT_LIMIT))})
                if ended or reply_text is not None or attempts >= MAX_ANSWER_ATTEMPTS:
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
            verdict = fact_boundary.check_text("answer", text, led, question=user_text)
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

    # S1: the runtime records delivery, not semantic completeness. Keep the
    # nullable legacy column for historical readers; do not infer a verdict.
    state.completion = None
    state.budget = {"lead_completions_used": completions, "lead_completions_limit": max_turns}
    await _save_state(db_factory, state)

    meta: dict = {"prompt_tokens": prompt_peak, "completions": completions,
                  "protocol": "simplified-s1", "completion": None, "state_version": state.version,
                  "delivery": "answered" if reply_text is not None else "not_answered",
                  "delegations": [{"domain": r.task.domain, "task_id": r.task.task_id, "status": r.status,
                                   "coverage": r.coverage, "cost": r.cost} for r in delegated],
                  # the page's report chip: `verified` is its word for a brief that passed
                  "reports": [{"domain": r.task.domain, "report_id": r.report_id,
                               "status": "verified" if r.status in ("settled", "partial", "unsettled") and not r.refused
                                         else "refused",
                               "title": f"the {r.task.analyst} analyst on {', '.join(r.task.subjects)}"}
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
