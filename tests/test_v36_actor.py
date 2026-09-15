"""V36 Phase 0 — a step says which agent took it (offline: no DB, no network).

A turn holds more than one agent from V36 on, and the reading a round is judged
by is which two nodes talked, how often, and carrying what. `step_type` cannot
answer it: the lead analyst and a domain analyst call the same tools through the
same wrapper. So the row carries the actor, and the two writers that exist —
the registry wrapper through `record_step`, and `llm_session` for the completion
that decided on the call — both have to be able to name one.

Null is the lead analyst, which is what every row written before V36 is; nothing
is backfilled and nothing has to be.
"""

from __future__ import annotations

import pytest

from exposure_workbench.agents import llm_session as ls
from exposure_workbench.services import trace_service


class _FakeResult:
    def __init__(self, value): self._value = value
    def scalar_one(self): return self._value


class _FakeSession:
    def __init__(self): self.added: list = []
    async def execute(self, *_a, **_k): return _FakeResult(1)
    def add(self, obj): self.added.append(obj)
    async def flush(self): pass
    async def commit(self): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_exc): return False


async def _record(**kw):
    db = _FakeSession()
    await trace_service.record_step(
        db, "sess_x", step_type=kw.pop("step_type", "tool_call"), tool_name=kw.pop("tool_name", "run"),
        args={"program": {}}, result_summary="ok", evidence_refs=[], **kw)
    return db.added[0]


@pytest.mark.asyncio
async def test_a_step_with_no_actor_is_the_lead_analysts():
    """Every row before V36 has no actor, and reading them as the lead's is what
    makes the column additive rather than a migration of 3,000 rows."""
    step = await _record()
    assert step.actor is None


@pytest.mark.asyncio
async def test_a_domain_analysts_step_carries_its_domain():
    step = await _record(actor="sub:book_limits_and_triggers")
    assert step.actor == "sub:book_limits_and_triggers"


@pytest.mark.asyncio
async def test_the_completion_that_decided_on_a_call_carries_the_same_actor(monkeypatch):
    """The two writers have to agree, or a turn's table shows a sub-analyst
    calling tools with nobody having thought about it."""
    rows: list = []

    async def _fake_chat(**_kw):
        return "", None, {"model": "m", "prompt_tokens": 10, "completion_tokens": 2}

    async def _fake_record(_db, session_id, **kw):
        rows.append(kw)
        return "step_1"

    monkeypatch.setattr(ls.llm_client, "chat_with_tools", _fake_chat)
    monkeypatch.setattr(ls.trace_service, "record_step", _fake_record)

    lead = ls.LlmSession(lambda: _FakeSession(), "sess_x", "msg_x")
    await lead.chat(messages=[])
    sub = lead.for_actor("sub:book_liquidity")
    await sub.chat(messages=[])

    assert [r["actor"] for r in rows] == [None, "sub:book_liquidity"]
    assert [r["step_type"] for r in rows] == ["llm_call", "llm_call"]


@pytest.mark.asyncio
async def test_a_sub_analysts_session_is_the_same_session_and_message(monkeypatch):
    """D3: the domain analyst runs inside the lead's turn. If `for_actor` opened
    a session of its own, the facts it fetched would land on a ledger the answer
    check never reads, and every figure the lead wrote from them would be
    refused as not_on_ledger."""
    lead = ls.LlmSession(lambda: _FakeSession(), "sess_x", "msg_x")
    sub = lead.for_actor("sub:book_market_risk")
    assert (sub._session_id, sub._message_id) == (lead._session_id, lead._message_id)
    assert sub._db_factory is lead._db_factory


def test_the_column_exists_in_the_schema_and_in_a_migration():
    """A model column with no DDL behind it is a column that works in tests and
    raises in production."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    init_sql = (root / "infra" / "init.sql").read_text()
    agent_steps = init_sql[init_sql.index("CREATE TABLE IF NOT EXISTS agent_steps"):]
    agent_steps = agent_steps[: agent_steps.index(");")]
    assert "actor" in agent_steps

    migration = (root / "infra" / "migrations" / "v36_actor.sql").read_text()
    assert "ADD COLUMN IF NOT EXISTS actor" in migration


@pytest.mark.asyncio
async def test_what_a_completion_read_is_on_its_row_and_never_sent_to_the_provider(monkeypatch):
    """V36.1: round A's table had a size for every edge except the ones into a
    completion — the digest, the delegate return, the refusal — which were the
    largest. The loop measures them and the row carries the measure as args;
    the provider sees the messages and nothing else."""
    rows: list = []
    sent: list = []

    async def _fake_chat(**kw):
        sent.append(kw)
        return "", None, {"model": "m", "prompt_tokens": 10, "completion_tokens": 2}

    async def _fake_record(_db, session_id, **kw):
        rows.append(kw)
        return "step_1"

    monkeypatch.setattr(ls.llm_client, "chat_with_tools", _fake_chat)
    monkeypatch.setattr(ls.trace_service, "record_step", _fake_record)
    lead = ls.LlmSession(lambda: _FakeSession(), "sess_x", "msg_x")
    await lead.chat(messages=[], note={"read": {"chars": 16650, "results": 1}})
    await lead.chat(messages=[])
    assert [r["args"] for r in rows] == [{"read": {"chars": 16650, "results": 1}}, None]
    assert all("note" not in kw for kw in sent)
