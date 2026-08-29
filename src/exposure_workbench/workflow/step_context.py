"""Reusable workflow step context — writes workflow_events around a step.

Mirrors the pattern ExposureWorkflow uses, factored out so the new readiness /
research workflows share one implementation without touching the existing
(working) exposure workflow. run_id is a free string (workflow_events lost its
FK in P0), so exposure and research runs share this same timeline machinery.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.errors import classify, detail_of, speaks_for_itself
from exposure_workbench.services import workflow_event_service

logger = logging.getLogger(__name__)


class step:
    """async context manager: logs 'running' on enter, 'completed'/'failed' on exit.

        async with step(db, run_id, "ingest_filings", "Fetching filings"):
            ...
    """

    def __init__(self, db: AsyncSession, run_id: str, step_name: str, message: str):
        self.db = db
        self.run_id = run_id
        self.step_name = step_name
        self.message = message
        self._start_ms = 0
        # Same attribute, same shape, same name as ExposureWorkflow's
        # _StepContext.payload: where a step records WHAT it did in
        # machine-readable form, written to workflow_events.payload_summary by
        # __aexit__. The two wrappers must not diverge on this, and the reason
        # is the shape of the failure when they do, not the untidiness: a step
        # body written against the other wrapper says `ctx.payload = {...}`,
        # which on a plain object SUCCEEDS and is then never read, so the event
        # lands with '{}' and the run looks like it recorded nothing. A green
        # step that hides what it actually did is the defect this attribute
        # exists to end, so it cannot be optional in one of the two places a
        # step is written. Empty here so a step that records nothing writes the
        # same '{}' the column already defaults to.
        self.payload: dict[str, Any] = {}

    async def __aenter__(self):
        self._start_ms = int(time.monotonic() * 1000)
        await workflow_event_service.log_event(
            db=self.db, run_id=self.run_id, step_name=self.step_name,
            status="running", message=self.message,
        )
        await self.db.commit()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int(time.monotonic() * 1000) - self._start_ms
        payload = self.payload
        if exc_type is None:
            # A body that left something other than a dict here — usually None,
            # from a helper that returned early — recorded nothing readable, and
            # log_event's `payload_summary or {}` would quietly turn that into
            # the same '{}' a step that recorded nothing writes. Two events that
            # cannot be told apart for "recorded nothing" and "lost what it
            # recorded" is the failure this attribute exists to end, so the
            # assignment fails here instead of being normalised. {} stays legal:
            # "recorded nothing" is a real state, not an error.
            # _StepContext.__aexit__ carries this same check, deliberately
            # identical; the parametrised tests in tests/test_step_payload.py
            # run both wrappers through it so the two cannot drift.
            if not isinstance(payload, dict):
                raise TypeError(
                    f"step '{self.step_name}' left a non-dict payload "
                    f"({payload!r}); ctx.payload must be a dict, and {{}} is how "
                    f"a step says it recorded nothing"
                )
            status, msg = "completed", self.message
        else:
            # The step's own account, in two registers (V13-S2). `message` is
            # what a person waiting on this run reads, so it stops where the
            # exception's words begin: "Research agent analysing AAPL — stopped",
            # never "— ERROR: Error code: 429 - {'error': {'message': 'You
            # exceeded your current quota…", which is a billing relationship the
            # reader is not party to, and never the internal hostname the tool
            # face names in its own sentence. Both of those really were on the
            # issuer page.
            #
            # The exception's words are not lost — they move into the payload,
            # under a code, where the audit layer reads them. Except when the
            # message was written for the reader in the first place: a refused
            # input names the stale holdings and the way out, and then this
            # carries it, because substituting a generic sentence for that one
            # would be losing information rather than protecting anyone.
            code = classify(exc_val)
            msg = (f"{self.message} — {exc_val}" if speaks_for_itself(code)
                   else f"{self.message} — stopped")
            status = "failed"
            # Same defect, but NOT raised here: the body already has an
            # exception in flight, and raising during its handling would replace
            # the real cause with a complaint about the evidence field — the
            # bigger loss of the two. It is recorded instead, so the event still
            # cannot be confused with one from a step that recorded nothing.
            if not isinstance(payload, dict):
                logger.error(
                    "step '%s' left a non-dict payload (%r) while failing; "
                    "recording the malformation instead of the evidence",
                    self.step_name, payload,
                )
                payload = {"payload_error": repr(payload)}
            # Beside whatever the body recorded, never instead of it: "it
            # ingested 4 filings and then blew up" and "it blew up before
            # ingesting any" stay distinguishable, and now carry why.
            payload = {**payload, "error": {"code": code, "detail": detail_of(exc_val)}}
        # The payload goes out on the failure path too, for the same reason the
        # message does: "it ingested 4 filings and then blew up" and "it blew up
        # before ingesting any" are different diagnoses, and this event is the
        # step's own account of which one happened. It is not the only surviving
        # trace of the work, and here that differs from _StepContext: this
        # wrapper has no rollback branch. Whatever the body committed as it went
        # is already durable, and whatever was still pending is COMMITTED by the
        # line below along with the event — the 4 filings stay in the database
        # as rows either way, where _StepContext would have abandoned them. It
        # cannot be mistaken for a certification: the same row carries
        # status='failed'.
        #
        # Known hazard, deliberately not fixed here: if the body failed with a DB
        # error the session is rollback-only, so log_event's flush raises
        # PendingRollbackError, this event is never written at all, and the
        # caller's session stays poisoned. _StepContext rolls back before its
        # write for exactly that reason; `step` inherited the shape without the
        # reason. Adding a rollback here would abandon the still-pending
        # remainder that readiness_workflow and issuer_research_workflow
        # currently keep, which is a behaviour change of its own and belongs in
        # its own commit.
        await workflow_event_service.log_event(
            db=self.db, run_id=self.run_id, step_name=self.step_name,
            status=status, message=msg, payload_summary=payload,
            duration_ms=duration_ms,
        )
        await self.db.commit()
        return False   # never suppress — fail loud


async def mark_skipped(db: AsyncSession, run_id: str, step_name: str, reason: str) -> None:
    """Record a step explicitly skipped by request (distinct from failed).

    Deliberately takes no payload, unlike `step`. A payload answers "what did
    this body do"; a skipped step has no body, so the honest answer is already
    fully carried by status='skipped' plus `reason`, and an evidence field on an
    event that asserts no work happened is an invitation to write work into it.
    The silent-drop trap that forced `step` to grow a payload does not exist
    here: this is a function, so a caller who passes one anyway gets a TypeError
    at the call site rather than an event that quietly loses it.
    """
    await workflow_event_service.log_event(
        db=db, run_id=run_id, step_name=step_name, status="skipped", message=reason,
    )
    await db.commit()
