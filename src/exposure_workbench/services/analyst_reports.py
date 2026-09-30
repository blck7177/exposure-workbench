"""Persist analyst reports and read them within their session.

S2 evidence-v2 reports hold retrieved evidence, individually checked notes and
actual execution metadata. Their returned/stopped status never certifies that
the question is complete. A stopped report can still contain accepted blocks;
rejected note text belongs only in the trace. Scope and evidence fingerprints
are rechecked by the follow-up reader before reusing either evidence or notes.

Historical brief reports retain their original schema and verified/refused
status; readers select the adapter using input_version/brief.protocol.

Tenant rule is the session's, as for `facts` and `agent_steps`: the policy is on
the table (infra/init.sql) and nothing here re-implements it.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import AnalystReport
from exposure_workbench.utils.ids import new_id

logger = logging.getLogger(__name__)

# Of the report's prose. The lead reads a brief; this bounds what `read_report`
# can put back into its context when the brief was not enough.
MAX_TEXT_CHARS = 6_000

_FIELDS = ("message_id", "task_id", "domain", "status", "title", "brief", "text", "blocks",
           "citations", "verified", "problems", "prompt_tokens", "completion_tokens", "evidence_calls",
           # V2 P2: TaskState
           "requirement_ids", "input_version", "accepted_lines", "attempts", "receipts")


async def store(db: AsyncSession, session_id: str, **cols) -> str:
    """Write one report; returns its id."""
    report_id = new_id("rep_")
    row = AnalystReport(id=report_id, session_id=session_id,
                        **{k: v for k, v in cols.items() if k in _FIELDS})
    row.text = (row.text or "")[:MAX_TEXT_CHARS]
    db.add(row)
    await db.flush()
    return report_id


def as_dict(row: AnalystReport) -> dict:
    return {"id": row.id, "session_id": row.session_id, "message_id": row.message_id,
            "task_id": row.task_id, "domain": row.domain, "status": row.status, "title": row.title,
            "brief": row.brief or {}, "text": row.text, "blocks": row.blocks or [],
            "citations": row.citations or [], "verified": row.verified or {}, "problems": row.problems or [],
            "cost": {"prompt_tokens": row.prompt_tokens, "completion_tokens": row.completion_tokens,
                     "evidence_calls": row.evidence_calls},
            # V2 P2: TaskState — read by follow_up_of and by the analysis state
            "requirement_ids": row.requirement_ids or [], "input_version": row.input_version or {},
            "accepted_lines": row.accepted_lines or [], "attempts": row.attempts, "receipts": row.receipts or [],
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def load(db: AsyncSession, session_id: str, report_id: str) -> dict | None:
    """One report of one session.

    Scoped by session as well as by id, so a report id guessed from another
    conversation is a 404 rather than a read — the RLS policy already refuses
    another tenant's, and this refuses another session of the same tenant, which
    the policy has no opinion about.
    """
    row = (await db.execute(
        select(AnalystReport).where(AnalystReport.id == report_id,
                                    AnalystReport.session_id == session_id))).scalar_one_or_none()
    return as_dict(row) if row is not None else None


async def load_by_task(db: AsyncSession, session_id: str, task_id: str) -> dict | None:
    """The record of one task of one session — what `open(<task id>)` reads when
    the task was asked in an earlier turn (V1)."""
    row = (await db.execute(
        select(AnalystReport).where(AnalystReport.task_id == task_id, AnalystReport.session_id == session_id)
        .order_by(AnalystReport.created_at.desc()).limit(1))).scalar_one_or_none()
    return as_dict(row) if row is not None else None


async def for_message(db: AsyncSession, session_id: str, message_id: str) -> list[dict]:
    rows = (await db.execute(
        select(AnalystReport).where(AnalystReport.session_id == session_id,
                                    AnalystReport.message_id == message_id)
        .order_by(AnalystReport.created_at))).scalars().all()
    return [as_dict(r) for r in rows]
