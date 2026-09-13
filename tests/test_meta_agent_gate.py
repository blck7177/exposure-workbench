"""V33 — the analyst loop has no ungated exit (offline: no DB, no network, no LLM).

The exit is plain text now, and the text goes through the answer check
(services/answer_check) against the session ledger. Two things still hold from
V3-A0-2 and are pinned here: nothing reaches the user that the check did not
accept, and every path to a turn with no accepted answer converges on ONE
wording, marked in meta so the UI can render it as a refusal.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import evidence_request, meta_agent
from exposure_workbench.agents.meta_agent import _GATE_EXHAUSTED_TEXT, handle_message
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger


class _FakeResult:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return self
    def all(self): return self._rows


class _FakeSession:
    """Just enough session for handle_message: it loads history and adds rows."""

    def __init__(self, store: list): self.store = store
    async def execute(self, *_a, **_k): return _FakeResult(list(self.store))
    def add(self, obj): self.store.append(obj)
    async def commit(self): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_exc): return False


def _factory(store: list):
    return lambda: _FakeSession(store)


def _stub_tools(monkeypatch, result: dict, tools: list | None = None, by_name: dict | None = None):
    """Stand in for the turn's tool session — the broker's door to the face.
    Records every call and every result it handed back, so a test can build the
    ledger the check reads from exactly what the broker fetched."""
    from contextlib import asynccontextmanager

    class _Session:
        def __init__(self):
            self.tools = tools or []
            self.calls: list[tuple[str, dict]] = []
            self.returned: list[dict] = []

        async def call(self, name, args):
            self.calls.append((name, args))
            res = (by_name or {}).get(name, result)
            self.returned.append(res)
            return res

    session = _Session()

    @asynccontextmanager
    async def _fake(*_a, **_k):
        yield session

    monkeypatch.setattr(meta_agent, "tool_session", _fake)
    return session


def _stub_llm(monkeypatch, chat):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    @asynccontextmanager
    async def _fake(*_a, **_k):
        yield SimpleNamespace(chat=chat)

    monkeypatch.setattr(meta_agent, "llm_session", _fake)


def _stub_desk(monkeypatch, session):
    """No database: the briefing is empty and the ledger is whatever facts the
    stubbed face returned this turn — which is what the real ledger holds too."""
    async def _no_briefing(_db_factory, _text):
        return {"subjects": {"tickers": [], "portfolios": [], "runs": []}}

    async def _ledger(_db_factory, _session_id):
        recs = []
        for res in session.returned:
            block = (res or {}).get("facts") or {}
            for row in block.get("rows") or []:
                recs.append(F.from_model_row(row, block.get("sources")))
        return Ledger.of(recs)

    async def _no_record(*_a, **_k):
        return None

    monkeypatch.setattr(meta_agent, "_briefing", _no_briefing)
    monkeypatch.setattr(meta_agent, "_load_ledger", _ledger)
    monkeypatch.setattr(meta_agent, "_record_answer", _no_record)
    monkeypatch.setattr(meta_agent.evidence_broker.Broker, "_record", _no_record)


def _request(*items):
    return [{"id": "c1", "function": {"name": evidence_request.TOOL_NAME, "arguments": json.dumps({"items": list(items)})}}]


def _run_result(*rows, nodes=None):
    """A `run` result as the face returns it: the note and the facts block."""
    return {"program_id": "calc_p", "returns": [], "settled": len(rows), "refused": [],
            "nodes": nodes or {r[8].get("node", "n"): {"kind": "scalar", "fact": r[0]} for r in rows},
            "facts": {"columns": list(F.COLUMNS), "rows": [list(r) for r in rows]}}


_W_MSFT = ("f_wmsft0001", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.16, "2026-09-10", None, {"node": "w"}, ["run_x"])


# ── nothing reaches the user that the check did not accept ───────────────────

@pytest.mark.asyncio
async def test_an_invented_number_is_refused_twice_and_the_turn_ends_on_the_bar(monkeypatch):
    """The path that mattered most in V3: raw model text reaching the user with
    citations=[]. It still cannot: text is the exit, and the exit is checked."""
    async def _no_tools(**_kw):
        return ("NVDA revenue was $999.9B and margins are expanding.", None)

    _stub_llm(monkeypatch, _no_tools)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    store: list = []
    out = await handle_message(_factory(store), "sess_1", "how did NVDA do?", max_turns=6)

    assert out["text"] == _GATE_EXHAUSTED_TEXT
    assert "999.9" not in out["text"]
    assert out["citations"] == []
    assert out["meta"]["gate"] == "exhausted"
    assert out["meta"]["gate_refusals"] == ["unsourced_figure"] * meta_agent.MAX_ANSWER_ATTEMPTS


@pytest.mark.asyncio
async def test_a_loop_that_never_writes_an_answer_says_so_in_the_same_words(monkeypatch):
    async def _always_requests(**_kw):
        return ("", _request({"subjects": ["NVDA"], "want": ["revenue"], "window": "12m"}))

    _stub_llm(monkeypatch, _always_requests)
    session = _stub_tools(monkeypatch, _run_result())
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_2", "how did NVDA do?", max_turns=2)

    assert out["text"] == _GATE_EXHAUSTED_TEXT
    assert out["meta"]["gate"] == "exhausted"
    assert out["meta"]["gate_refusals"] == []            # empty, not absent: the check never ran


@pytest.mark.asyncio
async def test_the_failure_is_persisted_and_marked_not_swallowed(monkeypatch):
    async def _no_tools(**_kw):
        return ("NVDA is 42% of the book.", None)

    _stub_llm(monkeypatch, _no_tools)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    store: list = []
    await handle_message(_factory(store), "sess_3", "hello?", max_turns=4)

    assistant = [m for m in store if getattr(m, "role", None) == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == _GATE_EXHAUSTED_TEXT
    assert assistant[0].meta["gate"] == "exhausted"


@pytest.mark.asyncio
async def test_an_accepted_answer_carries_no_marker(monkeypatch):
    async def _greets(**_kw):
        return ("Hello. Ask me about a holding or an issuer.", None)

    _stub_llm(monkeypatch, _greets)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_4", "hi", max_turns=4)

    assert out["text"] == "Hello. Ask me about a holding or an issuer."
    assert "gate" not in out["meta"]


@pytest.mark.asyncio
async def test_the_refusal_does_not_claim_a_cause_it_did_not_see(monkeypatch):
    async def _no_tools(**_kw):
        return ("NVDA revenue was $999.9B.", None)

    _stub_llm(monkeypatch, _no_tools)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_cause", "how did NVDA do?", max_turns=4)

    assert out["meta"]["gate"] == "exhausted"
    assert "cited evidence I had not actually retrieved" not in out["text"]
    assert "narrow the question" in out["text"]


@pytest.mark.asyncio
async def test_every_turn_records_what_its_prompt_cost(monkeypatch):
    """The count includes the one tool schema and the briefing, which appear on
    every request; a bare system prompt already costs hundreds of tokens once
    they are counted."""
    async def _greets(**_kw):
        return ("Hello.", None)

    _stub_llm(monkeypatch, _greets)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    store: list = []
    out = await handle_message(_factory(store), "sess_5", "hello?", max_turns=1)

    assert out["meta"]["prompt_tokens"] > 500, "the request tool's schema must be in the count"
    assistant = [m for m in store if getattr(m, "role", None) == "assistant"]
    assert assistant[0].meta["prompt_tokens"] == out["meta"]["prompt_tokens"]


# ── the analyst asks, the broker fetches, the check reads what was fetched ───

@pytest.mark.asyncio
async def test_a_request_is_fulfilled_and_the_figure_it_returned_can_be_stated(monkeypatch):
    prompts: list[list[dict]] = []

    async def _chat(messages, tools, **_kw):
        prompts.append(list(messages))
        assert [t["function"]["name"] for t in tools] == [evidence_request.TOOL_NAME]
        if len(prompts) == 1:
            return ("", _request({"subjects": ["port_001"], "want": ["issuer_exposures.weight"]}))
        return ("MSFT is 16.0% of the book.", None)

    _stub_llm(monkeypatch, _chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_6", "how big is MSFT in the book?", max_turns=4)

    assert [n for n, _ in session.calls] == ["run"]                      # the broker ran one program
    assert session.calls[0][1]["program"]["let"], "a compiled program went to the face"
    digest = json.loads([m for m in prompts[1] if m.get("role") == "tool"][0]["content"])
    assert digest["items"][0]["figures"][0]["id"] == "f_wmsft0001"
    assert digest["items"][0]["figures"][0]["value"] == "16.0%"           # as the reader will see it
    assert out["text"] == "MSFT is 16.0% of the book."
    assert out["citations"] == ["f_wmsft0001"]
    assert out["meta"]["format"] == "blocks" and out["meta"]["verified"]["figures"] == 1
    assert "gate" not in out["meta"]
    assert out["meta"]["requests"] == 1


@pytest.mark.asyncio
async def test_a_refused_reply_is_told_every_problem_and_the_second_attempt_can_pass(monkeypatch):
    prompts: list[list[dict]] = []

    async def _chat(messages, tools, **_kw):
        prompts.append(list(messages))
        if len(prompts) == 1:
            return ("", _request({"subjects": ["port_001"], "want": ["issuer_exposures.weight"]}))
        if len(prompts) == 2:
            return ("MSFT is 16.0% of the book, up from 12.5% last year, the largest holding.", None)
        return ("MSFT is 16.0% of the book.", None)

    _stub_llm(monkeypatch, _chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_7", "how big is MSFT?", max_turns=6)

    told = [m for m in prompts[2] if m.get("role") == "user"][-1]["content"]
    assert "unsourced_figure" in told and "12.5%" in told
    assert "superlative_without_rank" in told
    assert out["text"] == "MSFT is 16.0% of the book."
    assert "gate" not in out["meta"]


@pytest.mark.asyncio
async def test_a_call_to_a_tool_the_analyst_does_not_have_is_answered_not_dispatched(monkeypatch):
    prompts: list[list[dict]] = []

    async def _chat(messages, tools, **_kw):
        prompts.append(list(messages))
        if len(prompts) == 1:
            return ("", [{"id": "c9", "function": {"name": "run", "arguments": "{}"}}])
        return ("Hello.", None)

    _stub_llm(monkeypatch, _chat)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_8", "hi", max_turns=4)

    assert session.calls == []
    answered = json.loads([m for m in prompts[1] if m.get("role") == "tool"][0]["content"])
    assert answered["error"] == "unknown_tool"
    assert out["text"] == "Hello."


@pytest.mark.asyncio
async def test_an_empty_completion_is_nudged_to_write_or_ask(monkeypatch):
    prompts: list[list[dict]] = []

    async def _chat(messages, tools, **_kw):
        prompts.append(list(messages))
        return ("", None) if len(prompts) == 1 else ("Hello.", None)

    _stub_llm(monkeypatch, _chat)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_9", "hi", max_turns=4)

    assert prompts[1][-1] == {"role": "user", "content": meta_agent._WRITE_OR_ASK}
    assert out["text"] == "Hello."


def test_the_analysts_only_tool_is_not_a_registry_tool():
    """The budget bounds EVIDENCE, and the analyst retrieves none itself: its one
    tool is in-process, on no face, and every call the broker makes on its
    behalf goes through the face and is charged there."""
    from exposure_workbench.tools import faces
    from exposure_workbench.tools.registries import build_meta_registry

    assert meta_agent._BUDGET_FREE_TOOLS == (evidence_request.TOOL_NAME,)
    assert evidence_request.TOOL_NAME not in build_meta_registry().tools
    assert evidence_request.TOOL_NAME not in faces.FACE_META_AGENT
