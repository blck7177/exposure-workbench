"""Job status (V3-C2) — what happened to work the agent delegated.

The delegation tools return a task or run id and nothing else, by design: they
enqueue and come straight back so the turn stays responsive. Until now that id
was a dead end — the agent could start an issuer research run and had no way to
answer "is it done yet", so the user had to go and watch the UI instead. Three
id shapes, one question.

Ownership is filtered here, in the service, and that is not the security
boundary: `tasks` is a shared table with no RLS (the worker polls it across
tenants), so this filter is semantic, not security — it decides what the agent
should talk about, not what the database will hand over. exposure_runs and
research_runs ARE RLS-scoped, and for those the filter is redundant belt beside
the policy's braces.

The dangerous case is an unauthenticated caller. `Task.owner_user_id == None`
renders as `IS NULL` in SQL and would match every ownerless seed task, so the
absence of a user is refused before any query runs rather than being allowed to
become a filter that matches the wrong rows.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.models import ExposureRun, ResearchRun, Task


class NoOwner(Exception):
    """No authenticated user, so ownership cannot be established (see module docstring)."""


async def status_of(db: AsyncSession, job_id: str) -> dict | None:
    """Status of a task_/run_/rrun_ id, or None if there is no such row."""
    if job_id.startswith("task_"):
        owner = current_user_id()
        if owner is None:
            # semantic, not security: `owner_user_id == None` compiles to IS NULL
            # and would match the ownerless seed tasks. Refuse before querying.
            raise NoOwner("task status needs an authenticated user")
        row = (await db.execute(
            select(Task).where(Task.id == job_id, Task.owner_user_id == owner)
        )).scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": row.id, "kind": "task", "type": row.type, "status": row.status,
            "retry_count": row.retry_count, "error": row.error_message,
            "completed_at": row.completed_at, "run_id": (row.payload or {}).get("run_id"),
        }

    if job_id.startswith("rrun_"):
        # RLS-scoped: another tenant's run is invisible, so no owner filter here.
        row = (await db.execute(
            select(ResearchRun).where(ResearchRun.id == job_id)
        )).scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": row.id, "kind": "research_run", "status": row.status,
            "error": row.error_message, "completed_at": row.completed_at,
        }

    if job_id.startswith("run_"):
        row = (await db.execute(
            select(ExposureRun).where(ExposureRun.id == job_id)
        )).scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": row.id, "kind": "exposure_run", "status": row.status,
            "error": row.error_message, "completed_at": row.completed_at,
            "as_of_date": row.as_of_date,
        }

    return None
