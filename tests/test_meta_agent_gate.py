"""V36 — the lead analyst's loop has no ungated exit (offline: no DB, no network, no LLM).

The exit is plain text, and the text goes through the answer check
(services/answer_check) against the session ledger. Two things have held since
V3-A0-2 and are pinned here: nothing reaches the user that the check did not
accept, and every path to a turn with no accepted answer converges on ONE
wording, marked in meta so the UI can render it as a refusal.

V36: the lead's one working tool is `delegate`, and what it delegates to is a
domain analyst that runs in this same turn. Both loops read from the same fake
provider here, in the order they actually run — lead, then analyst, then lead —
because they share a session by construction (D3) and a harness that pretended
otherwise would be testing a shape the code does not have.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import delegation, meta_agent, sub_analyst
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
    """Stand in for the turn's tool session — a domain analyst's door to the face.
    Records every call and every result it handed back, so a test can build the
    ledger the check reads from exactly what the analysts fetched."""
    from contextlib import asynccontextmanager

    class _Session:
        def __init__(self):
            self.tools = tools if tools is not None else [
                {"type": "function", "function": {"name": n, "description": n, "parameters": {}}}
                for n in sub_analyst.EVIDENCE_TOOLS]
            self.calls: list[tuple[str, dict]] = []
            self.returned: list[dict] = []
            self.actors: list[str | None] = []

        async def call(self, name, args, *, actor=None):
            self.calls.append((name, args))
            self.actors.append(actor)
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

    session = SimpleNamespace(chat=chat)
    # `for_actor` is how a domain analyst spends under its own name; here both
    # loops read the one script, which is what the turn does.
    session.for_actor = lambda _actor: session

    @asynccontextmanager
    async def _fake(*_a, **_k):
        yield session

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
    async def _sub_ledger(_ctx):
        return await _ledger(None, None)

    monkeypatch.setattr(meta_agent, "_record_answer", _no_record)
    monkeypatch.setattr(meta_agent, "_record_delegate", _no_record)
    monkeypatch.setattr(meta_agent, "_record_bad_delegate", _no_record)
    monkeypatch.setattr(meta_agent, "_record_read_report", _no_record)
    monkeypatch.setattr(sub_analyst, "_record", _no_record)
    monkeypatch.setattr(sub_analyst, "_ledger", _sub_ledger)


def _delegate(*tasks):
    """What the lead writes: a domain, subjects, and lines in its own words."""
    full = [{"domain": "book_composition", "subjects": ["port_001"],
             "want_to_know": ["how big MSFT is in the book"], **t} for t in (tasks or [{}])]
    return [{"id": "c1", "function": {"name": delegation.DELEGATE_TOOL_NAME,
                                      "arguments": json.dumps({"tasks": full})}}]


def _submit(*findings, report="ok"):
    """What a domain analyst files."""
    return [{"id": "s1", "function": {"name": delegation.SUBMIT_TOOL_NAME, "arguments": json.dumps(
        {"brief": {"findings": [{"want": i, "facts": f[0], "finding": f[1]} for i, f in enumerate(findings, 1)]},
         "report": {"title": "t", "text": report}})}}]


def _run(program=None):
    return [{"id": "r0", "function": {"name": "run", "arguments": json.dumps({"program": program or {"let": []}})}}]


def _is_lead(tools) -> bool:
    """Which loop is asking. They share the provider because they share the
    turn; `delegate` is on exactly one of the two faces."""
    return delegation.DELEGATE_TOOL_NAME in [t["function"]["name"] for t in tools]


def _two_loops(lead_replies, sub_replies):
    """One script per loop, read in the order the turn runs them."""
    lead, sub = [], []

    async def _chat(messages, tools, **_kw):
        if _is_lead(tools):
            lead.append(list(messages))
            return lead_replies[min(len(lead), len(lead_replies)) - 1]
        sub.append(list(messages))
        return sub_replies[min(len(sub), len(sub_replies)) - 1]

    return _chat, lead, sub


def _repair(*replacements):
    return [{"id": "r1", "function": {"name": meta_agent.REPAIR_TOOL_NAME,
                                      "arguments": json.dumps({"replacements": list(replacements)})}}]


def _run_result(*rows, nodes=None):
    """A `run` result as the face returns it: the note and the facts block."""
    return {"program_id": "calc_p", "returns": [], "settled": len(rows), "refused": [],
            "nodes": nodes or {r[8].get("node", "n"): {"kind": "scalar", "fact": r[0]} for r in rows},
            "facts": {"columns": list(F.COLUMNS), "rows": [list(r) for r in rows]}}


_W_MSFT = ("f_wmsft0001", "scalar", "MSFT", "issuer_exposures.weight", "RATIO", 0.16, "2026-09-10", None, {"node": "w"}, ["run_x"])


# ── nothing reaches the user that the check did not accept ───────────────────

@pytest.mark.asyncio
async def test_an_invented_number_is_refused_and_the_turn_ends_on_the_bar(monkeypatch):
    """The path that mattered most in V3: raw model text reaching the user with
    citations=[]. It still cannot: text is the exit, and the exit is checked.
    V35: after the refusal the turn is a tool call by construction; a provider
    that keeps writing prose is told so once, and the turn ends on the bar."""
    seen: list[dict] = []

    async def _no_tools(**kw):
        seen.append({"tools": [t["function"]["name"] for t in kw["tools"]], "tool_choice": kw.get("tool_choice")})
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
    assert out["meta"]["gate_refusals"] == ["unsourced_figure", "malformed_repair"]
    assert seen[0] == {"tools": [delegation.DELEGATE_TOOL_NAME], "tool_choice": None}
    assert seen[1] == {"tools": [delegation.DELEGATE_TOOL_NAME, meta_agent.REPAIR_TOOL_NAME], "tool_choice": "required"}
    assert len(seen) == 3, "one nudge, then the bar"


@pytest.mark.asyncio
async def test_a_loop_that_never_writes_an_answer_says_so_in_the_same_words(monkeypatch):
    async def _always_delegates(**_kw):
        return ("", _delegate({"domain": "issuer_profitability", "subjects": ["NVDA"],
                               "want_to_know": ["how revenue did over 12 months"]}))

    _stub_llm(monkeypatch, _always_delegates)
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


# ── the lead asks, an analyst fetches, the check reads what was fetched ──────

_FINDING = (["f_wmsft0001"], "MSFT weighs 16.0% [f_wmsft0001] of the book.")


@pytest.mark.asyncio
async def test_a_delegation_is_answered_and_the_figure_it_returned_can_be_stated(monkeypatch):
    chat, lead, sub = _two_loops(
        lead_replies=[("", _delegate()), ("MSFT is 16.0% [f_wmsft0001] of the book.", None)],
        sub_replies=[("", _run()), ("", _submit(_FINDING, report="MSFT weighs 16.0% [f_wmsft0001]."))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_6", "how big is MSFT in the book?", max_turns=4)

    assert [n for n, _ in session.calls] == ["run"]                 # the analyst ran one program
    shown = json.loads([m for m in sub[1] if m.get("role") == "tool"][0]["content"])
    assert shown["figures"][0]["value"] == "16.0% [f_wmsft0001]"    # as the analyst copies it
    handed = json.loads([m for m in lead[1] if m.get("role") == "tool"][0]["content"])
    assert handed["analysts"][0]["coverage"] == {"asked": 1, "done": 1, "not_done": 0, "refused": 0}
    assert handed["analysts"][0]["findings"][0]["asked"] == "how big MSFT is in the book"
    assert out["text"] == "MSFT is 16.0% of the book."              # as the reader sees it
    assert out["citations"] == ["f_wmsft0001"]
    assert out["meta"]["format"] == "blocks" and out["meta"]["verified"]["figures"] == 1
    assert "gate" not in out["meta"]
    assert out["meta"]["delegations"][0]["status"] == "verified"


@pytest.mark.asyncio
async def test_the_lead_never_sees_a_figure_that_did_not_pass_the_handoff(monkeypatch):
    """The boundary earns its place here: a finding whose figure points at the
    wrong fact would cost the LEAD its turn, two loops away from where it was
    written."""
    chat, lead, sub = _two_loops(
        lead_replies=[("", _delegate()), ("The desk could not settle it.", None)],
        sub_replies=[("", _run()),
                     ("", _submit((["f_wmsft0001"], "MSFT is 1.0% [f_wmsft0001] above its tier."),
                                  report="MSFT weighs 16.0% [f_wmsft0001].")),
                     ("", _submit((["f_wmsft0001"], "MSFT is 1.0% [f_wmsft0001] above its tier."),
                                  report="MSFT weighs 16.0% [f_wmsft0001]."))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_handoff", "how big is MSFT?", max_turns=4)

    handed = json.loads([m for m in lead[1] if m.get("role") == "tool"][0]["content"])
    assert handed["analysts"][0]["findings"] == []
    assert handed["analysts"][0]["refused"][0]["reason"] == "mark_mismatch"
    assert out["text"] == "The desk could not settle it."
    assert out["meta"]["delegations"][0]["status"] == "refused"


@pytest.mark.asyncio
async def test_a_delegation_the_roster_cannot_take_is_told_to_the_lead(monkeypatch):
    chat, lead, _sub = _two_loops(
        lead_replies=[("", _delegate({"domain": "no_such_desk"})), ("Hello.", None)],
        sub_replies=[("", None)])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_bad", "hi", max_turns=4)

    told = json.loads([m for m in lead[1] if m.get("role") == "tool"][0]["content"])
    assert told["error"] == "invalid_delegation" and "ROSTER" in told["detail"]
    assert session.calls == []
    assert out["text"] == "Hello."


@pytest.mark.asyncio
async def test_a_refused_reply_is_told_every_problem_and_the_second_attempt_can_pass(monkeypatch):
    chat, lead, _sub = _two_loops(
        lead_replies=[("", _delegate()),
                      ("MSFT is 16.0% of the book, up from 12.5% last year, the largest holding.", None),
                      ("", _repair({"tag": "S1", "text": "MSFT is 16.0% [f_wmsft0001] of the book."}))],
        sub_replies=[("", _run()), ("", _submit(_FINDING, report="MSFT weighs 16.0% [f_wmsft0001]."))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_7", "how big is MSFT?", max_turns=6)

    told = [m for m in lead[2] if m.get("role") == "user"][-1]["content"]
    assert "unsourced_figure" in told and "12.5%" in told
    assert "unpointed_figure" in told and "f_wmsft0001" in told, "a bare figure the desk showed comes back with its id"
    # the relation checks read pointed figures: a superlative over a bare one is
    # judged once the figure points (nothing here infers which fact "16.0%" meant)
    assert "superlative_without_rank" not in told
    assert "repair_answer" in told
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

    assert meta_agent._BUDGET_FREE_TOOLS == (delegation.DELEGATE_TOOL_NAME,
                                             delegation.READ_REPORT_TOOL_NAME,
                                             meta_agent.REPAIR_TOOL_NAME)
    for name in meta_agent._BUDGET_FREE_TOOLS:
        assert name not in build_meta_registry().tools
        assert name not in faces.FACE_META_AGENT


@pytest.mark.asyncio
async def test_a_refused_reply_is_repaired_sentence_by_sentence_through_the_tool(monkeypatch):
    """V34 invariant C: the second attempt replaces only the sentences that did not
    pass; every accepted sentence is kept exactly as written, so the accepted set
    can only grow. V35: the replacements come through repair_answer — round G
    showed a text protocol is not one (1 of 18 second attempts used it, 4 re-sent
    the refused text byte for byte)."""
    told: list = []
    lead_replies = iter([
        ("", _delegate()),
        ("MSFT weighs 23.4% of the book. The book leans on its largest names.", None),
        ("", _repair({"tag": "S1", "text": "MSFT weighs 16.0% [f_wmsft0001] of the book."})),
    ])
    sub_replies = iter([("", _run()), ("", _submit(_FINDING, report="MSFT weighs 16.0% [f_wmsft0001]."))])

    async def _llm(**kw):
        if not _is_lead(kw["tools"]):
            return next(sub_replies)
        told.append({**kw, "messages": list(kw["messages"])})
        return next(lead_replies)

    _stub_llm(monkeypatch, _llm)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT))
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_repair", "how big is MSFT", max_turns=8)

    assert out["text"] == "MSFT weighs 16.0% of the book. The book leans on its largest names."
    assert "gate" not in out["meta"]
    assert told[2]["tool_choice"] == "required"
    refusal = [m for m in told[2]["messages"] if m.get("role") == "user"][-1]["content"]
    assert "[S1] MSFT weighs 23.4% of the book." in refusal and "[S2]" not in refusal
    assert out["meta"]["verified"]["sentences"] == {"checked": 1, "unchecked": 1,
                                                   "judgement": ["The book leans on its largest names."]}


@pytest.mark.asyncio
async def test_a_whole_new_reply_while_a_verdict_stands_is_not_read(monkeypatch):
    """Even a correct one: the repair is the tool. A provider that ignores
    tool_choice is told so once; the next prose reply ends the turn."""
    told: list = []
    replies = iter([
        ("MSFT weighs 23.4% of the book.", None),
        ("MSFT weighs 16.0% [f_wmsft0001] of the book.", None),          # a rewrite, not a repair
        ("", _repair({"tag": "S1", "text": "MSFT weighs 16.0% [f_wmsft0001] of the book."})),
    ])

    async def _llm(**kw):
        told.append({**kw, "messages": list(kw["messages"])})      # a snapshot: the loop appends to the live list
        return next(replies)


    _stub_llm(monkeypatch, _llm)
    session = _stub_tools(monkeypatch, _run_result(_W_MSFT), by_name={"run": _run_result(_W_MSFT)})
    _stub_desk(monkeypatch, session)
    session.returned.append(_run_result(_W_MSFT))          # the ledger holds the weight this turn
    out = await handle_message(_factory([]), "sess_nudge", "how big is MSFT", max_turns=8)

    assert told[2]["messages"][-1] == {"role": "user", "content": meta_agent._REPAIR_ONLY}
    assert out["text"] == "MSFT weighs 16.0% of the book."
    assert "gate" not in out["meta"]


@pytest.mark.asyncio
async def test_a_repair_that_still_fails_spends_the_second_attempt(monkeypatch):
    replies = iter([
        ("MSFT weighs 23.4% of the book.", None),
        ("", _repair({"tag": "S1", "text": "MSFT weighs 24.4% of the book."})),
    ])

    async def _llm(**kw):
        return next(replies)

    _stub_llm(monkeypatch, _llm)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    out = await handle_message(_factory([]), "sess_twice", "how big is MSFT", max_turns=8)
    assert out["text"] == _GATE_EXHAUSTED_TEXT
    assert out["meta"]["gate_refusals"] == ["unsourced_figure", "unsourced_figure"]


# ── V36.1 (round A) · the two edges the table had to infer are recorded ──────

@pytest.mark.asyncio
async def test_a_rejected_delegation_and_a_read_report_are_steps(monkeypatch):
    """Round A's table showed eight lead completions with one tool call and
    nothing after: three delegations the protocol refused, five read_reports.
    Both are steps now, so the next table needs no inference."""
    recorded: list = []

    async def _bad(_f, _s, _m, args, detail):
        recorded.append(("delegate", "rejected", detail))

    async def _read(_f, _s, _m, report_id, result):
        recorded.append(("read_report", result.get("status") or result.get("error"), report_id))

    chat, lead, _sub = _two_loops(
        lead_replies=[("", _delegate({"domain": "no_such_desk"})),
                      ("", _delegate()),
                      ("", [{"id": "rr", "function": {"name": delegation.READ_REPORT_TOOL_NAME,
                                                      "arguments": json.dumps({"report_id": "rep_missing"})}}]),
                      ("Hello.", None)],
        sub_replies=[("", _submit((["f_wmsft0001"], "MSFT is 16.0% [f_wmsft0001] of the book.")))])
    _stub_llm(monkeypatch, chat)
    session = _stub_tools(monkeypatch, {"noted": True})
    _stub_desk(monkeypatch, session)
    monkeypatch.setattr(meta_agent, "_record_bad_delegate", _bad)
    monkeypatch.setattr(meta_agent, "_record_read_report", _read)
    out = await handle_message(_factory([]), "sess_rec", "hi", max_turns=6)

    assert out["text"] == "Hello."
    assert recorded[0][:2] == ("delegate", "rejected") and "ROSTER" in recorded[0][2]
    assert recorded[-1][0] == "read_report" and recorded[-1][2] == "rep_missing"
    # what the lead read between completions is measured on the way in
    assert all("note" not in m for m in lead[1])         # the note is the row's, not the prompt's
