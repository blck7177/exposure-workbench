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
async def test_a_refused_brief_is_kept_and_marked():
    db = _Db()
    rid = await _store(db, status="refused", problems=[{"reason": "mark_mismatch"}],
                       text="tsk_1 — the risk analyst …", blocks=[])
    stored = await analyst_reports.load(db, "sess_a", rid)
    assert stored["status"] == "refused" and stored["text"], "kept: the record of what was tried"
    assert stored["blocks"] == [], "and never rendered as if its findings had passed"


# ── V1: what is on the record is opened by its id, and nothing else is ───────

class _TaskDb(_Db):
    """The same store, answering the query `load_by_task` makes."""

    async def execute(self, stmt):
        wanted = {str(c.right.value) for c in stmt.whereclause.clauses}
        return _Result([r for r in self.rows if {r.task_id, r.session_id} >= wanted])


@pytest.mark.asyncio
async def test_the_lead_opens_an_analysts_log_by_the_tasks_id(monkeypatch):
    """V1: the text on the record is the LOG — the analyst's calls in order, each
    with why — and `open(<task id>)` reads it, for a task of an earlier turn too."""
    db = _TaskDb()
    await _store(db, task_id="tsk_1", text="tsk_1 — the risk analyst, asked about port_001: 1. how big is MSFT\n"
                                           "1. book_read(book=\"port_001\") — why: line 1 asks the weight → 1 row")
    out = await meta_agent._open(lambda: db, "sess_a", "tsk_1", delegated=[])
    assert out["log"].startswith("tsk_1 — the risk analyst") and "why: line 1 asks the weight" in out["log"]
    assert (await meta_agent._open(lambda: db, "sess_b", "tsk_1", delegated=[]))["error"] == "unknown_task"


@pytest.mark.asyncio
async def test_a_task_of_this_turn_opens_from_the_turn_itself():
    task = dl.Task("tsk_9", "market", ("AAPL",), ("has volatility risen",))
    result = dl.AnalystResult(task=task, status="settled", log=[
        {"step": 1, "tool": "metric", "asked": 'name="price.volatility"', "why": "line 1: the short window", "got": "1 row"}])
    out = await meta_agent._open(None, "sess_a", "tsk_9", delegated=[result])
    assert out == {"log": dl.log_text(result)}
    assert "1. metric(name=\"price.volatility\") — why: line 1: the short window → 1 row" in out["log"]


@pytest.mark.asyncio
async def test_an_id_from_nowhere_is_told_to_the_lead_not_raised(monkeypatch):
    from exposure_workbench.services.ledger import Ledger

    async def _ledger(_f, _s):
        return Ledger()
    monkeypatch.setattr(meta_agent, "_load_ledger", _ledger)
    assert (await meta_agent._open(None, "sess_a", "", delegated=[]))["error"] == "no_id"
    assert (await meta_agent._open(None, "sess_a", "rep_invented", delegated=[]))["error"] == "unknown_id"
    assert (await meta_agent._open(None, "sess_a", "f_invented", delegated=[]))["error"] == "not_on_the_record"
    # a standing policy is on every ledger: it opens as its row
    assert "The desk does not forecast" in (await meta_agent._open(None, "sess_a", "f_policy_no_forecast", delegated=[]))["row"]


@pytest.mark.asyncio
async def test_the_prose_is_bounded_at_the_store_not_at_the_reader():
    db = _Db()
    rid = await _store(db, text="x" * (analyst_reports.MAX_TEXT_CHARS + 500))
    assert len((await analyst_reports.load(db, "sess_a", rid))["text"]) == analyst_reports.MAX_TEXT_CHARS


def test_the_lead_can_open_the_record_only_once_something_is_on_it():
    """The tool is offered after an ask and not before: a tool whose every
    argument would be invented is a tool that invites inventing one."""
    import inspect
    src = inspect.getsource(meta_agent.handle_message)
    assert "OPEN_TOOL] if delegated else []" in src


def test_the_table_is_owned_by_the_session_and_erased_with_it():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    init_sql = (root / "infra" / "init.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS analyst_reports" in init_sql
    assert "ALTER TABLE analyst_reports ENABLE ROW LEVEL SECURITY" in init_sql
    assert "agent_sessions s WHERE s.id = analyst_reports.session_id" in init_sql
    assert "ADD COLUMN" not in (root / "infra" / "migrations" / "v36_analyst_reports.sql").read_text()
