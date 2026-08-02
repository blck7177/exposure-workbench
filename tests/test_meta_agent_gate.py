"""V3-A0-2 — the loop has no ungated exit (offline: no DB, no network, no LLM).

Two paths used to hand the user something the citation gate had never accepted,
and they are the same event wearing different clothes: the model stops calling
tools on the last turn, or it burns every turn without a respond the gate takes.
Both must converge on one refusal, marked so the UI can render it as one.
"""

from __future__ import annotations

import pytest

from exposure_workbench.agents import meta_agent
from exposure_workbench.agents.meta_agent import _GATE_EXHAUSTED_TEXT, handle_message


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


@pytest.mark.asyncio
async def test_a_model_that_stops_calling_tools_does_not_get_its_text_published(monkeypatch):
    """The path that mattered most: on the final turn the loop used to assign the
    raw model content as the answer. It reached the user with citations=[],
    rendered identically to a verified reply, having passed no gate at all."""
    async def _no_tools(**_kw):
        return ("NVDA revenue was $999.9B and margins are expanding.", None, {})

    monkeypatch.setattr(meta_agent.llm_client, "chat_with_tools", _no_tools)
    store: list = []
    out = await handle_message(_factory(store), "sess_1", "how did NVDA do?", max_turns=1)

    assert out["text"] == _GATE_EXHAUSTED_TEXT
    assert "999.9" not in out["text"]
    assert out["citations"] == []
    assert out["meta"]["gate"] == "exhausted"


@pytest.mark.asyncio
async def test_a_loop_that_never_reaches_respond_says_so_in_the_same_words(monkeypatch):
    """The commoner path — turns spent on tools, or every respond refused. It
    used to emit "(no response produced)", which reads as a crash rather than as
    a refusal, and carried no marker at all."""
    async def _always_thinks(**_kw):
        return ("", [{"id": "c1", "function": {"name": "think", "arguments": '{"thought":"hm"}'}}], {})

    async def _invoke(*_a, **_k):
        return {"noted": True}

    monkeypatch.setattr(meta_agent.llm_client, "chat_with_tools", _always_thinks)
    monkeypatch.setattr(meta_agent, "invoke", _invoke)
    store: list = []
    out = await handle_message(_factory(store), "sess_2", "how did NVDA do?", max_turns=2)

    assert out["text"] == _GATE_EXHAUSTED_TEXT
    assert out["meta"]["gate"] == "exhausted"


@pytest.mark.asyncio
async def test_the_failure_is_persisted_and_marked_not_swallowed(monkeypatch):
    """A 200 with a marked message, not a 500 and not silence. The chat_turn
    quota was charged and committed before the loop began, the work was really
    done, and dropping the turn would leave the user's question in the
    transcript with no reply and nothing to explain it."""
    async def _no_tools(**_kw):
        return ("whatever", None, {})

    monkeypatch.setattr(meta_agent.llm_client, "chat_with_tools", _no_tools)
    store: list = []
    await handle_message(_factory(store), "sess_3", "hello?", max_turns=1)

    assistant = [m for m in store if getattr(m, "role", None) == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == _GATE_EXHAUSTED_TEXT
    assert assistant[0].meta["gate"] == "exhausted"


@pytest.mark.asyncio
async def test_an_accepted_answer_carries_no_marker(monkeypatch):
    """The marker must mean something, so it has to be absent on the happy path."""
    async def _responds(**_kw):
        return ("", [{"id": "c1", "function": {"name": "respond",
                                               "arguments": '{"text":"Hello.","citations":[]}'}}], {})

    async def _invoke(*_a, **_k):
        return {"responded": True, "text": "Hello.", "citations": []}

    monkeypatch.setattr(meta_agent.llm_client, "chat_with_tools", _responds)
    monkeypatch.setattr(meta_agent, "invoke", _invoke)
    store: list = []
    out = await handle_message(_factory(store), "sess_4", "hi", max_turns=4)

    assert out["text"] == "Hello."
    assert "gate" not in out["meta"]


@pytest.mark.asyncio
async def test_every_turn_records_what_its_prompt_cost(monkeypatch):
    """V3-B0. Measurement, not policy: B1 refuses on this number and B3's
    go/no-go on summarisation is decided by its distribution, so it has to exist
    before either. The count includes the tool schemas, which are sent on every
    request and appear nowhere in `messages` — a bare system prompt already costs
    thousands of tokens once they are counted."""
    async def _no_tools(**_kw):
        return ("whatever", None, {})

    monkeypatch.setattr(meta_agent.llm_client, "chat_with_tools", _no_tools)
    store: list = []
    out = await handle_message(_factory(store), "sess_5", "hello?", max_turns=1)

    assert out["meta"]["prompt_tokens"] > 1000, "tool schemas must be in the count"
    assistant = [m for m in store if getattr(m, "role", None) == "assistant"]
    assert assistant[0].meta["prompt_tokens"] == out["meta"]["prompt_tokens"]
