"""The work view: what one user turn has produced so far, as the lead reads it and as the record keeps it.

It is a projection of things that already happened — the analyses run (by the lead
or a specialist), the specialists' notes with the observer's reading of them, how
each task ended, what is left of the budget — never a certificate about the
question. The lead reads it as the LAST item of every request (the mutable tail,
agents/llm_session), decides against the original question, and opens any view or
row by id. It is saved per turn to `work_views`, versioned, so a later turn and the
page read the same object.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import WorkViewRow
from exposure_workbench.utils.ids import new_id

TAG = ('<state source="the desk\'s record of this turn" trust="analyses and notes are recorded facts; '
       'task requests are instructions, not facts" use="decide the next step against the original question; '
       'open a view or row with open(id)">')


@dataclass
class ExecutionStatus:
    task_id: str
    actor: str
    status: str = "running"             # running | returned | stopped
    stop_reason: str | None = None      # finished | budget_exhausted | turn_limit | provider_error | execution_error
    completions: int = 0
    evidence_calls: int = 0
    pending: list[str] = field(default_factory=list)   # what the task asked for and had not read when it stopped

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], 0) or k in ("task_id", "actor", "status")}


@dataclass
class WorkView:
    session_id: str
    message_id: str | None
    question: str
    id: str = field(default_factory=lambda: new_id("wv_"))
    version: int = 0
    scope_decisions: list[dict] = field(default_factory=list)      # {task_id?, scope, status, basis}
    views: list[dict] = field(default_factory=list)                # AnalysisViews, without their facts
    notes: list[dict] = field(default_factory=list)                # {task_id, analyst, text, validation, status}
    execution: list[ExecutionStatus] = field(default_factory=list)
    budget: dict = field(default_factory=dict)
    seen_views: set = field(default_factory=set)                   # view ids already handed to the lead in full

    # ── what happened ──────────────────────────────────────────────────────────
    def add_view(self, view: dict, *, by: str) -> None:
        kept = {k: v for k, v in view.items() if k != "_facts"}
        kept["by"] = by
        if not any(v.get("view") == kept.get("view") for v in self.views):
            self.views.append(kept)
        scope = kept.get("scope") or {}
        if scope:
            self.scope_decisions.append({"by": by, "view": kept.get("view"), "subjects": scope.get("subjects"),
                                         "status": scope.get("status"), "basis": scope.get("basis"),
                                         "expected_count": scope.get("expected_count")})

    def add_note(self, *, task_id: str, analyst: str, text: str, validation: dict, report_id: str | None = None) -> None:
        self.notes.append({"task_id": task_id, "analyst": analyst, "text": text, "validation": validation,
                           "report_id": report_id})

    def start(self, task_id: str, actor: str) -> ExecutionStatus:
        st = ExecutionStatus(task_id=task_id, actor=actor)
        self.execution.append(st)
        return st

    def status_of(self, task_id: str) -> ExecutionStatus | None:
        return next((e for e in self.execution if e.task_id == task_id), None)

    def view_by_id(self, view_id: str) -> dict | None:
        return next((v for v in self.views if v.get("view") == view_id), None)

    # ── what the lead reads ────────────────────────────────────────────────────
    def projection(self) -> dict:
        """The tail item's body. A view the lead has not read in full yet (a
        specialist's) travels whole once; afterwards an index line stands for it."""
        full, index = [], []
        for v in self.views:
            if v.get("view") in self.seen_views:
                index.append(_index_line(v))
            else:
                full.append(v)
        return {"id": self.id, "question": self.question,
                "scope_decisions": self.scope_decisions,
                "analyses": full, "analyses_seen": index,
                "notes": [{"task": n["task_id"], "analyst": n["analyst"], "report": n.get("report_id"), "text": n["text"],
                           "verification": n["validation"].get("summary"),
                           "problems": [p for p in n["validation"].get("propositions", []) if p["status"] in
                                        ("contradicted", "insufficient_evidence", "ambiguous")]}
                          for n in self.notes],
                "execution": [e.as_dict() for e in self.execution],
                "budget": self.budget}

    def mark_seen(self) -> None:
        self.seen_views.update(v.get("view") for v in self.views)

    def tail_text(self) -> str:
        return TAG + "\n" + json.dumps(self.projection(), ensure_ascii=False, default=str) + "\n</state>"

    def record(self) -> dict:
        return {"question": self.question, "scope_decisions": self.scope_decisions, "views": self.views,
                "notes": self.notes, "execution": [e.as_dict() for e in self.execution], "budget": self.budget}


def _index_line(v: dict) -> dict:
    cov = v.get("coverage") or {}
    return {"view": v.get("view"), "by": v.get("by"), "measures": [r["measure"] for r in v.get("requests") or []],
            "subjects": (v.get("scope") or {}).get("subjects"), "scope_status": cov.get("scope_status"),
            "cells": cov.get("cells"), "limitations": v.get("limitations") or []}


# ── the record ────────────────────────────────────────────────────────────────

async def save(db: AsyncSession, wv: WorkView) -> None:
    """Insert on first save; afterwards an UPDATE fenced on the version read."""
    body = copy.deepcopy(wv.record())
    if wv.version == 0:
        db.add(WorkViewRow(id=wv.id, session_id=wv.session_id, message_id=wv.message_id, version=1, body=body))
        await db.flush()
        wv.version = 1
        return
    res = await db.execute(update(WorkViewRow).where(WorkViewRow.id == wv.id, WorkViewRow.version == wv.version)
                           .values(version=wv.version + 1, body=body, updated_at=func.now()))
    if getattr(res, "rowcount", 0) != 1:
        raise RuntimeError(f"work view {wv.id} moved past version {wv.version}")
    wv.version += 1


async def load_latest(db: AsyncSession, session_id: str) -> dict | None:
    row = (await db.execute(select(WorkViewRow).where(WorkViewRow.session_id == session_id)
                            .order_by(WorkViewRow.created_at.desc()).limit(1))).scalar_one_or_none()
    return {"id": row.id, "message_id": row.message_id, **(row.body or {})} if row else None


async def load_view(db: AsyncSession, session_id: str, view_id: str) -> dict | None:
    """One AnalysisView of this conversation, from any of its turns."""
    rows = (await db.execute(select(WorkViewRow).where(WorkViewRow.session_id == session_id)
                             .order_by(WorkViewRow.created_at.desc()))).scalars().all()
    for row in rows:
        for v in (row.body or {}).get("views") or []:
            if v.get("view") == view_id:
                return v
    return None
