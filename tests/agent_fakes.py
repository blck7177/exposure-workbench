"""Fakes for driving the lead and specialist loops offline: a scripted provider, a
tool face that answers from a fixture, a database that records what is written.

Every scripted provider checks its request against tests/provider_contract first,
so a loop that builds a request the provider would refuse fails the test that
drives it.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from exposure_workbench.llm.client import ModelTurn, ToolCall
from tests import provider_contract

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "q07_view.json"


def view_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def tool_turn(*calls: tuple[str, dict], text: str | None = None) -> ModelTurn:
    """A turn that makes these function calls (name, arguments)."""
    out, tcs = [], []
    if text:
        out.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
    for i, (name, args) in enumerate(calls):
        cid = f"call_{name}_{i}_{abs(hash(json.dumps(args, sort_keys=True))) % 10_000}"
        out.append({"type": "function_call", "call_id": cid, "name": name, "arguments": json.dumps(args)})
        tcs.append(ToolCall(cid, name, json.dumps(args)))
    return ModelTurn(text=text, tool_calls=tcs, output=out,
                     usage={"input_tokens": 1000, "output_tokens": 50, "cached_input_tokens": 0, "reasoning_tokens": 10},
                     status="completed", response_id="resp_x", model="scripted")


def text_turn(text: str) -> ModelTurn:
    return ModelTurn(text=text, tool_calls=[],
                     output=[{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}],
                     usage={"input_tokens": 1200, "output_tokens": 80, "cached_input_tokens": 600, "reasoning_tokens": 20},
                     status="completed", response_id="resp_y", model="scripted")


@dataclass
class ScriptedProvider:
    """`respond` as the tests script it: turns handed out in order, requests kept."""
    turns: list[ModelTurn]
    requests: list[dict] = field(default_factory=list)

    async def __call__(self, **kw) -> ModelTurn:
        provider_contract.check(kw["input_items"], kw.get("tools"))
        self.requests.append(kw)
        if not self.turns:
            raise AssertionError("the script ran out of turns: the loop asked once more than scripted")
        return self.turns.pop(0)


class FakeResult:
    rowcount = 1

    def scalars(self):
        return self

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None

    def first(self):
        return None


@dataclass
class Store:
    rows: list = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    reports: list[dict] = field(default_factory=list)
    work_views: list[dict] = field(default_factory=list)


class FakeDb:
    def __init__(self, store: Store):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, row):
        self.store.rows.append(row)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def execute(self, stmt):
        return FakeResult()

    async def get(self, model, key):
        return None


@dataclass
class FakeTools:
    """A tool face: the function tools it lists, and what each call returns."""
    tools: list[dict]
    answers: dict                      # tool name -> dict | callable(args) -> dict
    calls: list[tuple[str, dict, dict]] = field(default_factory=list)

    async def call(self, name, args, *, actor=None, task_id=None):
        self.calls.append((name, json.loads(json.dumps(args)), {"actor": actor, "task_id": task_id}))
        answer = self.answers.get(name)
        if answer is None:
            return {"error": "unknown_tool", "tool": name}
        return answer(args) if callable(answer) else json.loads(json.dumps(answer))


def tool(name: str, params: dict | None = None) -> dict:
    return {"type": "function", "name": name, "description": f"fake {name}",
            "parameters": params or {"type": "object", "properties": {}, "additionalProperties": True}, "strict": False}


def fake_tool_session(faces: dict[str, FakeTools]):
    """`tool_session(face_name, **kw)` yielding the fake for that face."""
    opened: list[str] = []

    @asynccontextmanager
    async def _session(face_name, **kw):
        opened.append(face_name)
        yield faces[face_name]

    _session.opened = opened
    return _session


def install(monkeypatch, *, provider: ScriptedProvider, faces: dict[str, FakeTools], store: Store,
            ledger_records: list[dict], catalogue: dict | None = None):
    """Wire the fakes into the loops. Returns the db_factory."""
    from exposure_workbench.agents import lead, specialist, research_session, work_view as wvm
    from exposure_workbench.llm import client as llm_client
    from exposure_workbench.services import analyst_reports, ledger as ledger_svc, scope as scope_svc, trace_service
    from exposure_workbench.services.ledger import Ledger

    monkeypatch.setattr(llm_client, "respond", provider)
    session = fake_tool_session(faces)
    monkeypatch.setattr(lead, "tool_session", session)
    monkeypatch.setattr(specialist, "tool_session", session, raising=False)
    monkeypatch.setattr(research_session, "tool_session", session)

    async def _record_step(db, session_id, **kw):
        store.steps.append({"session_id": session_id, **kw})
        return f"step_{len(store.steps)}"
    monkeypatch.setattr(trace_service, "record_step", _record_step)

    async def _load(db, session_id):
        return Ledger.of([dict(r) for r in ledger_records])
    monkeypatch.setattr(ledger_svc, "load", _load)

    async def _store(db, session_id, **cols):
        store.reports.append({"session_id": session_id, **cols})
        return f"rep_{len(store.reports)}"
    monkeypatch.setattr(analyst_reports, "store", _store)

    async def _save(db, wv):
        store.work_views.append(wv.record())
        wv.version += 1
    monkeypatch.setattr(wvm, "save", _save)

    async def _history(db, session_id):
        return [{"role": "user", "content": "q"}]
    monkeypatch.setattr(lead, "_load_history", _history)

    async def _catalogue(db):
        return catalogue or {"books": [{"portfolio_id": "port_001", "name": "Demo", "runs": {"latest": {"id": "run_e2945c5ebd5a", "as_of": "2026-09-10"}, "prev": {"id": "run_4ee5ca92b926", "as_of": "2026-09-09"}},
                                                  "holdings": [{"ticker": "MSFT", "sector": "Technology"}, {"ticker": "AAPL", "sector": "Technology"}, {"ticker": "NVDA", "sector": "Technology"}, {"ticker": "JPM", "sector": "Financials"}]}],
                            "issuers_on_desk": ["AAPL", "JPM", "MSFT", "NVDA"], "issuers_preparing": []}
    monkeypatch.setattr(scope_svc, "catalogue", _catalogue)

    async def _bind(db, spec):
        subjects = spec.get("subjects") or ["AAPL", "MSFT", "NVDA"]
        return scope_svc.Scope(subjects=tuple(subjects), book=spec.get("book"), runs={}, basis=spec.get("basis") or "test",
                               expected_count=spec.get("expected_count"), status="resolved")
    monkeypatch.setattr(scope_svc, "bind", _bind)

    def db_factory():
        return FakeDb(store)
    return db_factory
