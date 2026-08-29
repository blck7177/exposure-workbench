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
from exposure_workbench.tools import faces
from exposure_workbench.tools.registries import build_meta_registry


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


def _stub_tools(monkeypatch, result: dict, tools: list | None = None,
                by_name: dict | None = None):
    """Stand in for the turn's tool session.

    These tests are about what the loop does with a tool RESULT — publishing an
    ungated answer, marking an exhausted gate — so the tools themselves are the
    part to hold still. The seam moved out one layer when the loop stopped
    calling invoke() directly and started calling a client (MCP_PLAN P3), and
    out again at R4, when that client became a connection to another process
    carrying a minted identity. It is still one substitution, and it is still
    the whole tool face.

    Every test in this file stands one in now, including the ones whose model
    never calls a tool: the loop opens the session before its first turn, so
    without this they would mint a token and reach for a container. That is not
    an inconvenience to work around — it is R4's point arriving in the tests.
    """
    from contextlib import asynccontextmanager

    class _Session:
        def __init__(self):
            self.tools = tools or []
            self.calls: list[tuple[str, dict]] = []

        async def call(self, name, args):
            self.calls.append((name, args))
            return (by_name or {}).get(name, result)

    session = _Session()

    @asynccontextmanager
    async def _fake(*_a, **_k):
        yield session

    monkeypatch.setattr(meta_agent, "tool_session", _fake)
    return session


def _stub_llm(monkeypatch, chat):
    """Stand in for the turn's provider session.

    The same substitution as _stub_tools and for the same reason — these tests
    are about what the loop does with an answer, not about getting one. The seam
    moved here at V4-S2: the loop used to call chat_with_tools and drop the
    usage, and now calls a session that returns (content, tool_calls) and writes
    the cost row itself. Stubbing that session is what keeps these tests about
    the gate; the row it would have written is asserted in test_llm_cost_trace.
    """
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    @asynccontextmanager
    async def _fake(*_a, **_k):
        yield SimpleNamespace(chat=chat)

    monkeypatch.setattr(meta_agent, "llm_session", _fake)


@pytest.mark.asyncio
async def test_a_model_that_stops_calling_tools_does_not_get_its_text_published(monkeypatch):
    """The path that mattered most: on the final turn the loop used to assign the
    raw model content as the answer. It reached the user with citations=[],
    rendered identically to a verified reply, having passed no gate at all."""
    async def _no_tools(**_kw):
        return ("NVDA revenue was $999.9B and margins are expanding.", None)

    _stub_llm(monkeypatch, _no_tools)
    _stub_tools(monkeypatch, {"noted": True})
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
        return ("", [{"id": "c1", "function": {"name": "think", "arguments": '{"thought":"hm"}'}}])

    _stub_llm(monkeypatch, _always_thinks)
    _stub_tools(monkeypatch, {"noted": True})
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
        return ("whatever", None)

    _stub_llm(monkeypatch, _no_tools)
    _stub_tools(monkeypatch, {"noted": True})
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
                                               "arguments": '{"text":"Hello.","citations":[]}'}}])

    _stub_llm(monkeypatch, _responds)
    _stub_tools(monkeypatch, {"responded": True, "text": "Hello.", "citations": []})
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
        return ("whatever", None)

    _stub_llm(monkeypatch, _no_tools)
    # The real face, because the count is the thing under test and an empty tool
    # list would pass the assertion below for the wrong reason — by being small
    # enough to fail it. This is the list the mount serves for FACE_META_AGENT.
    _stub_tools(monkeypatch, {"noted": True},
                tools=build_meta_registry().schemas(faces.FACE_META_AGENT))
    store: list = []
    out = await handle_message(_factory(store), "sess_5", "hello?", max_turns=1)

    assert out["meta"]["prompt_tokens"] > 1000, "tool schemas must be in the count"
    assistant = [m for m in store if getattr(m, "role", None) == "assistant"]
    assert assistant[0].meta["prompt_tokens"] == out["meta"]["prompt_tokens"]


@pytest.mark.asyncio
async def test_the_refusal_does_not_claim_a_cause_it_did_not_see(monkeypatch):
    """V7-Q2. The sentence asserted WHY: "every attempt either cited evidence I
    had not actually retrieved or stated a figure I could not trace back to a
    source." On the path this test drives, there was no attempt at all — the
    model never reached the gate — so the user was told, confidently, about a
    citation failure that never happened.

    That is not a wording nit. It is what a reader takes away from a system whose
    entire claim is that it does not state things it cannot support: the one
    sentence it emits when it fails was the one sentence nothing checked. It was
    also actively misleading in the incident that prompted this — the gate had
    refused for an exhausted tool budget, and the user went looking at citations.

    The refusal still converges on ONE wording, which is the property the rest of
    this module pins. What changed is that the wording now describes the BAR
    rather than diagnosing the miss, so it is true however the turn ended."""
    async def _no_tools(**_kw):
        return ("NVDA revenue was $999.9B.", None)

    _stub_llm(monkeypatch, _no_tools)
    _stub_tools(monkeypatch, {"noted": True})
    out = await handle_message(_factory([]), "sess_cause", "how did NVDA do?", max_turns=1)

    assert out["meta"]["gate"] == "exhausted"
    assert "cited evidence I had not actually retrieved" not in out["text"]
    assert "stated a figure I could not trace" not in out["text"]
    # And it still says the two things a person needs: it did not get there, and
    # what to do next.
    assert "narrow the question" in out["text"]


@pytest.mark.asyncio
async def test_what_the_gate_actually_refused_is_recorded_for_the_desk(monkeypatch):
    """The cause leaves the sentence and lands in meta, where it is machine
    readable and cannot mislead anybody.

    Diagnosing the incident meant reconstructing the turn from agent_steps by
    hand, because the persisted message said only `gate: exhausted` — the marker
    recorded THAT the gate never opened and never what it said. These codes are
    exactly what would have answered it in one query."""
    async def _always_responds(**_kw):
        return ("", [{"id": "c1", "function": {"name": "respond",
                                               "arguments": '{"text":"x","citations":[]}'}}])

    _stub_llm(monkeypatch, _always_responds)
    _stub_tools(monkeypatch, {"error": "unverified_numbers", "problems": [{"value": "999.9"}]})
    out = await handle_message(_factory([]), "sess_codes", "how did NVDA do?", max_turns=3)

    assert out["meta"]["gate"] == "exhausted"
    assert out["meta"]["gate_refusals"] == ["unverified_numbers"] * 3


@pytest.mark.asyncio
async def test_a_turn_that_never_reached_the_gate_records_no_refusals(monkeypatch):
    """Empty, not absent: "the gate said nothing" and "nobody recorded what the
    gate said" must not look the same to whoever reads this next."""
    async def _always_thinks(**_kw):
        return ("", [{"id": "c1", "function": {"name": "think", "arguments": '{"thought":"hm"}'}}])

    _stub_llm(monkeypatch, _always_thinks)
    _stub_tools(monkeypatch, {"noted": True})
    out = await handle_message(_factory([]), "sess_norefuse", "how did NVDA do?", max_turns=2)

    assert out["meta"]["gate_refusals"] == []


# ── a spent budget narrows the face (2026-08-29) ────────────────────────────────

def _face(*names):
    return [{"type": "function",
             "function": {"name": n, "description": "", "parameters": {}}} for n in names]


@pytest.mark.asyncio
async def test_a_spent_budget_narrows_the_face_to_its_exits(monkeypatch):
    """The wrapper refuses a call over budget with a structured return, and the
    loop used to hand that to the model and go round again: sess_1c71b5fb7f79
    made 65 refused calls after its fifteenth, each a ~12k-token round trip on
    a state where no evidence could arrive. The budget bounds EVIDENCE, so once
    it is spent the only tools that can still do anything are the pause and the
    exit — and the loop now offers exactly those, which is the skip-flag rule
    (remove the capability, do not refuse it inside) applied to the rest of a
    turn. The model can still answer with what it gathered."""
    offered: list[list[str]] = []

    async def _chat(messages, tools, **_kw):
        offered.append([t["function"]["name"] for t in tools])
        if len(offered) == 1:
            return ("", [{"id": "c1", "function": {
                "name": "get_flow", "arguments": '{"ticker":"NVDA","metric":"revenue"}'}}])
        return ("", [{"id": "c2", "function": {
            "name": "respond", "arguments": '{"text":"Here is what I have.","citations":[]}'}}])

    _stub_llm(monkeypatch, _chat)
    _stub_tools(
        monkeypatch, {"noted": True}, tools=_face("get_flow", "think", "respond"),
        by_name={"get_flow": {"error": "budget_exceeded", "kind": "turn_tool",
                              "used": 15, "limit": 15},
                 "respond": {"responded": True, "text": "Here is what I have.",
                             "citations": []}})
    out = await handle_message(_factory([]), "sess_5", "everything about NVDA", max_turns=4)

    assert offered[0] == ["get_flow", "think", "respond"]
    assert offered[1] == ["think", "respond"]
    assert out["text"] == "Here is what I have."
    assert "gate" not in out["meta"]


@pytest.mark.asyncio
async def test_only_an_evidence_pool_running_dry_narrows_the_face(monkeypatch):
    """The narrowing keys on WHICH pool is empty. A refusal of any other kind —
    here the external-search pool, which this face does not even carry — leaves
    the face as it was: nothing about evidence has been settled by it."""
    offered: list[list[str]] = []

    async def _chat(messages, tools, **_kw):
        offered.append([t["function"]["name"] for t in tools])
        if len(offered) == 1:
            return ("", [{"id": "c1", "function": {"name": "get_flow", "arguments": "{}"}}])
        return ("", [{"id": "c2", "function": {
            "name": "respond", "arguments": '{"text":"Hi.","citations":[]}'}}])

    _stub_llm(monkeypatch, _chat)
    _stub_tools(
        monkeypatch, {"noted": True}, tools=_face("get_flow", "think", "respond"),
        by_name={"get_flow": {"error": "budget_exceeded", "kind": "external_search",
                              "used": 5, "limit": 5},
                 "respond": {"responded": True, "text": "Hi.", "citations": []}})
    await handle_message(_factory([]), "sess_6", "hi", max_turns=4)

    assert offered[1] == ["get_flow", "think", "respond"]


def test_the_budget_free_names_mirror_the_registry_budget_free_classes():
    """Two spellings of one decision. The registry says which CLASSES cost no
    budget; the loop, which cannot see classes from its side of the mount,
    says which NAMES it keeps. If either side changes, this is where it shows."""
    from exposure_workbench.tools.registry import BUDGET_FREE_CLASSES

    reg = build_meta_registry()
    by_class = {n for n in faces.FACE_META_AGENT
                if reg.tools[n].tool_class in BUDGET_FREE_CLASSES}
    assert by_class == set(meta_agent._BUDGET_FREE_TOOLS)
