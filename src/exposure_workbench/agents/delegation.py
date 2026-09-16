"""Delegation (V36): the protocol between the lead analyst and a domain analyst.

The schemas of the three messages that cross the boundary, and the check that
reads what comes back. No loop lives here — `agents/sub_analyst` runs the
analyst, `agents/meta_agent` runs the lead — so the shape of the conversation
can be read, and tested, without either of them.

WHY THE BOUNDARY MOVED. V35 put a deterministic compiler behind the lead: the
request was fields, the compiler read the fields, and the sentence the analyst
wrote in `ask` to say what it actually wanted was read by nothing. Round J's
Q11 asked for "room to warning and breach" in that sentence and got four
columns of levels back, twice, and the analyst subtracted in prose and was
refused for it. Round I's Q11 wrote the subtraction itself, in the desk's own
derive syntax, and the figures it produced were capped out of what it was
shown. Two rounds, one seam: turning an intent into the desk's language had no
owner. Here it has one, and it is an analyst holding that domain's procedure.

WHAT CROSSES, AND WHAT DOES NOT. Down: subjects, numbered lines of what the
lead wants to know, arithmetic it wants worked out, and a window. Not a method
name, not a program, not an id — those are the domain analyst's business, which
is the whole point of the split. Up: a finding per numbered line, every figure
written as the desk showed it and pointed at its fact; what could not be done,
in the desk's own words; and a report id. Not prose for the reader: the lead
writes the answer.

WHY THE CHECK IS CODE. Cognition's 2026 note on what actually works in
multi-agent systems says children do not surface what a sibling needs by
default, because models were not trained where they had to; Anthropic's is that
a subagent needs an objective, an output format, guidance and BOUNDARIES or it
quietly does something else. Both failures are invisible at the receiving end:
a brief that answers three of four lines reads exactly like one that answers
four. So coverage is counted here rather than trusted, and every figure in a
finding is resolved against the same ledger the answer check will read — a
brief whose numbers the lead cannot cite is a brief that costs the lead its
turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from exposure_workbench.services import answer_check
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger

DELEGATE_TOOL_NAME = "delegate"
SUBMIT_TOOL_NAME = "submit"
READ_REPORT_TOOL_NAME = "read_report"

# One turn's delegations. Four is what a question spanning the book, an issuer,
# its filings and its price would need; past that the lead is decomposing
# instead of asking.
MAX_TASKS = 4
# Lines in one task. A task with more is two tasks or a question that has not
# been taken apart yet.
MAX_WANTS = 8


DELEGATE_TOOL = {"type": "function", "function": {
    "name": DELEGATE_TOOL_NAME,
    "description": (
        "Ask the desk's domain analysts for what you need to know. Pick from the ROSTER the analyst whose question "
        "this is, name the subjects it concerns (tickers, port_… or run_… ids from the BRIEFING), and write what you "
        "want to know as short, separate lines — one thing per line, in your own words. The analyst chooses the desk's "
        "measures, writes and runs the programs, and comes back with a finding for each of your lines, every figure "
        "carrying the id you must write it with. Ask several analysts in one call when a question spans them. "
        "Do not name a measure, a program or a fact id: that is the analyst's job and the reason you have one."),
    "parameters": {"type": "object", "properties": {
        "tasks": {"type": "array", "minItems": 1, "maxItems": MAX_TASKS, "items": {
            "type": "object", "properties": {
                "domain": {"type": "string", "description": "a domain name from the ROSTER"},
                "subjects": {"type": "array", "minItems": 1, "items": {"type": "string"},
                             "description": "tickers, port_… or run_… ids from the BRIEFING; or a calc_… id from an analyst's `made`, for a book built this turn"},
                "want_to_know": {"type": "array", "minItems": 1, "maxItems": MAX_WANTS, "items": {"type": "string"},
                                 "description": "one thing per line, in your own words; each line comes back answered or explained"},
                "facts_to_derive": {"type": ["array", "null"], "items": {"type": "string"},
                                    "description": "arithmetic you want worked out rather than done in prose, in words: "
                                                   "'room to warning = the warning tier minus the current reading'"},
                "constraints": {"type": ["object", "null"], "properties": {
                    "window": {"type": ["string", "null"], "description": "over what: latest, the last 8 quarters, the last 5 years, at 2026-03-31, 1y, 30d, against the prior run"},
                    "compare": {"type": ["string", "null"], "description": "how it must be compared, in words: ranked, against the prior run, against each other, against a benchmark"}},
                    "additionalProperties": False},
                "context": {"type": ["string", "null"], "description": "one sentence on what the answer is for, when it changes what matters"},
                "follow_up_of": {"type": ["string", "null"], "description": "the task_id this follows up, when asking the same analyst again"},
            },
            "required": ["domain", "subjects", "want_to_know"], "additionalProperties": False}}},
        "required": ["tasks"], "additionalProperties": False}}}


SUBMIT_TOOL = {"type": "function", "function": {
    "name": SUBMIT_TOOL_NAME,
    "description": (
        "File your brief and your report. The brief answers the task line by line and is what the lead analyst reads; "
        "the report is your full reading, kept on the record. Every figure in either is written exactly as the desk "
        "showed it to you, bracket included. One entry per numbered line: settled (finding + facts) or not settled "
        "(why + boundary), never both."),
    "parameters": {"type": "object", "properties": {
        "brief": {"type": "object", "properties": {
            # V36.1: ONE list, one entry per line. Two lists let round A file a
            # line as both answered and not (18 of 51 refusals, answered_and_
            # explained); a rule caught it and cost a round trip each time. The
            # shape now says it, and parse_submission refuses an entry that is
            # both before any check runs.
            "lines": {"type": "array", "minItems": 1, "items": {
                "type": "object", "properties": {
                    "want": {"type": "integer", "description": "the numbered line of the task this entry is about (1-based); one entry per line"},
                    "finding": {"type": ["string", "null"],
                                "description": "SETTLED: one to three sentences, every figure written as the desk showed it"},
                    "facts": {"type": ["array", "null"], "items": {"type": "string"},
                              "description": "SETTLED: the f_… ids the finding rests on"},
                    "why": {"type": ["string", "null"],
                            "description": "NOT SETTLED: one line in your words on what stopped it; the desk's own words travel with the boundary id"},
                    "boundary": {"type": ["string", "null"],
                                 "description": "NOT SETTLED: the f_… id of the boundary the desk stated, when it stated one"}},
                "required": ["want"], "additionalProperties": False},
                "description": "one entry per numbered line of the task: a settled line has finding and facts; a line the desk could not settle has why and its boundary; never both"},
            "caveats": {"type": "array", "items": {"type": "string"},
                        "description": "what you had to assume or leave out; the lead states these to the reader"},
            "follow_ups": {"type": "array", "items": {"type": "string"},
                           "description": "what you would ask next, if the lead wants it"}},
            "required": ["lines"], "additionalProperties": False},
        "report": {"type": "object", "properties": {
            "title": {"type": "string"},
            "text": {"type": "string", "description": "your reading in prose, for the record; figures as shown, [table: node] / [chart: node] for a node's figures"}},
            "required": ["title", "text"], "additionalProperties": False}},
        "required": ["brief", "report"], "additionalProperties": False}}}


READ_REPORT_TOOL = {"type": "function", "function": {
    "name": READ_REPORT_TOOL_NAME,
    "description": ("Open a domain analyst's full report by the id its findings came with. Use it when the findings "
                    "are not enough to answer the question you were asked."),
    "parameters": {"type": "object", "properties": {
        "report_id": {"type": "string", "description": "the report_id from a delegate result"}},
        "required": ["report_id"], "additionalProperties": False}}}


@dataclass(frozen=True)
class Task:
    """One delegation, as the domain analyst receives it."""
    task_id: str
    domain: str
    subjects: tuple[str, ...]
    want_to_know: tuple[str, ...]
    facts_to_derive: tuple[str, ...] = ()
    window: str | None = None
    compare: str | None = None
    context: str | None = None
    follow_up_of: str | None = None

    def as_dict(self) -> dict:
        out: dict = {"task_id": self.task_id, "domain": self.domain, "subjects": list(self.subjects),
                     "want_to_know": [f"{i}. {w}" for i, w in enumerate(self.want_to_know, 1)]}
        if self.facts_to_derive:
            out["facts_to_derive"] = list(self.facts_to_derive)
        if self.window or self.compare:
            out["constraints"] = {k: v for k, v in (("window", self.window), ("compare", self.compare)) if v}
        if self.context:
            out["context"] = self.context
        if self.follow_up_of:
            out["follow_up_of"] = self.follow_up_of
        return out

    def asked_text(self) -> str:
        """The lead's own words, for the check: a number the lead wrote is a
        number the analyst may repeat (`answer_check` reads the question for
        exactly this). Q11's "over 8%" is the user's 8, not the desk's."""
        return " ".join((*self.want_to_know, *self.facts_to_derive, self.context or "", self.window or ""))


@dataclass
class AnalystResult:
    """What one domain analyst comes back with, before the lead sees it."""
    task: Task
    status: str = "refused"                      # verified | partial | refused
    findings: list[dict] = field(default_factory=list)
    not_done: list[dict] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    refused: list[dict] = field(default_factory=list)
    report: dict | None = None                   # {title, text, status, problems, blocks, citations, verified}
    report_id: str | None = None
    made: list[dict] = field(default_factory=list)   # books this analyst built: {node, id, kind}
    # V37/T2: figures this analyst was shown and did not file. Only set when it
    # filed nothing at all — see sub_analyst's fallback.
    shown: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)


@dataclass
class HandoffVerdict:
    problems: list[dict] = field(default_factory=list)
    coverage: dict = field(default_factory=dict)
    accepted: list[dict] = field(default_factory=list)      # findings that passed
    rejected: list[dict] = field(default_factory=list)      # {want, finding, problems}
    report_verdict: Any = None

    @property
    def ok(self) -> bool:
        return not self.problems


class BadDelegation(ValueError):
    """The lead's call was not a delegation. Told to the lead, never raised at
    the turn: a malformed tool call is a message to fix, not a lost turn."""


def parse_tasks(args: dict, domains: set[str], new_id) -> list[Task]:
    """The tasks of one delegate call, normalised, or a BadDelegation naming what
    is wrong in the words the lead can act on."""
    if not isinstance(args, dict) or not isinstance(args.get("tasks"), list) or not args["tasks"]:
        raise BadDelegation("delegate takes {tasks: [{domain, subjects, want_to_know, …}]}")
    if len(args["tasks"]) > MAX_TASKS:
        raise BadDelegation(f"at most {MAX_TASKS} analysts in one call; ask the rest after you read these")
    out: list[Task] = []
    seen: set[str] = set()
    for i, t in enumerate(args["tasks"]):
        if not isinstance(t, dict):
            raise BadDelegation(f"tasks[{i}] is not an object")
        domain = str(t.get("domain") or "").strip()
        if domain not in domains:
            raise BadDelegation(f"tasks[{i}].domain {domain!r} is not a domain on the ROSTER")
        if domain in seen:
            raise BadDelegation(f"{domain} is asked twice in one call; put every line for it in one task")
        seen.add(domain)
        subjects = t.get("subjects")
        if isinstance(subjects, str):
            subjects = [subjects]
        subjects = [str(s).strip() for s in (subjects or []) if str(s).strip()]
        if not subjects:
            raise BadDelegation(f"tasks[{i}].subjects names at least one ticker, port_… or run_… id, or a calc_… id an analyst made")
        wants = t.get("want_to_know")
        if isinstance(wants, str):
            wants = [wants]
        wants = [str(w).strip() for w in (wants or []) if str(w).strip()]
        if not wants:
            raise BadDelegation(f"tasks[{i}].want_to_know is a non-empty list of things you want to know")
        if len(wants) > MAX_WANTS:
            raise BadDelegation(f"tasks[{i}].want_to_know has more than {MAX_WANTS} lines; that is more than one task")
        derive = t.get("facts_to_derive")
        if isinstance(derive, str):
            derive = [derive]
        con = t.get("constraints") or {}
        con = con if isinstance(con, dict) else {}
        out.append(Task(
            task_id=new_id("tsk_"), domain=domain, subjects=tuple(subjects), want_to_know=tuple(wants),
            facts_to_derive=tuple(str(d).strip() for d in (derive or []) if str(d).strip()),
            window=(con.get("window") or None), compare=(con.get("compare") or None),
            context=(t.get("context") or None), follow_up_of=(t.get("follow_up_of") or None)))
    return out


def parse_submission(args: dict) -> tuple[dict, dict]:
    """(brief, report) from a submit call, shaped, or a BadDelegation."""
    if not isinstance(args, dict):
        raise BadDelegation("submit takes {brief: {findings: [...]}, report: {title, text}}")
    brief = args.get("brief")
    report = args.get("report")
    if not isinstance(brief, dict) or not (isinstance(brief.get("lines"), list) or isinstance(brief.get("findings"), list)):
        raise BadDelegation("submit takes a brief with a lines list: one entry per numbered line of the task")
    if not isinstance(report, dict) or not str(report.get("text") or "").strip():
        raise BadDelegation("submit takes a report with a title and text; it is the record of your reading")
    findings, not_done = [], []
    if isinstance(brief.get("lines"), list):
        seen_wants: set[int] = set()
        for e in brief["lines"]:
            if not isinstance(e, dict):
                continue
            try:
                want = int(e.get("want"))
            except (TypeError, ValueError):
                raise BadDelegation("every entry names the numbered line it is about, as an integer") from None
            if want in seen_wants:
                raise BadDelegation(f"line {want} appears twice; one entry per line")
            seen_wants.add(want)
            finding = str(e.get("finding") or "").strip()
            why = str(e.get("why") or "").strip()
            if finding and why:
                raise BadDelegation(f"line {want} is filed as settled (finding) and as not settled (why): an entry is "
                                    f"one or the other — keep the one that is true")
            if not finding and not why:
                raise BadDelegation(f"line {want} has neither a finding nor a why: settle it, or say what stopped you")
            if finding:
                findings.append({"want": want, "facts": [str(x) for x in (e.get("facts") or []) if isinstance(x, str)],
                                 "finding": finding})
            else:
                not_done.append({"want": want, "why": why, **({"boundary": e["boundary"]} if e.get("boundary") else {})})
        brief = {**brief, "findings": [], "not_done": []}      # the two lists below are the pre-V36.1 shape
    for f in brief["findings"]:
        if not isinstance(f, dict):
            continue
        try:
            want = int(f.get("want"))
        except (TypeError, ValueError):
            raise BadDelegation("every finding names the numbered line it answers, as an integer") from None
        facts = [str(x) for x in (f.get("facts") or []) if isinstance(x, str)]
        findings.append({"want": want, "facts": facts, "finding": str(f.get("finding") or "").strip()})
    for n in brief.get("not_done") or []:
        if not isinstance(n, dict):
            continue
        try:
            want = int(n.get("want"))
        except (TypeError, ValueError):
            raise BadDelegation("every not_done entry names the numbered line it is about, as an integer") from None
        not_done.append({"want": want, "why": str(n.get("why") or "").strip(),
                         **({"boundary": n["boundary"]} if n.get("boundary") else {})})
    out_brief = {"findings": findings, "not_done": not_done,
                 "caveats": [str(c) for c in (brief.get("caveats") or []) if str(c).strip()],
                 "follow_ups": [str(c) for c in (brief.get("follow_ups") or []) if str(c).strip()]}
    out_report = {"title": str(report.get("title") or "").strip() or "untitled", "text": str(report["text"]).strip()}
    return out_brief, out_report


# ── the check at the boundary ────────────────────────────────────────────────

def handoff_check(task: Task, brief: dict, report: dict, ledger: Ledger) -> HandoffVerdict:
    """What the lead is allowed to be handed.

    Five lookups, no judgement — the same discipline as the answer check, for
    the same reason: a boundary that guesses is a boundary that refuses true
    work and lets false work through.

      C1  every numbered line is answered or explained, and nothing else is
      C2  every finding's figures point at facts, checked by the answer check
          itself, so a figure the lead copies is a figure the gate will accept
      C3  the ids a finding names are on the ledger
      C4  a not_done that names a boundary names a real one
      C5  the report passes the same reading as a finding
    """
    v = HandoffVerdict()
    asked = task.asked_text()
    n = len(task.want_to_know)

    # C1 — coverage
    answered = {f["want"] for f in brief.get("findings") or []}
    explained = {d["want"] for d in brief.get("not_done") or []}
    for want in range(1, n + 1):
        if want not in answered and want not in explained:
            v.problems.append({"where": "coverage", "reason": "uncovered_want", "want": want,
                               "line": task.want_to_know[want - 1],
                               "fix": f"line {want} of the task has no finding and no not_done entry: answer it, "
                                      f"or say what stopped you and point at the boundary"})
    for want in sorted(answered | explained):
        if not 1 <= want <= n:
            v.problems.append({"where": "coverage", "reason": "unknown_want", "want": want,
                               "fix": f"the task has {n} numbered line(s); {want} is not one of them"})
    # A line is answered or it is not. The smoke round found an analyst filing
    # three findings and three not_done entries for the same three lines, and
    # the coverage read 3 of 3 done with 3 not done — a number that says two
    # opposite things. V36.1 made the brief one list keyed by line, so the
    # canonical shape cannot say this; the pre-V36.1 two-list shape still can.
    for want in sorted(answered & explained):
        v.problems.append({"where": "coverage", "reason": "duplicate_want", "want": want,
                           "line": task.want_to_know[want - 1] if 1 <= want <= n else None,
                           "fix": f"line {want} is filed as settled and as not settled: keep the one that is true"})

    # C2 / C3 — the findings
    for i, f in enumerate(brief.get("findings") or []):
        problems: list[dict] = []
        text = f.get("finding") or ""
        if not text.strip():
            problems.append({"where": f"findings[{i}]", "reason": "empty_finding", "want": f.get("want"),
                             "fix": "a finding says what the figures show, in a sentence or three"})
        else:
            verdict = answer_check.check(text, ledger, question=asked)
            for p in verdict.problems:
                problems.append({**p, "where": f"findings[{i}]", "want": f.get("want")})
        for fid in f.get("facts") or []:
            if not ledger.holds(fid):
                problems.append({"where": f"findings[{i}]", "reason": "not_on_ledger", "id": fid, "want": f.get("want"),
                                 "fix": f"{fid} is not a fact the desk showed you this turn: copy the id from the evidence"})
        if problems:
            v.rejected.append({**f, "problems": problems})
            v.problems += problems
        else:
            v.accepted.append(f)

    # C4 — a boundary named is a boundary held
    for i, d in enumerate(brief.get("not_done") or []):
        fid = d.get("boundary")
        if fid and ledger.kind(fid) != F.ABSENCE:
            v.problems.append({"where": f"not_done[{i}]", "reason": "not_a_boundary", "id": fid, "want": d.get("want"),
                               "fix": f"{fid} is not the desk's statement of what it could not do: point at the "
                                      f"boundary the desk gave you, or leave it out and say why in your own words"})
        if not (d.get("why") or "").strip():
            v.problems.append({"where": f"not_done[{i}]", "reason": "unexplained", "want": d.get("want"),
                               "fix": "say what stopped you, in the desk's words where it gave you any"})

    # C5 — the report reads like a finding
    v.report_verdict = answer_check.check(report.get("text") or "", ledger, question=asked)
    for p in v.report_verdict.problems:
        v.problems.append({**p, "where": "report"})

    v.coverage = {"asked": n, "done": len({f["want"] for f in v.accepted}),
                  "not_done": len(explained), "refused": len({f.get("want") for f in v.rejected})}
    return v


def refusal_message(task: Task, verdict: HandoffVerdict) -> str:
    """What the domain analyst is told. Only what failed, and what to do — the
    same shape the lead's own refusal has, for the same reason: a whole rewrite
    re-rolls the entries that were already right (V33F)."""
    lines = [f"{len(verdict.problems)} problem(s) with your submission. Everything not named here is kept.", ""]
    seen: set[str] = set()
    for p in verdict.problems[:20]:
        where = p.get("where") or "?"
        what = p.get("figure") or p.get("id") or p.get("quote") or p.get("word") or p.get("phrase") or ""
        line = f"[{where}] {p['reason']}" + (f" ({what!r})" if what else "")
        if p.get("line"):
            line += f" — {p['line']}"
        if p.get("fix"):
            line += f": {p['fix']}"
        if p.get("candidates"):
            line += " — the desk showed: " + "; ".join(
                f"{c.get('measure')} {c.get('subject')} {c.get('as_of')} [{c.get('id')}]" for c in p["candidates"][:4])
        if line not in seen:
            seen.add(line)
            lines.append(line)
    lines += ["", "Submit again with those entries replaced. Request the evidence a fix needs first if you were not "
                  "shown the figure; a line the desk cannot settle is an entry with why and its boundary, not a finding."]
    return "\n".join(lines)


HOW_TO_CITE = (
    "Every figure below is written exactly as you must write it, bracket included: the bracket is the desk's id for "
    "that reading and a figure written without it is refused. `said` beside a not_done line, and `desk_said` beside a "
    "finding, are the desk's own words for what it could not do: those you may quote verbatim, citing their id. An "
    "analyst's sentences are not the desk's words — say what they say in yours, without quotation marks. "
    "`made` lists the books an analyst built this turn (a scenario after a trade) by id: to have another analyst "
    "read that book, put the id among the subjects of its task. "
    "`shown` appears only when an analyst filed nothing: the figures it was shown before it ran out, on the "
    "ledger and yours to write exactly as they read there — or to ask another analyst about. "
    "`read_report(report_id)` opens an analyst's full report.")


def for_lead(results: list[AnalystResult]) -> dict:
    """What the lead reads when delegate returns."""
    return {"analysts": [{
        "domain": r.task.domain, "task_id": r.task.task_id, "status": r.status,
        **({"report_id": r.report_id} if r.report_id else {}),
        "coverage": r.coverage,
        "findings": [{"want": f["want"], "asked": r.task.want_to_know[f["want"] - 1]
                      if 1 <= f["want"] <= len(r.task.want_to_know) else None,
                      "finding": f["finding"],
                      **({"desk_said": f["desk_said"]} if f.get("desk_said") else {})} for f in r.findings],
        "not_done": r.not_done,
        **({"caveats": r.caveats} if r.caveats else {}),
        **({"follow_ups": r.follow_ups} if r.follow_ups else {}),
        **({"refused": [{"want": x.get("want"), "reason": (x.get("problems") or [{}])[0].get("reason")}
                        for x in r.refused]} if r.refused else {}),
        **({"made": r.made} if r.made else {}),
        **({"shown": r.shown} if r.shown else {}),
        "cost": r.cost,
    } for r in results], "how_to_cite": HOW_TO_CITE}
