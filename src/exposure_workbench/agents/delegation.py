"""Delegation (V1): the protocol between the lead analyst and the desk's three analysts.

The schemas of the messages that cross the boundary, and the check that reads
what comes back. No loop lives here — `agents/sub_analyst` runs an analyst,
`agents/meta_agent` runs the lead — so the shape of the conversation can be
read, and tested, without either of them.

WHO IS ASKED. Until V1 the lead chose among fourteen domains cut by question
type, every one of them holding the same tools. Now it asks one of three
ANALYSTS cut by resource family — the issuer analyst (filings), the market
analyst (prices), the portfolio risk manager (the book) — and the family is what
the analyst can reach (tools/faces), not a sentence in a prompt.

WHAT CROSSES, AND WHAT DOES NOT.
  down  `ask`: the analyst, the subjects, numbered lines of what the lead wants
        to know in financial language, one sentence of context. Not a measure's
        name, not a verb, not an id the desk did not hand over — and no field
        that invites arithmetic in words: what is compared with what is part of
        the line, and the analyst has one verb for one operation.
  up    a `Return`: for each numbered line, either the finding WITH THE ROWS IT
        RESTS ON — the fact lines themselves, attached here from the ledger by id,
        so the lead reads the desk's row and not an analyst's transcription of it
        — or why it could not be settled, with the desk's own boundary row.
        Caveats sit on the line they qualify. No legend goes with it: a row says
        what it is (services/facts.line), and each entry is one of two shapes.
  back  `open(id)`: the lead may open anything the turn put on the record — a row,
        the rows of one call, an analyst's log, a book a scenario built. It reads;
        it cannot pull a new figure.

THE BRIEF HAS NO THIRD STATE, AND THE SCHEMA SAYS SO. An entry is settled (a
finding and the ids it rests on) or it is not (why, and the id of the boundary
the desk stated) — a settled line without a fact, an unsettled one without a
boundary, or an entry that is both, never reaches the check: `parse_submission`
refuses it. An analyst always HAS a boundary to point at, because every refusal
a tool makes is a row and the three policies stand on every ledger
(tools/registry, analytics/registry.POLICY_ABSENCES).

WHY THE CHECK IS CODE. A brief that answers three of four lines reads exactly
like one that answers four, so coverage is counted here rather than trusted, and
every figure in a finding is resolved against the ledger the answer check will
read — a brief whose numbers the lead cannot cite costs the lead its turn.

THE LOG IS NOT WRITTEN. Every tool call carries `why` (tools/primitives), so an
analyst's log is its calls read in order; there is no prose report to keep in
step with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from exposure_workbench.analytics import handbook
from exposure_workbench.services import answer_check
from exposure_workbench.services import facts as F
from exposure_workbench.services import style_guide
from exposure_workbench.services.ledger import Ledger

ASK_TOOL_NAME = "ask"
SUBMIT_TOOL_NAME = "submit"
OPEN_TOOL_NAME = "open"

ANALYSTS: tuple[str, ...] = handbook.ANALYSTS

# One turn's asks. Four is what a question spanning the book, two issuers and a
# price would need; past that the lead is decomposing instead of asking.
MAX_TASKS = 4
# Lines in one task. A task with more is two tasks or a question not yet taken apart.
MAX_LINES = 8


ASK_TOOL = {"type": "function", "function": {
    "name": ASK_TOOL_NAME,
    "description": (
        "Ask the desk's analysts for what you need to know. Pick each analyst by the family of evidence the line "
        "turns on — the issuer analyst reads filings, the market analyst prices, the portfolio risk manager the book — "
        "name the subjects it concerns, and write what you want to know as short, separate lines, one thing per line, "
        "in financial language: say the period, and say what is to be set against what where the line is a "
        "comparison. Ask several analysts in one call when a question spans them; several issuers studied in depth "
        "are one task each. Every line comes back settled — a finding with the desk's rows under it — or with what "
        "stopped it."),
    "parameters": {"type": "object", "properties": {
        "tasks": {"type": "array", "minItems": 1, "maxItems": MAX_TASKS, "items": {
            "type": "object", "properties": {
                "analyst": {"type": "string", "enum": list(ANALYSTS)},
                "subjects": {"type": "array", "minItems": 1, "items": {"type": "string"},
                             "description": "tickers, or a book's id as the desk gave it to you — including the id of a "
                                            "book an analyst built this turn, to have another analyst read it"},
                "lines": {"type": "array", "minItems": 1, "maxItems": MAX_LINES, "items": {"type": "string"},
                          "description": "one thing you want to know per line, in your own words"},
                "context": {"type": ["string", "null"],
                            "description": "one sentence on what the answer is for, when it changes what matters"},
                "follow_up_of": {"type": ["string", "null"],
                                 "description": "the task this follows up, when asking the same analyst again"}},
            "required": ["analyst", "subjects", "lines"], "additionalProperties": False}}},
        "required": ["tasks"], "additionalProperties": False}}}


_SETTLED = {"type": "object", "properties": {
    "n": {"type": "integer", "minimum": 1}, "settled": {"const": True},
    "finding": {"type": "string", "minLength": 1, "description": "one to three sentences, written to the style guide"},
    "facts": {"type": "array", "minItems": 1, "items": {"type": "string"},
              "description": "the f_… ids of the rows the finding rests on"}},
    "required": ["n", "settled", "finding", "facts"], "additionalProperties": False}
_UNSETTLED = {"type": "object", "properties": {
    "n": {"type": "integer", "minimum": 1}, "settled": {"const": False},
    "why": {"type": "string", "minLength": 1, "description": "one line, in your words, on what stopped it"},
    "boundary": {"type": "string", "description": "the f_… id of the absence row that says so — a tool's refusal, or a standing policy"}},
    "required": ["n", "settled", "why", "boundary"], "additionalProperties": False}

SUBMIT_TOOL = {"type": "function", "function": {
    "name": SUBMIT_TOOL_NAME,
    "description": (
        "File your brief: one entry per numbered line of the task, and an entry is one of two things. SETTLED: a "
        "finding and the ids of the rows it rests on. NOT SETTLED: why, in a line, and the id of the absence row that "
        "says so. Never both, never neither. A caveat names the line it qualifies."),
    "parameters": {"type": "object", "properties": {
        "lines": {"type": "array", "minItems": 1, "items": {"oneOf": [_SETTLED, _UNSETTLED]}},
        "caveats": {"type": "array", "items": {"type": "object", "properties": {
            "line": {"type": "integer", "minimum": 1}, "text": {"type": "string", "minLength": 1}},
            "required": ["line", "text"], "additionalProperties": False},
            "description": "where a finding is not quite the line asked: another date, another spacing, a proxy"},
        "follow_ups": {"type": "array", "items": {"type": "string"}, "description": "what you would ask next"}},
        "required": ["lines"], "additionalProperties": False}}}


OPEN_TOOL = {"type": "function", "function": {
    "name": OPEN_TOOL_NAME,
    "description": (
        "Open something this conversation already put on the record, by its id: a row (f_…), every row one call "
        "pulled (r_…), an analyst's log of what it did and why (the task's id), or a book a scenario built (calc_…). "
        "It reads what is there; a figure nobody pulled is asked for, not opened. A call's rows and a long series "
        "come a page at a time: the reply says the total and the range shown, and `offset` reads on from where the "
        "last page ended."),
    "parameters": {"type": "object", "properties": {
        "id": {"type": "string"},
        "offset": {"type": ["integer", "null"], "minimum": 0,
                   "description": "where to read on from — the last page's next_offset; omitted reads from the start"}},
        "required": ["id"], "additionalProperties": False}}}


@dataclass(frozen=True)
class Task:
    """One ask, as the analyst receives it."""
    task_id: str
    analyst: str
    subjects: tuple[str, ...]
    lines: tuple[str, ...]
    context: str | None = None
    follow_up_of: str | None = None

    @property
    def domain(self) -> str:
        """What the record and the page call the asked party (analyst_reports.domain,
        the report chip): the analyst, now that there are three of them."""
        return self.analyst

    def as_dict(self) -> dict:
        out: dict = {"task_id": self.task_id, "analyst": self.analyst, "subjects": list(self.subjects),
                     "lines": [f"{i}. {w}" for i, w in enumerate(self.lines, 1)]}
        if self.context:
            out["context"] = self.context
        if self.follow_up_of:
            out["follow_up_of"] = self.follow_up_of
        return out

    def asked_text(self) -> str:
        """The lead's own words, for the check: a number the lead wrote is a number
        the analyst may repeat (`answer_check` reads the question for exactly this)."""
        return " ".join((*self.lines, self.context or ""))


@dataclass
class AnalystResult:
    """What one analyst comes back with, before the lead sees it."""
    task: Task
    status: str = "refused"                      # settled | partial | unsettled | refused
    lines: list[dict] = field(default_factory=list)       # {n, settled, finding, facts} | {n, settled, why, boundary}
    caveats: list[dict] = field(default_factory=list)     # {line, text}
    follow_ups: list[str] = field(default_factory=list)
    refused: list[dict] = field(default_factory=list)     # {n, finding, problems}: settled lines the check refused
    made: list[str] = field(default_factory=list)         # books this analyst built, by id
    log: list[dict] = field(default_factory=list)         # {step, tool, asked, why, got}: its calls, in order
    report_id: str | None = None
    coverage: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)


@dataclass
class HandoffVerdict:
    problems: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    accepted: list[dict] = field(default_factory=list)      # settled lines that passed
    rejected: list[dict] = field(default_factory=list)      # {n, finding | why, problems}: entries with a problem
    # V2 P1: what a resubmission may keep — every entry, caveat and follow-up that passed
    # every check, so the patch contract (merge_brief) has something to hold on to.
    kept: list[dict] = field(default_factory=list)          # entries (settled or not) with no problem
    caveats_ok: list[dict] = field(default_factory=list)
    follow_ups_ok: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


class BadDelegation(ValueError):
    """The call was not an ask, or not a brief. Told to whoever made it, never
    raised at the turn: a malformed tool call is a message to fix, not a lost turn."""


def parse_tasks(args: dict, new_id) -> list[Task]:
    """The tasks of one ask, normalised, or a BadDelegation in words the lead can act on."""
    if not isinstance(args, dict) or not isinstance(args.get("tasks"), list) or not args["tasks"]:
        raise BadDelegation("ask takes {tasks: [{analyst, subjects, lines, …}]}")
    if len(args["tasks"]) > MAX_TASKS:
        raise BadDelegation(f"at most {MAX_TASKS} tasks in one call; ask the rest after you read these")
    out: list[Task] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for i, t in enumerate(args["tasks"]):
        if not isinstance(t, dict):
            raise BadDelegation(f"tasks[{i}] is not an object")
        analyst = str(t.get("analyst") or "").strip()
        if analyst not in ANALYSTS:
            raise BadDelegation(f"tasks[{i}].analyst {analyst!r} is not one of the desk's analysts: {', '.join(ANALYSTS)}")
        subjects = t.get("subjects")
        if isinstance(subjects, str):
            subjects = [subjects]
        subjects = [str(s).strip() for s in (subjects or []) if str(s).strip()]
        if not subjects:
            raise BadDelegation(f"tasks[{i}].subjects names at least one ticker or one book's id")
        key = (analyst, tuple(sorted(s.upper() for s in subjects)))
        if key in seen:
            raise BadDelegation(f"the {analyst} analyst is asked twice about {', '.join(subjects)} in one call; "
                                f"put every line for them in one task")
        seen.add(key)
        lines = t.get("lines")
        if isinstance(lines, str):
            lines = [lines]
        lines = [str(w).strip() for w in (lines or []) if str(w).strip()]
        if not lines:
            raise BadDelegation(f"tasks[{i}].lines is a non-empty list of things you want to know")
        if len(lines) > MAX_LINES:
            raise BadDelegation(f"tasks[{i}].lines has more than {MAX_LINES} lines; that is more than one task")
        out.append(Task(task_id=new_id("tsk_"), analyst=analyst, subjects=tuple(subjects), lines=tuple(lines),
                        context=(t.get("context") or None), follow_up_of=(t.get("follow_up_of") or None)))
    return out


def parse_submission(args: dict) -> dict:
    """A brief from a submit call, shaped — or a BadDelegation. The two-state rule
    is enforced HERE, before any check reads a figure: it is a rule about the
    shape of an entry, and a shape is refused at the door."""
    if not isinstance(args, dict) or not isinstance(args.get("lines"), list) or not args["lines"]:
        raise BadDelegation("submit takes {lines: [one entry per numbered line of the task], caveats?, follow_ups?}")
    lines: list[dict] = []
    seen: set[int] = set()
    for e in args["lines"]:
        if not isinstance(e, dict):
            raise BadDelegation("every entry of lines is an object")
        try:
            n = int(e.get("n"))
        except (TypeError, ValueError):
            raise BadDelegation("every entry names the numbered line it is about: n, an integer") from None
        if n in seen:
            raise BadDelegation(f"line {n} appears twice; one entry per line")
        seen.add(n)
        if not isinstance(e.get("settled"), bool):
            raise BadDelegation(f"line {n}: say whether it is settled — settled: true or false")
        finding, why = str(e.get("finding") or "").strip(), str(e.get("why") or "").strip()
        facts = [str(x) for x in (e.get("facts") or []) if isinstance(x, str) and x.strip()]
        boundary = str(e.get("boundary") or "").strip()
        if e["settled"]:
            if why or boundary:
                raise BadDelegation(f"line {n} is filed as settled and carries why/boundary: an entry is one or the "
                                    f"other — keep the one that is true")
            if not finding or not facts:
                raise BadDelegation(f"line {n} is settled: it takes a finding and the ids of the rows it rests on")
            lines.append({"n": n, "settled": True, "finding": finding, "facts": facts})
        else:
            if finding or facts:
                raise BadDelegation(f"line {n} is filed as not settled and carries a finding: an entry is one or the "
                                    f"other — keep the one that is true")
            if not why or not boundary:
                raise BadDelegation(f"line {n} is not settled: it takes why, and the id of the absence row that says "
                                    f"so — every refusal the desk made you is a row, and the policies stand as rows")
            lines.append({"n": n, "settled": False, "why": why, "boundary": boundary})
    caveats = []
    for c in args.get("caveats") or []:
        if not isinstance(c, dict) or not str(c.get("text") or "").strip():
            raise BadDelegation("a caveat is {line, text}: it names the line it qualifies")
        try:
            caveats.append({"line": int(c.get("line")), "text": str(c["text"]).strip()})
        except (TypeError, ValueError):
            raise BadDelegation("a caveat names the numbered line it qualifies, as an integer") from None
    return {"lines": lines, "caveats": caveats,
            "follow_ups": [str(c).strip() for c in (args.get("follow_ups") or []) if str(c).strip()]}


# ── the check at the boundary ────────────────────────────────────────────────

def handoff_check(task: Task, brief: dict, ledger: Ledger) -> HandoffVerdict:
    """What the lead is allowed to be handed. Lookups, no judgement — the same
    discipline as the answer check, for the same reason.

      C1  every numbered line has exactly one entry, and nothing else does
      C2  every finding's figures point at facts, checked by the answer check
          itself, so a figure the lead copies is a figure the gate will accept
      C3  the ids a finding names are on the ledger
      C4  the boundary of an unsettled line is an absence the ledger holds
      C5  a caveat qualifies a line of this task
      C6  a caveat's text reads against the ledger exactly as a finding does
      C7  an unsettled line's `why` reads against the ledger exactly as a finding does
      C8  a follow-up reads against the ledger exactly as a finding does

    C6–C8 are V2 P1.1 (design v0.4 G1): every channel that carries the analyst's
    words goes through ONE check — answer_check.check, the same lookup the finding
    and the lead's reply go through — so moving a figure from a finding into a
    caveat, a why or a follow-up changes nothing about what it must point at. A
    caveat or a follow-up that fails is not handed on (`caveats_ok`,
    `follow_ups_ok`); an unsettled line whose why fails is refused like a settled
    line whose finding fails.

    A problem that enforces one of the style guide's eight rules says which, by
    number (`rule`, services/style_guide): everything C2, C6, C7 and C8 find, and
    C5. The others are about the SHAPE of the brief and carry none. Every problem
    says the way out.
    """
    v = HandoffVerdict()
    asked = task.asked_text()
    n = len(task.lines)
    filed = {e["n"] for e in brief.get("lines") or []}
    for want in range(1, n + 1):
        if want not in filed:
            v.problems.append({"where": "coverage", "reason": "uncovered_line", "n": want, "line": task.lines[want - 1],
                               "way_out": f"line {want} of the task has no entry: settle it, or say what stopped you and "
                                      f"point at the absence row that says so"})
    for want in sorted(filed):
        if not 1 <= want <= n:
            v.problems.append({"where": "coverage", "reason": "unknown_line", "n": want,
                               "way_out": f"the task has {n} numbered line(s); {want} is not one of them"})

    for e in brief.get("lines") or []:
        where = f"line {e['n']}"
        if not e["settled"]:
            problems = []
            fid = e["boundary"]
            if ledger.kind(fid) != F.ABSENCE:
                problems.append({"where": where, "reason": "not_a_boundary", "id": fid, "n": e["n"],
                                 "way_out": f"{fid} is not an absence row the desk showed you: point at the row that "
                                        f"says what could not be done, or at the policy that stops the line"})
            # C7 — the why is the analyst's words about a fact, and reads like one
            problems += [{**p, "where": f"{where} / why", "n": e["n"]}
                         for p in answer_check.check(e["why"], ledger, question=asked).problems]
            if problems:
                v.rejected.append({**e, "problems": problems})
                v.problems += problems
            else:
                v.kept.append(e)
            continue
        problems = [{**p, "where": where, "n": e["n"]}
                    for p in answer_check.check(e["finding"], ledger, question=asked).problems]
        for fid in e["facts"]:
            if not ledger.holds(fid):
                problems.append({"where": where, "reason": "not_on_ledger", "id": fid, "n": e["n"],
                                 "way_out": f"{fid} is not a row the desk showed you this turn: copy the id from the row"})
        if problems:
            v.rejected.append({**e, "problems": problems})
            v.problems += problems
        else:
            v.accepted.append(e)
            v.kept.append(e)

    for i, c in enumerate(brief.get("caveats") or []):
        where = f"caveats[{i}]"
        problems = []
        if not 1 <= c["line"] <= n:
            problems.append(style_guide.ruled({"where": where, "reason": "caveat_without_a_line", "n": c["line"],
                                               "way_out": f"a caveat qualifies one of the task's {n} line(s)"}))
        # C6 — a caveat's figure points at a row like any other figure
        problems += [{**p, "where": where, "n": c["line"]}
                     for p in answer_check.check(c["text"], ledger, question=asked).problems]
        if problems:
            v.problems += problems
        else:
            v.caveats_ok.append(c)

    for i, s in enumerate(brief.get("follow_ups") or []):
        # C8 — a question carries no figure; one that does carries it under an id
        problems = [{**p, "where": f"follow_ups[{i}]"}
                    for p in answer_check.check(s, ledger, question=asked).problems]
        if problems:
            v.problems += problems
        else:
            v.follow_ups_ok.append(s)

    v.coverage = {"asked": n, "settled": len(v.accepted),
                  "unsettled": len([e for e in v.kept if not e["settled"]]), "refused": len(v.rejected)}
    return v


def merge_brief(kept: dict | None, new: dict) -> dict:
    """THE PATCH CONTRACT (V2 P1.2, design v0.4 G2). The refusal tells the analyst
    that every entry not named is kept, and until V2 the code replaced the whole
    brief with the resubmission — an analyst that did as told lost its passing
    lines to C1. Now the resubmission is merged over what the last verdict kept:
    a line named again is replaced, a line not named stays as filed, caveats that
    passed stay beside the new ones, and follow-ups are the new list if one was
    filed. Within one task the ledger only grows and a fact never changes, so an
    entry that passed against the earlier ledger passes against the later one;
    nothing is kept across tasks (that is follow_up_of's business, P2)."""
    if not kept:
        return new
    lines = {e["n"]: e for e in kept.get("lines") or []}
    lines.update({e["n"]: e for e in new.get("lines") or []})
    seen: set[tuple] = set()
    caveats: list[dict] = []
    for c in [*(kept.get("caveats") or []), *(new.get("caveats") or [])]:
        key = (c["line"], c["text"])
        if key not in seen:
            seen.add(key)
            caveats.append(c)
    return {"lines": [lines[k] for k in sorted(lines)], "caveats": caveats,
            "follow_ups": list(new.get("follow_ups") or kept.get("follow_ups") or [])}


def refusal_message(task: Task, verdict: HandoffVerdict) -> str:
    """What the analyst is told. Only what failed, and what to do — the same shape
    the lead's own refusal has, for the same reason: a whole rewrite re-rolls the
    entries that were already right (V33F)."""
    lines = [f"{len(verdict.problems)} problem(s) with your brief. Every entry not named here is kept.", ""]
    seen: set[str] = set()
    for p in verdict.problems[:20]:
        what = p.get("figure") or p.get("id") or p.get("quote") or p.get("word") or p.get("phrase") or ""
        line = (f"[{p.get('where') or '?'}] " + (f"rule {p['rule']} — " if p.get("rule") else "") + p["reason"]
                + (f" ({what!r})" if what else ""))
        if p.get("line"):
            line += f" — {p['line']}"
        if p.get("way_out"):
            line += f": {p['way_out']}"
        if p.get("candidates"):
            line += " — the desk showed: " + "; ".join(
                f"{c.get('measure')} {c.get('subject')} {c.get('as_of')} [{c.get('id')}]" for c in p["candidates"][:4])
        if line not in seen:
            seen.add(line)
            lines.append(line)
    lines += ["", "Submit again with only the entries named above; every other entry stays as you filed it. Pull the "
                  "row a fix needs first if you were not shown the figure; a line the desk cannot settle is an entry with "
                  "why and its boundary, not a finding."]
    return "\n".join(lines)


# ── what the lead is handed ──────────────────────────────────────────────────

def _row(ledger: Ledger | None, fid: str) -> str | None:
    rec = (getattr(ledger, "by_id", None) or {}).get(fid)
    return F.line(rec) if rec else None


def for_lead(results: list[AnalystResult], ledger: Ledger | None = None) -> dict:
    """The Return the lead reads when `ask` comes back. Each line is one of three
    shapes and says which by what it holds: a finding with the rows under it; why,
    with the boundary row; or that the analyst's finding did not pass the desk's
    check. The rows are read off the ledger here, by id — the lead is handed the
    desk's own line, never a copy an analyst typed."""
    out = []
    for r in results:
        refused = {x["n"]: x for x in r.refused}
        lines = []
        for e in sorted(r.lines, key=lambda e: e["n"]):
            asked = r.task.lines[e["n"] - 1] if 1 <= e["n"] <= len(r.task.lines) else None
            if e["n"] in refused:
                reasons = sorted({p.get("reason") for p in refused[e["n"]].get("problems") or [] if p.get("reason")})
                lines.append({"n": e["n"], "asked": asked,
                              "refused": "the analyst's finding for this line did not pass the desk's check"
                                         + (f" ({', '.join(reasons)})" if reasons else "")})
            elif e["settled"]:
                lines.append({"n": e["n"], "asked": asked, "finding": e["finding"],
                              "rows": [row for fid in e["facts"] if (row := _row(ledger, fid))]})
            else:
                lines.append({"n": e["n"], "asked": asked, "why": e["why"],
                              "boundary": _row(ledger, e["boundary"]) or e["boundary"]})
        by_line: dict[int, list[str]] = {}
        for c in r.caveats:
            by_line.setdefault(c["line"], []).append(c["text"])
        for entry in lines:
            if entry["n"] in by_line:
                entry["caveats"] = by_line[entry["n"]]        # beside the line it qualifies
        out.append({"task_id": r.task.task_id, "analyst": r.task.analyst, "status": r.status, "lines": lines,
                    **({"made": r.made} if r.made else {}),
                    **({"follow_ups": r.follow_ups} if r.follow_ups else {})})
    return {"returns": out}


def asked_of(args: dict) -> str:
    """A call's arguments as the log shows them — everything but the `why`, which has its own place."""
    from exposure_workbench.utils import json as ejson
    return ", ".join(f"{k}={ejson.dumps(v)[:60]}" for k, v in (args or {}).items() if k != "why" and v is not None)


def got_of(said: str) -> str:
    """What came back, from what the desk said of the call: the result's head for the analyst that
    read it, the step's summary for a reader of the trace (services/fact_adapters.came_back). The
    same words either way: how many rows, and the book it made."""
    return str(said or "").split(" | refused:", 1)[0].split("→", 1)[-1].strip()


def _log(task: Task, calls: list[dict], status: str) -> str:
    head = f"{task.task_id} — the {task.analyst} analyst, asked about {', '.join(task.subjects)}: " + " | ".join(
        f"{i}. {w}" for i, w in enumerate(task.lines, 1))
    steps = [f"{s['step']}. {s['tool']}({s['asked']}) — why: {s['why']} → {s['got']}" for s in calls]
    return "\n".join([head, *steps, f"brief: {status}"])


def log_text(result: AnalystResult) -> str:
    """An analyst's log, as `open(<task id>)` shows it: its calls in order, each
    with why it was made and what came back. Built from the calls; nobody writes it."""
    return _log(result.task, result.log, result.status)


def log_from_steps(task: Task, steps: list[dict], status: str) -> str:
    """THE SAME LOG, REBUILT FROM THE TRACE (plan V1 §6: "log 由 why 长出"). Nothing the analyst
    kept is read: only `agent_steps` rows — {step_type, tool_name, args, result_summary, actor,
    status} in order — so that the log is what the calls WERE is a property a test can hold, and
    a log can be had for a turn whose process is gone.

    An analyst's stretch of the trace runs up to the `report` step that names its task. A call is
    a step its face's registry recorded; one refused before it ran (arguments that do not fit, a
    budget spent) is a rejected step and then a `boundary` step saying what came back. The
    analyst's own steps — its brief, its report, the boundary it states when it stops — are not
    calls. With `parallel_analysts` on, two tasks of ONE analyst interleave under one actor and
    this cannot tell them apart; that switch is off, and the actor would have to carry the task."""
    stretch: list[dict] = []
    for s in steps:
        if s.get("actor") != f"sub:{task.analyst}":
            continue
        if s.get("step_type") == "report":
            if ((s.get("args") or {}).get("task_id")) == task.task_id:
                break
            # an earlier task of the same analyst ended here: the steps that could only be
            # attributed by the actor stretch were its; a step tagged with THIS task stays
            stretch = [x for x in stretch if x.get("task_id")]
            continue
        # V2 P2: a step that says which task it belongs to is not read into another
        # task's stretch; a step written before task_id existed is read by the actor
        # stretch as before, which is also how two tasks interleaved under one actor
        # (parallel_analysts) are finally told apart.
        if s.get("task_id") and s["task_id"] != task.task_id:
            continue
        stretch.append(s)
    calls: list[dict] = []
    for i, s in enumerate(stretch):
        if s.get("step_type") not in ("tool_call", "delegation") or not isinstance(s.get("args"), dict):
            continue
        said = s.get("result_summary") or ""
        if s.get("status") == "rejected":      # refused before it ran: the row it got is on the next boundary step
            said = next((b.get("result_summary") or "" for b in stretch[i + 1:i + 2]
                         if b.get("step_type") == "boundary" and b.get("tool_name") == s.get("tool_name")), said)
        got = got_of(said) if "→" in said else said.removeprefix("error: ")
        calls.append({"step": len(calls) + 1, "tool": s.get("tool_name"), "asked": asked_of(s["args"]),
                      "why": str(s["args"].get("why") or ""), "got": got})
    return _log(task, calls, status)
