"""V36 Phase 2 — a domain analyst's reading, on the record.

The brief is spent inside the turn. This is what is left, and the only reason
it is worth keeping is that it passed the same check the answer did, against the
same session ledger. So the two things these tests hold are: a refused report is
kept and MARKED rather than dropped or shown, and a report id from another
conversation is not a way to read one.
"""

from __future__ import annotations

import pytest

from exposure_workbench.agents import delegation as dl, meta_agent
from exposure_workbench.db.models import AnalystReport
from exposure_workbench.services import analyst_reports


class _Result:
    def __init__(self, rows): self._rows = rows
    def scalar_one_or_none(self): return self._rows[0] if self._rows else None
    def scalars(self): return self
    def all(self): return self._rows


class _Db:
    """Enough session to store and read back, with the session scoping applied
    the way the query applies it."""

    def __init__(self): self.rows: list[AnalystReport] = []

    def add(self, row): self.rows.append(row)
    async def flush(self): pass
    async def commit(self): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_e): return False

    async def execute(self, stmt):
        wanted = {str(c.right.value) for c in stmt.whereclause.clauses} if hasattr(stmt.whereclause, "clauses") \
            else {str(stmt.whereclause.right.value)}
        return _Result([r for r in self.rows if {r.id, r.session_id} >= wanted or {r.session_id, r.message_id} >= wanted])


async def _store(db, **kw):
    return await analyst_reports.store(
        db, kw.pop("session_id", "sess_a"),
        **{"domain": "book_liquidity", "status": "verified", "title": "t", "brief": {"findings": []},
           "text": "The book clears in a day.", "blocks": [], "citations": [], "verified": {}, "problems": [],
           **kw})


@pytest.mark.asyncio
async def test_a_report_is_stored_and_read_back_by_its_session():
    db = _Db()
    rid = await _store(db, message_id="msg_1", task_id="tsk_1")
    assert rid.startswith("rep_")
    got = await analyst_reports.load(db, "sess_a", rid)
    assert got["domain"] == "book_liquidity" and got["status"] == "verified"
    assert got["text"] == "The book clears in a day."


@pytest.mark.asyncio
async def test_a_report_of_another_conversation_is_not_readable_by_its_id():
    """RLS refuses another tenant's; nothing in the database has an opinion about
    another SESSION of the same tenant, so the query carries it."""
    db = _Db()
    rid = await _store(db, session_id="sess_a")
    assert await analyst_reports.load(db, "sess_b", rid) is None


@pytest.mark.asyncio
async def test_a_refused_report_is_kept_marked_and_its_prose_withheld_from_the_lead():
    db = _Db()
    rid = await _store(db, status="refused", problems=[{"reason": "mark_mismatch"}],
                       text="MSFT has 4.0% of room.", blocks=[])
    stored = await analyst_reports.load(db, "sess_a", rid)
    assert stored["status"] == "refused" and stored["text"], "kept: the record of what was tried"

    out = await meta_agent._read_report(lambda: db, "sess_a", rid)
    assert out["status"] == "refused"
    assert "text" not in out, "an unchecked reading is not the lead's to quote"
    assert out["problems"] == ["mark_mismatch"]


@pytest.mark.asyncio
async def test_a_verified_report_comes_back_whole_for_the_lead_to_read():
    db = _Db()
    rid = await _store(db, citations=["f_a"])
    out = await meta_agent._read_report(lambda: db, "sess_a", rid)
    assert out["text"] == "The book clears in a day." and out["citations"] == ["f_a"]


@pytest.mark.asyncio
async def test_an_id_from_nowhere_is_told_to_the_lead_not_raised():
    db = _Db()
    out = await meta_agent._read_report(lambda: db, "sess_a", "rep_invented")
    assert out["error"] == "unknown_report" and "this conversation" in out["detail"]
    assert (await meta_agent._read_report(lambda: db, "sess_a", ""))["error"] == "no_report_id"


@pytest.mark.asyncio
async def test_the_prose_is_bounded_at_the_store_not_at_the_reader():
    db = _Db()
    rid = await _store(db, text="x" * (analyst_reports.MAX_TEXT_CHARS + 500))
    assert len((await analyst_reports.load(db, "sess_a", rid))["text"]) == analyst_reports.MAX_TEXT_CHARS


def test_the_lead_can_open_a_report_only_once_one_exists():
    """The tool is on the face after a delegation and not before: a tool whose
    every argument would be invented is a tool that invites inventing one."""
    import inspect
    src = inspect.getsource(meta_agent.handle_message)
    assert "READ_REPORT_TOOL] if delegated else []" in src


def test_the_table_is_owned_by_the_session_and_erased_with_it():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    init_sql = (root / "infra" / "init.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS analyst_reports" in init_sql
    assert "ALTER TABLE analyst_reports ENABLE ROW LEVEL SECURITY" in init_sql
    assert "agent_sessions s WHERE s.id = analyst_reports.session_id" in init_sql
    assert "ADD COLUMN" not in (root / "infra" / "migrations" / "v36_analyst_reports.sql").read_text()
