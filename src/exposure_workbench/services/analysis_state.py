"""The analysis state (V2 P2, design v0.4 §07): what a turn has established, as
the runtime keeps it — never as the model remembers it.

WHY THIS EXISTS. Until V2 the lead's only state was the turn's local variables
and the growing transcript: which lines were settled, what stopped the others,
which rows had actually been handed to it, had to be re-inferred from the
conversation on every completion, and were gone at the end of the turn. The
design's answer is a small persistent record — requirements, scope, findings,
gaps, tasks — that the runtime writes and projects, and that the lead reads as
a block (P3) instead of re-deriving.

THE ONE RULE. A standalone model proposal reaches this record through `propose`,
which applies the same check a finding passes
(services/answer_check against the session ledger). A proposal that fails is an
agent_steps row (`state_proposal`, rejected) and nothing here: not a finding,
not a summary, not the next turn's context (acceptance A3). Findings from an
analyst's brief arrive through `merge_task`, already checked at the handoff
(delegation.handoff_check); a line that was refused there never arrives.
candidate / hypothesis / unverified are not statuses that exempt anything —
there is no such status here.

S1 projects findings, execution records and tool results without requirement
statuses or completion claims. Requirement helpers and storage fields remain
for interpreting historical records, not for controlling the new loop. A
conflict is two accepted rows of one measure, subject and period whose displayed
values differ; restored text must match the request/snapshot scope and evidence
fingerprints and pass the fact check again. Nothing here reads meaning.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.db.models import AnalysisState
from exposure_workbench.services import answer_check, fact_boundary
from exposure_workbench.services import facts as F
from exposure_workbench.services import trace_service
from exposure_workbench.services.ledger import Ledger
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

REQUIREMENT_STATUS = ("unresolved", "covered", "boundary")
GAP_TYPES = ("data_missing", "method_unsupported", "policy_boundary", "execution_failed",
             "delivery_missing", "evidence_conflict", "needs_clarification")
COMPLETION = ("completed", "completed_with_boundaries", "partial")
BOUNDARY_VERSION = 1
CLOSING_GAPS = frozenset(("data_missing", "method_unsupported", "policy_boundary"))

# A gap's type is read off the boundary row's reason (analytics/registry.ABSENCE_REASONS),
# never off the analyst's words. A reason not here is `cannot`: the desk stopped.
GAP_OF_REASON: dict[str, str] = {
    "not_held": "data_missing", "no_such_name": "data_missing", "not_prepared": "data_missing",
    "meaningless": "method_unsupported", "not_comparable": "method_unsupported",
    "policy": "policy_boundary",
    "param_out_of_range": "execution_failed", "cannot": "execution_failed", "not_on_this_face": "execution_failed",
}

# Whole-card pages of the lead's work view. The record keeps everything.
VIEW_PAGE_ITEMS = 40
VIEW_PAGE_CHARS = 24_000  # soft bound: one complete card is never cut in half
DELIVERY_ROWS_NAMED = 8


class StaleState(RuntimeError):
    """The row moved under us: re-read, merge again, save again."""


@dataclass
class State:
    id: str
    session_id: str
    message_id: str | None
    question: str
    version: int = 0                                   # 0: never saved
    requirements: list[dict] = field(default_factory=list)   # {id, anchor, status, evidence, boundary}
    scope: dict = field(default_factory=dict)          # {subjects, books, as_of}
    findings: list[dict] = field(default_factory=list)  # {text, refs, subjects, requirement_ids, task_id, status, source}
    gaps: list[dict] = field(default_factory=list)      # {type, requirement_ids, boundary, why, task_id, refs}
    tasks: list[dict] = field(default_factory=list)     # {task_id, analyst, status, coverage}
    budget: dict = field(default_factory=dict)
    completion: str | None = None

    def accepted(self) -> list[dict]:
        return [f for f in self.findings if f.get("status") in ("accepted", "inherited")]


# ── a turn opens ─────────────────────────────────────────────────────────────

def _plain(value):
    """The scope AS THE RECORD HOLDS IT. The catalogue hands the briefing `date`
    objects (a book's `positions_as_of`, an issuer's `latest_period_end`, a filing's
    date, the span of its prices); the record is a JSONB column, and json.dumps
    has no word for a date. V2E_mini (2026-09-29): every save of a book-scoped
    state and every analyst report store raised `date is not JSON serializable`
    and was swallowed — 14 of 20 turns never persisted a state, 13 of 46 reports
    were stored. The same string form is also what `reusable` compares a restored
    scope against, so a scope is written in it from the start, not at the door."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(v) for v in value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def scope_of(briefing: dict, question: str | None = None) -> dict:
    """Conservative request scope plus the catalogue's book and issuer snapshots.
    Dates not represented structurally remain part of the literal request.
    Every date in it is an ISO string (`_plain`): the scope is a record.
    """
    subs = (briefing or {}).get("subjects") or {}
    books = [*(subs.get("portfolios") or []), *(subs.get("runs") or [])]
    snapshots = {}
    for pid, d in ((briefing or {}).get("portfolios") or {}).items():
        snapshots[pid] = {k: _plain((d or {}).get(k)) for k in ("runs", "positions_as_of")}
    dates = sorted({str(v["as_of"]) for d in snapshots.values() for v in (d.get("runs") or {}).values()
                    if isinstance(v, dict) and v.get("as_of")})
    return {"subjects": sorted(str(t).upper() for t in (subs.get("tickers") or [])),
            "books": sorted(str(b) for b in books), "as_of": dates[-1] if dates else None,
            "snapshots": snapshots,
            "issuers": {tk: {k: _plain(d.get(k)) for k in ("latest_period_end", "filings", "prices")}
                        for tk, d in ((briefing or {}).get("issuers") or {}).items() if isinstance(d, dict)},
            # No semantic date parser: a differently worded request must explicitly
            # re-read evidence. This also covers changed periods absent from the map.
            "request": " ".join((question or "").split())}


def _signature(rec: dict) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()


def validation_context(scope: dict, refs: Iterable[str], ledger: Ledger | None) -> dict:
    rows = getattr(ledger, "by_id", {}) if ledger is not None else {}
    return {"version": BOUNDARY_VERSION, "scope": copy.deepcopy(scope),
            "facts": {fid: _signature(rows[fid]) for fid in refs if fid in rows}}


def reusable(text: str, refs: Iterable[str], validation: dict | None, scope: dict, ledger: Ledger | None,
             question: str, *, channel: str = "finding") -> bool:
    """Recheck both provenance and the same factual boundary before restoring text.
    Old records without a stamp are audit records, not automatically trusted memory.
    """
    refs = list(refs)
    if ledger is None or not refs or not validation or validation.get("version") != BOUNDARY_VERSION:
        return False
    if validation.get("scope") != scope or set(validation.get("facts") or {}) != set(refs):
        return False
    if any(fid not in ledger.by_id or _signature(ledger.by_id[fid]) != validation["facts"][fid] for fid in refs):
        return False
    return fact_boundary.check_text(channel, text, ledger, question=question).ok


def new_turn(session_id: str, message_id: str | None, question: str, briefing: dict,
             previous: "State | None" = None, *, ledger: Ledger | None = None) -> State:
    """A turn's state, version 0. Previously accepted findings with matching
    scope and evidence come along as `inherited` only after revalidation:
    requirements and gaps are this turn's own (design §07: a new user turn is a
    new unit of work that may explicitly inherit what still applies)."""
    state = State(id=new_id("ast_"), session_id=session_id, message_id=message_id, question=question or "",
                  scope=scope_of(briefing, question))
    if previous is not None:
        within = set(state.scope.get("subjects") or []) | set(state.scope.get("books") or [])
        for f in previous.accepted():
            subjects = {str(s).upper() for s in f.get("subjects") or []}
            if (subjects and subjects <= {s.upper() for s in within}
                    and reusable(f["text"], f.get("refs") or [], f.get("validation"),
                                 state.scope, ledger, state.question)
                    and all(fact_boundary.check_text("caveat", text, ledger, question=state.question).ok
                            for text in f.get("caveats") or [])):
                state.findings.append({**copy.deepcopy(f), "status": "inherited", "requirement_ids": []})
    return state


# ── the boundary: the one way a model's sentence gets in ─────────────────────

def check_text(channel: str, text: str, ledger: Ledger, question: str | None = None) -> answer_check.Verdict:
    """THE entry — services/fact_boundary.check_text, the same function the finding,
    the caveat, the why, the follow-up and the lead's reply go through. `channel`
    is the proposal's own name for where it came from; the boundary records it as
    a state_proposal."""
    verdict = fact_boundary.check_text("state_proposal", text, ledger, question)
    for p in verdict.problems:
        p["where"] = channel
    return verdict


async def propose(db_factory, state: State, channel: str, text: str, ledger: Ledger, *,
                  question: str | None = None, actor: str | None = None,
                  requirement_ids: Iterable[str] = (), task_id: str | None = None) -> answer_check.Verdict:
    """A model's sentence, offered for the state. Passing, it becomes an accepted
    finding with the refs the check resolved; failing, it becomes a rejected
    `state_proposal` step on the trace and nothing else."""
    verdict = check_text(channel, text, ledger, question or state.question)
    if verdict.ok:
        add_finding(state, text, refs=verdict.refs, ledger=ledger, requirement_ids=requirement_ids,
                    task_id=task_id, source=channel)
        return verdict
    try:
        async with db_factory() as db:
            await trace_service.record_step(
                db, state.session_id, step_type="state_proposal", tool_name=None,
                args={"channel": channel, "text": text[:4000], "problems": verdict.problems[:20]},
                result_summary=f"rejected: {verdict.error}; {verdict.detail}", evidence_refs=[],
                status="rejected", message_id=state.message_id, actor=actor, task_id=task_id)
            await db.commit()
    except Exception:  # noqa: BLE001 — the audit row is owed; the refusal stands either way
        logger.exception("could not record the rejected proposal for %s", state.session_id)
    return verdict


def add_finding(state: State, text: str, *, refs: Iterable[str], ledger: Ledger | None,
                requirement_ids: Iterable[str] = (), task_id: str | None = None, source: str = "finding",
                n: int | None = None) -> dict:
    """A checked sentence becomes a finding. Callers are the two doors: `propose`
    (a model's own sentence, just checked) and `merge_task` (a brief's line,
    checked at the handoff). Nothing else appends to `findings`."""
    ids = list(dict.fromkeys(r for r in refs if F.is_fact_id(r)))
    subjects = sorted({str(s) for s in (_subject(ledger, fid) for fid in ids) if s})
    finding = {"text": text, "refs": ids, "subjects": subjects, "requirement_ids": list(requirement_ids),
               "task_id": task_id, "n": n, "status": "accepted", "source": source, "state_version": state.version,
               "validation": validation_context(state.scope, ids, ledger)}
    state.findings.append(finding)
    _recompute_requirements(state)
    return finding


def _subject(ledger: Ledger | None, fid: str) -> str | None:
    rec = (getattr(ledger, "by_id", None) or {}).get(fid) if ledger is not None else None
    return rec.get("subject") if rec else None


# ── what a task leaves behind ─────────────────────────────────────────────────

def gap_type_of(ledger: Ledger | None, boundary: str) -> str:
    rec = (getattr(ledger, "by_id", None) or {}).get(boundary) if ledger is not None else None
    reason = ((rec or {}).get("means") or {}).get("reason")
    return GAP_OF_REASON.get(str(reason), "execution_failed")


def start_tasks(state: State, tasks: Iterable) -> None:
    """Register work before dispatch. S1 tasks carry no requirements and do not
    supersede previous findings. Historical tasks retain their old mapping logic.
    """
    for task in tasks:
        if any(t["task_id"] == task.task_id for t in state.tasks):
            continue
        served = set(getattr(task, "requirement_ids", ()) or ())
        prior = getattr(task, "follow_up_of", None)
        if prior and served:
            for entry in [*state.findings, *state.gaps]:
                if entry.get("task_id") == prior:
                    entry["requirement_ids"] = [r for r in entry.get("requirement_ids") or [] if r not in served]
                    if not entry["requirement_ids"]:
                        entry["status"] = "superseded"
            for old in state.tasks:
                if old["task_id"] == prior:
                    for line in old.get("lines") or []:
                        line["for"] = [r for r in line["for"] if r not in served]
        of_line = getattr(task, "requirements_of_line", None)
        state.tasks.append({"task_id": task.task_id, "analyst": task.analyst, "status": "running",
                            "subjects": list(task.subjects), "asked": list(task.lines),
                            "lines": [{"n": n, "for": list(of_line(n) if callable(of_line) else served),
                                       "status": "unresolved"} for n in range(1, len(task.lines) + 1)]})
    state.completion = None
    _recompute_requirements(state)


def active_gaps(state: State) -> list[dict]:
    return [g for g in state.gaps if g.get("status") not in ("superseded", "stale")]


def merge_task(state: State, task, result, ledger: Ledger | None) -> None:
    """The lines that passed the handoff check become findings, the unsettled ones
    gaps typed by their boundary row. Refused or missing lines leave a runtime
    execution_failed gap, never the rejected prose (kept in the report audit).
    Every registered line retains its requirement mapping until explicitly
    superseded by a follow-up serving those requirements.
    """
    start_tasks(state, [task])
    record = next(t for t in state.tasks if t["task_id"] == task.task_id)
    # A second merge of this task replaces its outcomes; it does not accumulate
    # an old failed attempt beside the accepted repair.
    state.findings = [f for f in state.findings if f.get("task_id") != task.task_id]
    state.gaps = [g for g in state.gaps if g.get("task_id") != task.task_id]
    refused = {x["n"] for x in (getattr(result, "refused", None) or [])}
    entries = {e.get("n"): e for e in getattr(result, "lines", None) or []}
    for obligation in record["lines"]:
        n, req_ids = obligation["n"], obligation["for"]
        e = entries.get(n)
        if e is None or n in refused:
            obligation["status"] = "unresolved"
            state.gaps.append({"type": "execution_failed", "requirement_ids": req_ids, "task_id": task.task_id,
                               "n": n, "why": "the analyst did not return an accepted result for this line",
                               "rejections": sorted({p["reason"] for r in getattr(result, "refused", [])
                                                     if r["n"] == n for p in r.get("problems") or []
                                                     if p.get("reason")})})
        elif e.get("settled"):
            caveats = [c["text"] for c in getattr(result, "caveats", []) if c["line"] == n]
            refs = list(e.get("facts") or [])
            for text in caveats:
                refs.extend(fact_boundary.check_text("caveat", text, ledger, question=state.question).refs)
            finding = add_finding(state, e["finding"], refs=refs, ledger=ledger,
                                  requirement_ids=req_ids, task_id=task.task_id, source="brief", n=n)
            if caveats:
                finding["caveats"] = caveats
            obligation["status"] = "covered"
        else:
            kind = gap_type_of(ledger, e.get("boundary") or "")
            obligation["status"] = "boundary" if kind in CLOSING_GAPS else "unresolved"
            state.gaps.append({"type": kind, "requirement_ids": req_ids,
                               "boundary": e.get("boundary"), "why": e.get("why"), "task_id": task.task_id,
                               "n": n, "caveats": [c["text"] for c in getattr(result, "caveats", []) if c["line"] == n]})
    record.update(status=getattr(result, "status", None), coverage=dict(getattr(result, "coverage", None) or {}),
                  made=list(getattr(result, "made", None) or []), cost=dict(getattr(result, "cost", None) or {}),
                  follow_ups=list(getattr(result, "follow_ups", None) or []),
                  report_id=getattr(result, "report_id", None))
    _recompute_requirements(state)


def mark_delivery_missing(state: State, ledger: Ledger, delivered: Iterable[str]) -> list[dict]:
    """Rows on the ledger that no completion of this turn was handed and no finding
    rests on: the design's first observation ("结果在账本但未完整交付"). One gap per
    call, naming a few of the rows, so the lead opens the call rather than asks
    again. Replaces the gaps of this type from an earlier pass."""
    seen = set(delivered)
    resting = {r for f in state.accepted() for r in f.get("refs") or []}
    by_pull: dict[str, list[str]] = {}
    for fid, rec in ledger.shown.items():
        if fid in seen or fid in resting or rec.get("kind") == F.ABSENCE:
            continue
        by_pull.setdefault(str((rec.get("params") or {}).get("pull") or "?"), []).append(fid)
    state.gaps = [g for g in state.gaps if g.get("type") != "delivery_missing"]
    made = []
    for pull, ids in sorted(by_pull.items()):
        gap = {"type": "delivery_missing", "requirement_ids": [], "pull": pull, "count": len(ids),
               "refs": ids[:DELIVERY_ROWS_NAMED]}
        state.gaps.append(gap)
        made.append(gap)
    return made


def conflicts(state: State, ledger: Ledger) -> list[dict]:
    """Two accepted rows of one measure, one subject and one period whose values
    the desk would display differently. A lookup, not a judgement; the lead is
    told to check dates, restatements and sources (design §06)."""
    groups: dict[tuple, dict[str, dict]] = {}
    for f in state.accepted():
        for fid in f.get("refs") or []:
            rec = ledger.by_id.get(fid)
            if not rec or rec.get("kind") != F.SCALAR or not isinstance(rec.get("value"), (int, float)):
                continue
            params = rec.get("params") or {}
            key = (rec.get("measure"), rec.get("subject"), rec.get("as_of"), json.dumps(rec.get("window"), sort_keys=True),
                   params.get("book") or params.get("of"))
            groups.setdefault(key, {})[fid] = rec
    state.gaps = [g for g in state.gaps if g.get("type") != "evidence_conflict"]
    made = []
    for key, recs in groups.items():
        shown = {(dc.display(float(r["value"]), r["unit"]) if r.get("unit") else repr(r["value"])) for r in recs.values()}
        if len(shown) > 1:
            reqs = sorted({r for f in state.accepted() if set(f.get("refs") or []) & recs.keys()
                           for r in f.get("requirement_ids") or []})
            gap = {"type": "evidence_conflict", "requirement_ids": reqs, "measure": key[0], "subject": key[1],
                   "refs": sorted(recs)}
            state.gaps.append(gap)
            made.append(gap)
    _recompute_requirements(state)
    return made


def invalidate(state: State, new_scope: dict) -> list[dict]:
    """A scope change invalidates findings and boundaries and reopens the work.
    Stale results remain on the audit record but are not projected (A4).
    """
    within = {str(s).upper() for s in (new_scope.get("subjects") or [])} | {str(b) for b in (new_scope.get("books") or [])}
    stale = []
    for f in state.findings:
        if f.get("status") not in ("accepted", "inherited"):
            continue
        subjects = {str(s) for s in f.get("subjects") or []}
        if ((f.get("validation") or {}).get("scope") != new_scope
                or (subjects and not {s.upper() for s in subjects} <= {s.upper() for s in within})):
            f["status"] = "stale"
            stale.append(f)
    if state.scope != new_scope:
        for gap in state.gaps:
            if gap.get("status") != "superseded":
                gap["status"] = "stale"
        for task in state.tasks:
            for line in task.get("lines") or []:
                line["status"] = "unresolved"
    state.scope = copy.deepcopy(new_scope)
    state.completion = None
    _recompute_requirements(state)
    return stale


def _recompute_requirements(state: State) -> None:
    covered = {r for f in state.accepted() for r in f.get("requirement_ids") or []}
    gaps = active_gaps(state)
    bounded = {r for g in gaps if g["type"] in CLOSING_GAPS for r in g.get("requirement_ids") or []}
    blocked = {r for g in gaps if g["type"] not in CLOSING_GAPS for r in g.get("requirement_ids") or []}
    blocked |= {r for task in state.tasks for line in task.get("lines") or []
                if line.get("status") == "unresolved" for r in line.get("for") or []}
    for req in state.requirements:
        rid = req["id"]
        req["status"] = ("unresolved" if rid in blocked else "boundary" if rid in bounded
                         else "covered" if rid in covered else "unresolved")
        req["evidence"] = [f["refs"][0] for f in state.accepted() if req["id"] in (f.get("requirement_ids") or []) and f.get("refs")]
        req["boundary"] = next((g.get("boundary") for g in gaps if rid in (g.get("requirement_ids") or []) and g.get("boundary")), None)


def unaddressed(state: State, cited: Iterable[str]) -> list[dict]:
    """A reply must reach each mapped finding and closing boundary. Execution
    failures, conflicts and unresolved obligations cannot close a requirement,
    even when the reply cites a successful sibling result. A lookup over ids.
    """
    refs = set(cited or ())
    out = []
    for req in state.requirements:
        findings = [f for f in state.accepted() if req["id"] in (f.get("requirement_ids") or [])]
        gaps = [g for g in active_gaps(state) if req["id"] in (g.get("requirement_ids") or [])]
        if (req.get("status") == "unresolved" or not (findings or gaps)
                or any(not refs.intersection(f.get("refs") or []) for f in findings)
                or any(g["type"] not in CLOSING_GAPS or g.get("boundary") not in refs for g in gaps)):
            out.append(req)
    return out


def completion_of(state: State) -> str | None:
    """Legacy record interpretation, never an S1 runtime completion verdict.
    Mechanical: every requirement covered → completed; none unresolved but some
    bounded → completed_with_boundaries; any unresolved → partial. None when no
    requirement was declared (there is nothing to be complete against)."""
    if not state.requirements:
        return None
    statuses = {r.get("status") for r in state.requirements}
    if statuses == {"covered"}:
        return "completed"
    if "unresolved" not in statuses:
        return "completed_with_boundaries"
    return "partial"


# ── what the lead reads ───────────────────────────────────────────────────────

def _line(ledger: Ledger | None, fid: str | None) -> str | None:
    rec = (getattr(ledger, "by_id", None) or {}).get(fid) if (ledger is not None and fid) else None
    return F.line(rec) if rec else None


def view(state: State, ledger: Ledger | None, *, offset: int = 0) -> dict:
    """One paged work view, newest task first; no semantic completion verdict.

    Checked prose lives here, not in ask receipts too. Keep whole findings with
    their caveats. A single oversized card may exceed the soft character bound;
    it is marked and never silently truncated. All remaining cards are reachable
    through open(state.id, next_offset), including inherited findings.
    """
    entries: list[tuple[str, dict]] = []
    for f in state.accepted():
        entry = {"text": f["text"], "refs": list(f.get("refs") or []),
                 "rows": [ln for fid in f.get("refs") or [] if (ln := _line(ledger, fid))]}
        for key, target in (("task_id", "task"), ("n", "line"), ("caveats", "caveats")):
            if f.get(key) is not None:
                entry[target] = f[key]
        if f.get("status") == "inherited":
            entry["inherited"] = True
        entries.append(("findings", entry))
    for g in active_gaps(state):
        # A boundary describes the operation that returned it. Its reason family
        # does not certify that the user's question is unanswerable.
        entry = {"type": "tool_result" if g.get("boundary") else g["type"]}
        for key, target in (("why", "why"), ("task_id", "task"), ("n", "line"), ("caveats", "caveats"),
                            ("rejections", "rejections")):
            if g.get(key):
                entry[target] = g[key]
        if g.get("boundary"):
            fid = g["boundary"]
            entry["boundary"] = _line(ledger, fid) or fid
            rec = (getattr(ledger, "by_id", {}) or {}).get(fid) or {}
            entry["operation"] = {k: (rec.get("params") or {}).get(k)
                                  for k in ("tool", "error", "pull") if (rec.get("params") or {}).get(k)}
        if g.get("pull"):
            entry.update(call=g["pull"], rows_not_handed_to_you=g.get("count"),
                         some_of_them=[ln for fid in g.get("refs") or [] if (ln := _line(ledger, fid))])
        if g["type"] == "evidence_conflict":
            entry["rows"] = [ln for fid in g.get("refs") or [] if (ln := _line(ledger, fid))]
        entries.append(("gaps", entry))
    for task in state.tasks:
        entry = {"task": task["task_id"], "analyst": task["analyst"],
                 "execution": "running" if task.get("status") == "running" else "returned",
                 "brief_status": task.get("status")}
        entry.update({k: task[k] for k in ("subjects", "asked", "made", "cost", "follow_ups", "report_id") if task.get(k)})
        entries.append(("tasks", entry))
    recent = {t["task_id"]: i for i, t in enumerate(reversed(state.tasks))}
    entries.sort(key=lambda item: recent.get(item[1].get("task"), len(recent)))
    offset = max(0, offset)
    if offset >= len(entries) and offset:
        return {"error": "invalid_offset", "total": len(entries), "detail": "offset is beyond the current work view"}
    out = {"id": state.id, "state_version": state.version, "question": state.question,
           "scope": {k: state.scope.get(k) for k in ("subjects", "books", "as_of")},
           "findings": [], "gaps": [], "tasks": [], "budget": state.budget,
           "total": len(entries), "shown": None, "next_offset": None}
    size, count = len(json.dumps(out, ensure_ascii=False)), 0
    for category, entry in entries[offset:]:
        chars = len(json.dumps(entry, ensure_ascii=False))
        if count and (count >= VIEW_PAGE_ITEMS or size + chars > VIEW_PAGE_CHARS):
            break
        out[category].append(entry)
        size += chars
        count += 1
    if count:
        out["shown"] = [offset, offset + count]  # half-open, like row and series pages
        out["next_offset"] = offset + count if offset + count < len(entries) else None
    if size > VIEW_PAGE_CHARS:
        out["oversized_card"] = True
    return out


# ── the record ───────────────────────────────────────────────────────────────

def _fields(state: State) -> dict:
    return {"session_id": state.session_id, "message_id": state.message_id, "question": state.question,
            "requirements": state.requirements, "scope": state.scope, "findings": state.findings,
            "gaps": state.gaps, "tasks": state.tasks, "budget": state.budget,
            "completion": state.completion if state.completion is not None else completion_of(state)}


def _from_row(row: AnalysisState) -> State:
    return State(id=row.id, session_id=row.session_id, message_id=row.message_id, question=row.question or "",
                 version=row.version or 1, requirements=list(row.requirements or []), scope=dict(row.scope or {}),
                 findings=list(row.findings or []), gaps=list(row.gaps or []), tasks=list(row.tasks or []),
                 budget=dict(row.budget or {}), completion=row.completion)


async def load_latest(db: AsyncSession, session_id: str) -> State | None:
    row = (await db.execute(select(AnalysisState).where(AnalysisState.session_id == session_id)
                            .order_by(AnalysisState.created_at.desc(), AnalysisState.version.desc()).limit(1))
           ).scalar_one_or_none()
    return _from_row(row) if row is not None else None


async def load(db: AsyncSession, state_id: str) -> State | None:
    row = await db.get(AnalysisState, state_id)
    return _from_row(row) if row is not None else None


async def save(db: AsyncSession, state: State) -> State:
    """Insert on first save; afterwards an UPDATE fenced on the version the caller
    read, so an older result cannot overwrite a newer state (design §07: version
    checks on the content, not a lease). StaleState means re-read and merge again."""
    fields = _fields(state)
    if state.version == 0:
        db.add(AnalysisState(id=state.id, version=1, **fields))
        await db.flush()
        state.version = 1
        return state
    res = await db.execute(
        update(AnalysisState)
        .where(AnalysisState.id == state.id, AnalysisState.version == state.version)
        .values(version=state.version + 1, updated_at=func.now(), **fields))
    if getattr(res, "rowcount", 0) != 1:
        raise StaleState(f"analysis state {state.id} moved past version {state.version}")
    state.version += 1
    return state
