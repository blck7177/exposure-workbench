"""One company is ingested once at a time, whoever asked (V7-D6).

Two users pressing Investigate on the same cold issuer start two runs that are
invisible to each other — research_runs is RLS-private, and deliberately so:
refusing B because A is running would mean B never gets a brief, and telling B
about A's run would hand one tenant another's run id. So both proceed, and both
reach the same SHARED tables.

Every ingest step is already written to be re-runnable: index_filing asks
is_indexed first, fact extraction upserts, filings dedupe on accession. What
none of them survive is being run CONCURRENTLY — two runs check is_indexed at
the same moment, both see nothing, and both write the chunks. filing_chunks has
no unique constraint to catch it (that is a separate debt), so the duplicate is
silent and permanent, and every later retrieval over that filing is scored
against two copies of the same passage.

Serialising them is therefore not an optimisation. It is what makes the
idempotence each step already claims actually hold. Note what this file
deliberately does NOT do: re-check readiness after taking the lock. The steps
each answer that for themselves, and a second opinion at the top would be a
second place deciding what "already ingested" means.

A SESSION-level advisory lock on a connection of its own, not a transaction-level
one on the caller's: readiness commits after every step, and a transaction-level
lock would be released by the first of those commits, half way through the work
it is supposed to be guarding. Nothing has to clean up after a crash — Postgres
drops session locks when the connection goes, and the connection goes when the
process does.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Callable

from sqlalchemy import text

from exposure_workbench.db.session import get_engine

logger = logging.getLogger(__name__)

# The first half of Postgres's two-int lock key, so these can never collide with
# an advisory lock some other part of the system takes for its own reasons. The
# value is arbitrary and only has to be ours.
_INGEST_NAMESPACE = 0x45570001


@asynccontextmanager
async def ingest_lock(
    company_id: str,
    *,
    announce_wait: Callable[[], Any] | None = None,
):
    """Hold the shared-ingest lock for `company_id` for the length of the block.

    `announce_wait` is an async context manager FACTORY, entered only when the
    lock is already held by someone else and kept open for as long as the wait
    lasts. It exists because the wait is minutes of an EDGAR ingest that belongs
    to another run, and a caller that can put a step on its own timeline should
    say so WHILE it waits rather than afterwards — a person watching a blank
    page cannot tell waiting from hung. A callable rather than an imported step
    helper because this is the service layer: it must not know that workflows
    have timelines.

    The key is hashtext(company_id), so two different companies could in
    principle share a lock. The cost of that collision is one run waiting for
    another it did not need to wait for; the cost of getting the identity wrong
    in the other direction would be the duplicate this file exists to prevent.
    """
    # Its own connection, checked out of the same pool the app uses. It stays
    # checked out for the whole ingest, which is why D10 raised max_connections:
    # three worker replicas ingesting three different issuers hold three of
    # these on top of their session pools.
    async with get_engine().connect() as conn:
        params = {"ns": _INGEST_NAMESPACE, "cid": company_id}
        got = (await conn.execute(
            text("SELECT pg_try_advisory_lock(:ns, hashtext(:cid))"), params
        )).scalar()

        if not got:
            logger.info("ingest lock for %s is held; waiting", company_id)
            if announce_wait is None:
                await conn.execute(text("SELECT pg_advisory_lock(:ns, hashtext(:cid))"), params)
            else:
                async with announce_wait():
                    # Blocks here, inside the announcement, which is the whole
                    # point: the step is open on the timeline for exactly as
                    # long as the wait.
                    await conn.execute(text("SELECT pg_advisory_lock(:ns, hashtext(:cid))"), params)

        try:
            yield
        finally:
            # Explicit, though the connection closing would also do it: a lock
            # released at a named moment is one a reader can reason about, and
            # a pooled connection may be recycled rather than closed.
            await conn.execute(text("SELECT pg_advisory_unlock(:ns, hashtext(:cid))"), params)
