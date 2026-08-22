"""V7-D6 — one company is ingested once at a time (offline).

The defect this guards is silent and permanent. Two users investigate the same
cold issuer; their runs cannot see each other (research_runs is RLS-private, and
that is deliberate); both reach index_filing, both ask is_indexed, both are told
no, and both write the chunks. filing_chunks has no unique constraint to catch
it, so from then on every retrieval over that filing scores two copies of the
same passage and nothing anywhere says so.

What is asserted here is the mechanism, not the SQL: that the second caller
waits, that it announces the wait while it is waiting rather than afterwards,
and that the lock is released on the way out including when the body raises.
The statements themselves are checked by their shape — a live test would need
two connections and a real ingest, which is the boss's acceptance, not this
file's.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from exposure_workbench.services import ingest_lock_service as ils


class _FakeConn:
    """Enough connection to record what the lock asked the database to do."""

    def __init__(self, script):
        self.statements: list[tuple[str, dict]] = []
        self._script = list(script)      # values pg_try_advisory_lock returns
        self.blocked = asyncio.Event()

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.statements.append((sql, params or {}))

        class _R:
            def __init__(self, v): self._v = v
            def scalar(self): return self._v

        if "pg_try_advisory_lock" in sql:
            return _R(self._script.pop(0) if self._script else True)
        if "pg_advisory_lock" in sql:
            # The blocking form. Signal that we reached it, so a test can assert
            # what was true DURING the wait rather than after it.
            self.blocked.set()
            return _R(None)
        return _R(None)

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False


def _engine_returning(conn):
    class _E:
        def connect(self): return conn
    return _E()


@pytest.fixture
def conn_taken_first_try(monkeypatch):
    c = _FakeConn([True])
    monkeypatch.setattr(ils, "get_engine", lambda: _engine_returning(c))
    return c


@pytest.fixture
def conn_must_wait(monkeypatch):
    c = _FakeConn([False])
    monkeypatch.setattr(ils, "get_engine", lambda: _engine_returning(c))
    return c


async def test_the_uncontended_case_never_blocks(conn_taken_first_try):
    """try_advisory_lock succeeded, so the blocking form must not be reached.

    If it were, one run ingesting alone would still take the slow path, and the
    difference would be invisible until someone timed it.
    """
    async with ils.ingest_lock("co_nvda"):
        pass
    sql = [s for s, _ in conn_taken_first_try.statements]
    assert any("pg_try_advisory_lock" in s for s in sql)
    assert not any(s.startswith("SELECT pg_advisory_lock") for s in sql)
    assert any("pg_advisory_unlock" in s for s in sql)


async def test_the_contended_case_waits_and_says_so_while_waiting(conn_must_wait):
    """The announcement is open FOR the wait, not after it.

    This is the whole reason the callback is a context manager: a step opened
    after the wait ends tells the timeline something it can no longer act on,
    and the person watching the page saw nothing for the minutes that mattered.
    """
    opened_before_block = None

    @asynccontextmanager
    async def announce():
        nonlocal opened_before_block
        # True if we are inside the announcement and the blocking call has not
        # been reached yet — i.e. the step opens first.
        opened_before_block = not conn_must_wait.blocked.is_set()
        yield

    async with ils.ingest_lock("co_nvda", announce_wait=announce):
        pass

    assert opened_before_block is True, "the wait was announced after it ended"
    assert conn_must_wait.blocked.is_set(), "the contended caller never blocked"


async def test_the_lock_is_released_when_the_body_raises(conn_taken_first_try):
    """A failed ingest must not leave the next run waiting on a dead hand.

    The connection closing would release it too, but this asserts the explicit
    release, because the connection comes from a pool and may be recycled rather
    than closed.
    """
    with pytest.raises(RuntimeError):
        async with ils.ingest_lock("co_nvda"):
            raise RuntimeError("EDGAR fell over")
    assert any("pg_advisory_unlock" in s for s, _ in conn_taken_first_try.statements)


async def test_the_key_is_the_company_and_a_namespace_of_ours(conn_taken_first_try):
    """Keyed on company_id, in a namespace nothing else in this system uses.

    Same company, same key, or the serialisation does not happen; a private
    namespace, or an unrelated advisory lock elsewhere could collide with these
    and serialise two things that have nothing to do with each other.
    """
    async with ils.ingest_lock("co_nvda"):
        pass
    _, params = conn_taken_first_try.statements[0]
    assert params["cid"] == "co_nvda"
    assert params["ns"] == ils._INGEST_NAMESPACE


def test_readiness_holds_the_lock_over_the_shared_writes_only():
    """Steps 2-6 inside, step 1 and step 7 outside — read as source, on purpose.

    Step 1 produces the company_id the lock is keyed on, so it cannot be inside.
    Step 7 is the calc ledger, which is append-only BY DESIGN: two runs minting
    their own calc ids is correct, and holding a lock across it would serialise
    work with no reason to wait. Both boundaries are decisions, and a decision
    that only exists as indentation is one a later edit moves without noticing.
    """
    import inspect
    from exposure_workbench.workflow import readiness_workflow as rw

    src = inspect.getsource(rw.run_readiness)
    lock_at = src.index("async with ingest_lock(")
    assert src.index('"resolve_company"') < lock_at, "step 1 must precede the lock"
    for guarded in ('"ingest_filings"', '"extract_facts"', '"index_filings"', '"refresh_market_data"'):
        assert src.index(guarded) > lock_at, f"{guarded} must be inside the lock"

    # step 7 is outside: its line is back at the function's own indentation.
    recipe_line = next(l for l in src.splitlines() if '"standard_recipe"' in l)
    assert recipe_line.startswith("    async with"), "step 7 must be outside the lock"
