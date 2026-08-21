"""V4-S2 — the completion leaves a row (offline: no DB, no network, no LLM).

The thing under test is an ABSENCE with a mechanism behind it. Before S2 both
loops received `usage` and dropped it, and no test could have caught that,
because dropping a return value is not a failure: everything works, the answers
are right, and the only symptom is a cost report that says zero for ever.

So these are written against the mechanism rather than the behaviour. chat()
hands back two things and not three (nothing left to discard), the row carries
what a bill is settled from (model version, both token counts, whose turn it
was), and a database that is down costs the user nothing — the completion is
already paid for by the time the write is attempted.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from exposure_workbench.agents.llm_session import llm_session
from exposure_workbench.db.models import AgentStep, IssuerBrief

ROOT = Path(__file__).resolve().parents[1]


class _FakeResult:
    """record_step's `max(seq) + 1` lookup, answered without a database."""

    def scalar_one(self):
        return 1


class _FakeDb:
    def __init__(self, rows: list, fail_on_commit: bool = False):
        self.rows = rows
        self.fail_on_commit = fail_on_commit
        self.committed = False

    async def execute(self, *_a, **_k):
        return _FakeResult()

    def add(self, obj):
        self.rows.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        if self.fail_on_commit:
            raise RuntimeError("connection refused")
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def _factory(rows: list, **kw):
    return lambda: _FakeDb(rows, **kw)


def _stub_completion(monkeypatch, *, content="hi", tool_calls=None,
                     model="gpt-5.1-2026-04-14", prompt=1204, completion=87):
    """Stand in for the provider at the seam llm_session actually uses."""
    from exposure_workbench.agents import llm_session as module

    async def _chat_with_tools(**_kw):
        return content, tool_calls, {
            "model": model, "prompt_tokens": prompt, "completion_tokens": completion,
        }

    monkeypatch.setattr(module.llm_client, "chat_with_tools", _chat_with_tools)


@pytest.mark.asyncio
async def test_a_completion_leaves_a_row(monkeypatch):
    _stub_completion(monkeypatch, tool_calls=[{"id": "c1"}, {"id": "c2"}])
    rows: list = []

    async with llm_session(_factory(rows), "sess_1", "msg_1") as llm:
        await llm.chat(messages=[{"role": "user", "content": "hi"}], tools=[])

    step = next(r for r in rows if isinstance(r, AgentStep))
    assert step.step_type == "llm_call"
    assert step.session_id == "sess_1"
    assert step.message_id == "msg_1", "a chat turn's cost belongs to that turn"
    assert step.prompt_tokens == 1204 and step.completion_tokens == 87
    assert step.tool_name is None, "nothing was called; this IS the call"
    assert "gpt-5.1-2026-04-14" in step.result_summary
    assert "2 tool calls" in step.result_summary


@pytest.mark.asyncio
async def test_the_loop_is_never_handed_the_usage_it_used_to_discard(monkeypatch):
    """D1 as a return value. The old loops did `content, tool_calls, _usage =`
    and `..., usage =` — one underscored it, one bound it and never read it, and
    both were free to. Two values is the enforcement: there is no third thing to
    ignore, so no version of a loop can spend money quietly."""
    _stub_completion(monkeypatch)
    rows: list = []

    async with llm_session(_factory(rows), "sess_2") as llm:
        out = await llm.chat(messages=[], tools=[])

    assert len(out) == 2
    content, tool_calls = out
    assert content == "hi" and tool_calls is None


@pytest.mark.asyncio
async def test_a_broken_ledger_does_not_cost_the_user_their_turn(monkeypatch, caplog):
    """invoke() makes the same choice about its own trace write, and here there
    is more at stake: the provider has already been paid and the answer is in
    hand. Raising would throw away a turn the user was charged for, and the row
    would still be missing. Loud in the log, whole to the caller."""
    _stub_completion(monkeypatch, content="the answer")
    rows: list = []

    with caplog.at_level("ERROR"):
        async with llm_session(_factory(rows, fail_on_commit=True), "sess_3") as llm:
            content, _ = await llm.chat(messages=[], tools=[])

    assert content == "the answer"
    assert any("llm_call" in r.getMessage() for r in caplog.records), (
        "a hole in the cost ledger must be visible somewhere"
    )


@pytest.mark.asyncio
async def test_a_usage_dict_of_the_wrong_shape_stops_the_turn(monkeypatch):
    """The other half of the failure split, and the reason the unpacking sits
    outside the try. A missing key is chat_with_tools having changed shape — a
    code error, which must fail on the first turn that meets it. Swallowed into
    the log beside a real database outage, it would read as an infrastructure
    problem while every completion silently stopped being counted."""
    from exposure_workbench.agents import llm_session as module

    async def _old_shape(**_kw):
        return "hi", None, {"prompt_tokens": 1, "completion_tokens": 2}

    monkeypatch.setattr(module.llm_client, "chat_with_tools", _old_shape)
    rows: list = []

    with pytest.raises(KeyError):
        async with llm_session(_factory(rows), "sess_4") as llm:
            await llm.chat(messages=[], tools=[])


@pytest.mark.asyncio
async def test_the_recorded_model_is_the_one_the_provider_served(monkeypatch):
    """Section 9 asks for the model VERSION. settings.openai_model is an alias:
    it moves under the account without a deploy, so a row stamped with it cannot
    answer which model charged this."""
    from exposure_workbench.llm import client as llm_client

    served = "gpt-5.1-2026-04-14"

    class _Completions:
        async def create(self, **_kw):
            return SimpleNamespace(
                model=served,
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
                usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
            )

    monkeypatch.setattr(
        llm_client, "get_openai_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=_Completions())),
    )

    _content, _calls, usage = await llm_client.chat_with_tools(
        messages=[], tools=[], model="gpt-5.1",
    )
    assert usage["model"] == served != "gpt-5.1"
    assert usage["prompt_tokens"] == 11 and usage["completion_tokens"] == 22


# ── the shape of the account ─────────────────────────────────────────────────

def test_a_brief_carries_no_cost_columns_of_its_own():
    """Deleted, not deprecated (v4_cost.sql). They were a fossil of the v2 shape
    where one artifact was one completion — daily_reports still is that, which is
    why its identical columns are alive. A brief is what a 30-turn session ends
    with, so nothing could ever have written them, and nothing did."""
    dead = {"llm_model", "prompt_tokens", "completion_tokens"}
    assert dead & set(IssuerBrief.__table__.columns.keys()) == set(), (
        "the brief is claiming a cost the session is the only place to ask about"
    )


def _v4_sql() -> str:
    return (ROOT / "infra" / "migrations" / "v4_cost.sql").read_text(encoding="utf-8")


def test_every_cost_view_reads_with_the_callers_privileges():
    """V2-E0's lesson, which cost this project a measured RLS bypass: a view
    without security_invoker runs as its DEFINER (the owner role, which bypasses
    RLS), so app_rls reads every tenant's spend through it. These three are views
    over agent_sessions and agent_steps, so all three need it."""
    sql = _v4_sql()
    views = re.findall(r"CREATE OR REPLACE VIEW (\w+)(.*?)AS", sql, flags=re.DOTALL)
    assert len(views) == 3, f"expected three cost views, found {[v[0] for v in views]}"
    for name, preamble in views:
        assert "security_invoker = true" in preamble, (
            f"{name} would report every tenant's spend to any caller"
        )


def test_the_migration_only_drops_columns_nothing_writes():
    """A DROP is the one irreversible statement in these files. Each of these
    three was verified empty and reader-less before it was written down; a fourth
    name appearing here is a decision that needs the same evidence."""
    dropped = set(re.findall(r"ALTER TABLE issuer_briefs DROP COLUMN IF EXISTS (\w+);", _v4_sql()))
    assert dropped == {"llm_model", "prompt_tokens", "completion_tokens"}
    assert "DROP TABLE" not in _v4_sql(), "no migration in this project drops a table"
