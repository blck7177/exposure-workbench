"""The analysis state (V2 P2, design v0.4 §07): what a turn has established, as
the runtime keeps it — never as the model remembers it.

WHY THIS EXISTS. Until V2 the lead's only state was the turn's local variables
and the growing transcript: which lines were settled, what stopped the others,
which rows had actually been handed to it, had to be re-inferred from the
conversation on every completion, and were gone at the end of the turn. The
design's answer is a small persistent record — requirements, scope, findings,
gaps, tasks — that the runtime writes and projects, and that the lead reads as
a block (P3) instead of re-deriving.

THE ONE RULE. A sentence a model wrote reaches this record through `propose`
and nowhere else, and `propose` is the same check a finding passes
(services/answer_check against the session ledger). A proposal that fails is an
agent_steps row (`state_proposal`, rejected) and nothing here: not a finding,
not a summary, not the next turn's context (acceptance A3). Findings from an
analyst's brief arrive through `merge_task`, already checked at the handoff
(delegation.handoff_check); a line that was refused there never arrives.
candidate / hypothesis / unverified are not statuses that exempt anything —
there is no such status here.

WHAT IS MECHANICAL HERE. Requirement status is a count over findings and gaps;
a gap's type is a table over the boundary row's registry reason; a conflict is
two accepted rows of one measure, subject and period whose displayed values
differ; a stale finding is one whose subjects fell outside the scope. Nothing
here reads meaning.
"""

from __future__ import annotations

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

# A gap's type is read off the boundary row's reason (analytics/registry.ABSENCE_REASONS),
# never off the analyst's words. A reason not here is `cannot`: the desk stopped.
GAP_OF_REASON: dict[str, str] = {
    "not_held": "data_missing", "no_such_name": "data_missing", "not_prepared": "data_missing",
    "meaningless": "method_unsupported", "not_comparable": "method_unsupported",
    "policy": "policy_boundary",
    "param_out_of_range": "execution_failed", "cannot": "execution_failed", "not_on_this_face": "execution_failed",
}

# What the lead's view shows of a long list. The record keeps everything.
VIEW_FINDINGS = 40
VIEW_GAPS = 40
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

def scope_of(briefing: dict) -> dict:
    """The scope the runtime fixes from the desk's map: the subjects the question
    names, the books, and the latest run's date where there is one."""
    subs = (briefing or {}).get("subjects") or {}
    books = [*(subs.get("portfolios") or []), *(subs.get("runs") or [])]
    as_of = None
    for pid, d in ((briefing or {}).get("portfolios") or {}).items():
        latest = ((d or {}).get("runs") or {}).get("latest") or {}
        if latest.get("as_of"):
            as_of = latest["as_of"]
    return {"subjects": sorted(str(t).upper() for t in (subs.get("tickers") or [])),
            "books": sorted(str(b) for b in books), "as_of": as_of}


def new_turn(session_id: str, message_id: str | None, question: str, briefing: dict,
             previous: "State | None" = None) -> State:
    """A turn's state, version 0. Findings of the session's previous state whose
    subjects are all inside this turn's scope come along as `inherited` — with
    their refs, which are on the session's ledger — and nothing else does:
    requirements and gaps are this turn's own (design §07: a new user turn is a
    new unit of work that may explicitly inherit what still applies)."""
    state = State(id=new_id("ast_"), session_id=session_id, message_id=message_id, question=question or "",
                  scope=scope_of(briefing))
    if previous is not None:
        within = set(state.scope.get("subjects") or []) | set(state.scope.get("books") or [])
        for f in previous.accepted():
            subjects = {str(s).upper() for s in f.get("subjects") or []}
            if subjects and subjects <= {s.upper() for s in within}:
                state.findings.append({**f, "status": "inherited", "requirement_ids": []})
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
                requirement_ids: Iterable[str] = (), task_id: str | None = None, source: str = "finding") -> dict:
    """A checked sentence becomes a finding. Callers are the two doors: `propose`
    (a model's own sentence, just checked) and `merge_task` (a brief's line,
    checked at the handoff). Nothing else appends to `findings`."""
    ids = list(dict.fromkeys(r for r in refs if F.is_fact_id(r)))
    subjects = sorted({str(s) for s in (_subject(ledger, fid) for fid in ids) if s})
    finding = {"text": text, "refs": ids, "subjects": subjects, "requirement_ids": list(requirement_ids),
               "task_id": task_id, "status": "accepted", "source": source, "state_version": state.version}
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


def merge_task(state: State, task, result, ledger: Ledger | None) -> None:
    """The lines that passed the handoff check become findings, the unsettled ones
    gaps typed by their boundary row; a refused line reaches neither (its record
    is analyst_reports.problems). `task.requirement_ids` (P3) is what the
    findings and gaps are mapped to; empty until the lead declares requirements."""
    refused = {x["n"] for x in (getattr(result, "refused", None) or [])}
    of_line = getattr(task, "requirements_of_line", None)
    for e in getattr(result, "lines", None) or []:
        if e.get("n") in refused:
            continue
        req_ids = list(of_line(int(e.get("n") or 0)) if callable(of_line) else (getattr(task, "requirement_ids", ()) or ()))
        if e.get("settled"):
            add_finding(state, e["finding"], refs=e.get("facts") or [], ledger=ledger,
                        requirement_ids=req_ids, task_id=task.task_id, source="brief")
        else:
            state.gaps.append({"type": gap_type_of(ledger, e.get("boundary") or ""), "requirement_ids": req_ids,
                               "boundary": e.get("boundary"), "why": e.get("why"), "task_id": task.task_id,
                               "n": e.get("n")})
    state.tasks.append({"task_id": task.task_id, "analyst": task.analyst, "status": getattr(result, "status", None),
                        "coverage": dict(getattr(result, "coverage", None) or {}),
                        "made": list(getattr(result, "made", None) or [])})
    _recompute_requirements(state)


def mark_delivery_missing(state: State, ledger: Ledger, delivered: Iterable[str]) -> list[dict]:
    """Rows on the ledger that no completion of this turn was handed and no finding
    rests on: the design's first observation ("结果在账本但未完整交付"). One gap per
    call, naming a few of the rows, so the lead opens the call rather than asks
    again. Replaces the gaps of this type from an earlier pass."""
    seen = set(delivered)
    resting = {r for f in state.findings for r in f.get("refs") or []}
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
            key = (rec.get("measure"), rec.get("subject"), rec.get("as_of"), json.dumps(rec.get("window"), sort_keys=True))
            groups.setdefault(key, {})[fid] = rec
    state.gaps = [g for g in state.gaps if g.get("type") != "evidence_conflict"]
    made = []
    for key, recs in groups.items():
        shown = {(dc.display(float(r["value"]), r["unit"]) if r.get("unit") else repr(r["value"])) for r in recs.values()}
        if len(shown) > 1:
            gap = {"type": "evidence_conflict", "requirement_ids": [], "measure": key[0], "subject": key[1],
                   "refs": sorted(recs)}
            state.gaps.append(gap)
            made.append(gap)
    return made


def invalidate(state: State, new_scope: dict) -> list[dict]:
    """The scope moved (another book, other names, another as-of): a finding whose
    subjects are no longer all inside it is `stale` and is not projected (A4). The
    record keeps it; nothing is deleted."""
    within = {str(s).upper() for s in (new_scope.get("subjects") or [])} | {str(b) for b in (new_scope.get("books") or [])}
    stale = []
    for f in state.findings:
        if f.get("status") not in ("accepted", "inherited"):
            continue
        subjects = {str(s) for s in f.get("subjects") or []}
        if subjects and not {s.upper() for s in subjects} <= {s.upper() for s in within}:
            f["status"] = "stale"
            stale.append(f)
    state.scope = dict(new_scope)
    _recompute_requirements(state)
    return stale


def _recompute_requirements(state: State) -> None:
    covered = {r for f in state.accepted() for r in f.get("requirement_ids") or []}
    bounded = {r for g in state.gaps for r in g.get("requirement_ids") or []}
    for req in state.requirements:
        req["status"] = ("covered" if req["id"] in covered else "boundary" if req["id"] in bounded else "unresolved")
        req["evidence"] = [f["refs"][0] for f in state.accepted() if req["id"] in (f.get("requirement_ids") or []) and f.get("refs")]
        req["boundary"] = next((g.get("boundary") for g in state.gaps if req["id"] in (g.get("requirement_ids") or []) and g.get("boundary")), None)


def unaddressed(state: State, cited: Iterable[str]) -> list[dict]:
    """The declared requirements a reply does not reach (V2 P3): a requirement is
    addressed when the reply points at a row of one of its findings, or at the
    boundary row of one of its gaps. One with neither a finding nor a gap on the
    record is unaddressed whatever the reply says. A lookup over ids."""
    refs = set(cited or ())
    out = []
    for req in state.requirements:
        rows = {r for f in state.accepted() if req["id"] in (f.get("requirement_ids") or []) for r in f.get("refs") or []}
        bounds = {g.get("boundary") for g in state.gaps if req["id"] in (g.get("requirement_ids") or []) and g.get("boundary")}
        if not (refs & (rows | bounds)):
            out.append(req)
    return out


def completion_of(state: State) -> str | None:
    """Mechanical: every requirement covered → completed; none unresolved but some
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


def view(state: State, ledger: Ledger | None) -> dict:
    """The AnalysisView: requirements with their status, accepted findings with the
    desk's rows under them, gaps by type with their boundary row, the tasks, the
    budget, the versions. Nothing refused, nothing stale, no measure key, no verb."""
    findings = [{"text": f["text"], "rows": [ln for fid in f.get("refs") or [] if (ln := _line(ledger, fid))],
                 **({"for": f["requirement_ids"]} if f.get("requirement_ids") else {}),
                 **({"task": f["task_id"]} if f.get("task_id") else {}),
                 **({"inherited": True} if f.get("status") == "inherited" else {})}
                for f in state.accepted()[:VIEW_FINDINGS]]
    gaps = []
    for g in state.gaps[:VIEW_GAPS]:
        entry: dict = {"type": g["type"]}
        if g.get("requirement_ids"):
            entry["for"] = g["requirement_ids"]
        if g.get("why"):
            entry["why"] = g["why"]
        if g.get("boundary"):
            entry["boundary"] = _line(ledger, g["boundary"]) or g["boundary"]
        if g.get("pull"):
            entry["call"] = g["pull"]
            entry["rows_not_handed_to_you"] = g.get("count")
            entry["some_of_them"] = [ln for fid in g.get("refs") or [] if (ln := _line(ledger, fid))]
        if g["type"] == "evidence_conflict":
            entry["rows"] = [ln for fid in g.get("refs") or [] if (ln := _line(ledger, fid))]
        if g.get("task_id"):
            entry["task"] = g["task_id"]
        gaps.append(entry)
    return {"state_version": state.version, "scope": state.scope,
            "requirements": [{"id": r["id"], "anchor": r.get("anchor"), "status": r.get("status")} for r in state.requirements],
            "findings": findings, "gaps": gaps,
            "tasks": [{k: t.get(k) for k in ("task_id", "analyst", "status", "coverage", "made") if t.get(k) not in (None, [], {})}
                      for t in state.tasks],
            "budget": state.budget, "completion": completion_of(state)}


# ── the record ───────────────────────────────────────────────────────────────

def _fields(state: State) -> dict:
    return {"session_id": state.session_id, "message_id": state.message_id, "question": state.question,
            "requirements": state.requirements, "scope": state.scope, "findings": state.findings,
            "gaps": state.gaps, "tasks": state.tasks, "budget": state.budget, "completion": completion_of(state)}


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
