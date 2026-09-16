"""V36 Phase 1 acceptance — Q11, the question three rounds never answered.

    "Which position is closest to its issuer-concentration warning, how much
     room is left, and what percentage move in that name alone would take it to
     the breach tier with everything else fixed? If we capped any single issuer
     at 8%, who would be over?"

Round I wrote the subtraction itself, in the desk's derive syntax, and the room
it produced was capped out of what it was shown. Round J did not write it: the
intent sat in an `ask` field the compiler did not read, and the analyst
subtracted in prose and was refused for it, twice. Neither round had anybody
whose job was turning that line into the desk's language.

This is that turn with the job assigned, end to end and offline: the lead
delegates four numbered lines, a domain analyst compiles them, adds the two
nodes the request syntax cannot say, runs one program, files a brief, and the
lead writes an answer the gate accepts. Every figure in the answer is one the
analyst was shown, and nothing in it was worked out in anybody's head.
"""

from __future__ import annotations

import json

import pytest

from exposure_workbench.agents import delegation, meta_agent, sub_analyst
from exposure_workbench.agents.meta_agent import handle_message
from exposure_workbench.services import facts as F
from exposure_workbench.services.digest import display
from exposure_workbench.services.ledger import Ledger

Q11 = ("Which position is closest to its issuer-concentration warning, how much room is left, and what percentage "
       "move in that name alone would take it to the breach tier with everything else fixed? If we capped any "
       "single issuer at 8%, who would be over?")

_WEIGHTS = {"MSFT": 0.16039003, "AAPL": 0.15208, "JPM": 0.14806, "LLY": 0.12481, "GOOGL": 0.12409}


def _rows() -> list[F.Fact]:
    """What one program produces: the three tiers of every issuer-concentration
    check, the two rooms derived from them, the move to breach, and the weights
    over the cap the question named.

    Every entry of a node carries the place that node's ordering gave it, set
    here the way `program_service._facts_of` sets it — sorted by value,
    descending — because that is what a superlative in the answer is checked
    against, and a fixture that numbered them any other way would be testing a
    check nobody has."""
    checks = {"MSFT": (0.16039003, 0.15, 0.20), "NVDA": (0.0406405, 0.15, 0.20), "XOM": (0.04612816, 0.15, 0.20)}
    nodes: dict[str, dict[str, tuple[str, float]]] = {
        "current": {tk: (f"issuer_concentration:{tk}", cur) for tk, (cur, _w, _b) in checks.items()},
        "warning": {tk: (f"issuer_concentration:{tk}", w) for tk, (_c, w, _b) in checks.items()},
        "breach": {tk: (f"issuer_concentration:{tk}", b) for tk, (_c, _w, b) in checks.items()},
        "room_to_warning": {tk: (f"issuer_concentration:{tk}", w - cur) for tk, (cur, w, _b) in checks.items()},
        "room_to_breach": {tk: (f"issuer_concentration:{tk}", b - cur) for tk, (cur, _w, b) in checks.items()},
        "over_8pct": {tk: (tk, w) for tk, w in _WEIGHTS.items()},
    }
    measure = {"current": "limit_checks.current_value", "warning": "limit_checks.warning_level",
               "breach": "limit_checks.breach_level", "room_to_warning": "room_to_warning",
               "room_to_breach": "room_to_breach", "over_8pct": "issuer_exposures.weight"}
    op = {"room_to_warning": "sub", "room_to_breach": "sub"}
    out: list[F.Fact] = []
    for node, entries in nodes.items():
        places = {lab: i for i, (lab, _v) in
                  enumerate(sorted(entries.items(), key=lambda kv: -kv[1][1]), start=1)}
        for lab, (subject, value) in entries.items():
            out.append(F.fact(F.SCALAR, measure[node], subject=subject, unit="RATIO", value=value,
                              as_of="2026-09-10",
                              params={"node": node, "label": subject, "place": places[lab], "of": len(entries),
                                      **({"op": op[node]} if node in op else {})}))
    out.append(F.fact(F.SCALAR, "move_to_breach", subject="issuer_concentration:MSFT", unit="RATIO",
                      value=(0.20 - 0.16039003) / 0.16039003, as_of="2026-09-10",
                      params={"node": "move_to_breach", "label": "issuer_concentration:MSFT", "op": "div"}))
    return out


def _run_result(facts: list[F.Fact]) -> dict:
    return {"program_id": "calc_q11", "returns": ["room_to_warning", "room_to_breach", "move_to_breach", "over_8pct"],
            "nodes": {n: {"kind": "vector"} for n in
                      ("current", "warning", "breach", "room_to_warning", "room_to_breach", "move_to_breach", "over_8pct")},
            "settled": len(facts), "refused": [],
            "facts": {"columns": list(F.COLUMNS),
                      "rows": [[f.id, f.kind, f.subject, f.measure, f.unit, f.value, f.as_of, None, f.params, []]
                               for f in facts]}}


def _shown(tool_message: str) -> dict:
    """What the analyst reads: {(measure, subject): "16.0% [f_…]"}."""
    d = json.loads(tool_message)
    return {(f["measure"], f["subject"]): f["value"] for f in d["figures"]}


# ── the turn ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_q11_end_to_end(monkeypatch):
    facts = _rows()
    ledger = Ledger.of_facts(facts)
    steps: list[dict] = []
    lead: list[list[dict]] = []
    sub: list[list[dict]] = []
    compiled: list[dict] = []
    tool_calls: list[tuple[str, dict]] = []

    class _Tools:
        tools = [{"type": "function", "function": {"name": n, "description": n, "parameters": {}}}
                 for n in sub_analyst.EVIDENCE_TOOLS]

        async def call(self, name, args, *, actor=None):
            tool_calls.append((name, args, actor))
            return _run_result(facts)

    def _lead_reply(n: int, messages: list[dict]):
        if n == 1:
            task = {"domain": "book_limits_and_triggers", "subjects": ["port_001"],
                    "want_to_know": [
                        "which position's issuer-concentration check is nearest its warning tier",
                        "how much room it has left to warning and to breach",
                        "what single-name percentage move would take it to breach with everything else fixed",
                        "which issuers would be over an 8% single-issuer cap"],
                    "facts_to_derive": ["room = the tier minus the current reading",
                                        "move to breach = room to breach over the name's weight"],
                    "constraints": {"window": "latest", "compare": "nearest first"}}
            return ("", [{"id": "d1", "function": {"name": delegation.DELEGATE_TOOL_NAME,
                                                   "arguments": json.dumps({"tasks": [task]})}}])
        # the lead writes from the findings it was handed, copying each figure
        handed = json.loads([m for m in messages if m.get("role") == "tool"][-1]["content"])
        by_want = {f["want"]: f["finding"] for f in handed["analysts"][0]["findings"]}
        return (" ".join(by_want[i] for i in sorted(by_want)), None)

    def _sub_reply(n: int, messages: list[dict]):
        if n == 1:
            request = {
                "subjects": ["port_001"],
                "want": ["limit_checks.current_value", "limit_checks.warning_level", "limit_checks.breach_level",
                         "issuer_exposures.weight"],
                "window": "latest", "compare": "rank lowest",
                "derive": ["room_to_warning = limit_checks.warning_level - limit_checks.current_value",
                           "room_to_breach = limit_checks.breach_level - limit_checks.current_value"]}
            return ("", [{"id": "c1", "function": {"name": "compile",
                                                   "arguments": json.dumps({"request": request})}}])
        if n == 2:
            # the two nodes the request syntax cannot say, added to the program
            # the compiler produced: the move to breach, and the cap the
            # question named as a filter over the weights
            program = compiled[0]["program"]
            program["let"] += [
                {"name": "move_to_breach", "expr": {"fn": "div", "a": "$room_to_breach", "b": "$current"}},
                {"name": "over_8pct", "expr": {"fn": "filter", "of": "$issuer_exposures_weight", "op": ">", "level": 0.08}}]
            return ("", [{"id": "r1", "function": {"name": "run", "arguments": json.dumps({"program": program})}}])
        last = [m for m in messages if m.get("role") == "tool"][-1]["content"]
        if "refusal" in last:                       # the boundary refused; say why, do not paper over it
            raise AssertionError(json.loads(last)["refusal"])
        shown = _shown(last)
        msft = "issuer_concentration:MSFT"
        over = ", ".join(f"{tk} at {shown[('issuer_exposures.weight', tk)]}" for tk in _WEIGHTS)
        findings = [
            {"want": 1, "facts": [], "finding":
             f"MSFT is nearest: its issuer-concentration check reads {shown[('limit_checks.current_value', msft)]} "
             f"against a warning tier of {shown[('limit_checks.warning_level', msft)]}, and its room to warning of "
             f"{shown[('room_to_warning', msft)]} is the smallest of the three checks — it is already past warning."},
            {"want": 2, "facts": [], "finding":
             f"Room to warning is {shown[('room_to_warning', msft)]}. Room to breach is "
             f"{shown[('room_to_breach', msft)]}, against a breach tier of "
             f"{shown[('limit_checks.breach_level', msft)]}."},
            {"want": 3, "facts": [], "finding":
             f"A rise of {shown[('move_to_breach', msft)]} in MSFT alone reaches breach, with everything else fixed."},
            {"want": 4, "facts": [], "finding": f"Over an 8% cap: {over}."},
        ]
        payload = {"brief": {"findings": findings, "not_done": [],
                             "caveats": ["room is in weight points, not dollars"]},
                   "report": {"title": "Issuer-concentration room, port_001",
                              "text": findings[0]["finding"] + " " + findings[1]["finding"]}}
        return ("", [{"id": "s1", "function": {"name": delegation.SUBMIT_TOOL_NAME,
                                               "arguments": json.dumps(payload)}}])

    async def _chat(messages, tools, **_kw):
        if delegation.DELEGATE_TOOL_NAME in [t["function"]["name"] for t in tools]:
            lead.append(list(messages))
            return _lead_reply(len(lead), messages)
        sub.append(list(messages))
        return _sub_reply(len(sub), messages)

    # — the harness: no database, no provider, no face —
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    llm = SimpleNamespace(chat=_chat)
    llm.for_actor = lambda _a: llm

    @asynccontextmanager
    async def _fake_llm(*_a, **_k):
        yield llm

    @asynccontextmanager
    async def _fake_tools(*_a, **_k):
        yield _Tools()

    class _Db:
        def __init__(self, store): self.store = store
        async def execute(self, *_a, **_k): return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        def add(self, obj): self.store.append(obj)
        async def commit(self): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_e): return False

    store: list = []
    real_compile = sub_analyst.pb.compile_request

    def _compile(request, held_in=None):
        out = real_compile(request, held_in=held_in)
        compiled.append(out)
        return out

    async def _record(ctx, actor, step_type, tool_name, args, summary, facts=None, status="completed"):
        steps.append({"actor": actor, "step_type": step_type, "tool": tool_name, "status": status})

    async def _record_delegate(_f, _s, _m, tasks):
        steps.append({"actor": None, "step_type": "delegate", "tool": "delegate", "status": "completed"})

    async def _record_answer(_f, _s, _m, _t, verdict):
        steps.append({"actor": None, "step_type": "answer", "tool": "answer",
                      "status": "completed" if verdict.ok else "rejected"})

    async def _no_briefing(_f, _t):
        return {"subjects": {"tickers": [], "portfolios": ["port_001"], "runs": []},
                "portfolios": {"port_001": {"name": "the book"}}}

    async def _ledger(*_a, **_k):
        return ledger

    monkeypatch.setattr(meta_agent, "llm_session", _fake_llm)
    monkeypatch.setattr(meta_agent, "tool_session", _fake_tools)
    monkeypatch.setattr(meta_agent, "_briefing", _no_briefing)
    monkeypatch.setattr(meta_agent, "_load_ledger", _ledger)
    monkeypatch.setattr(meta_agent, "_record_delegate", _record_delegate)
    monkeypatch.setattr(meta_agent, "_record_answer", _record_answer)
    monkeypatch.setattr(sub_analyst, "_record", _record)
    monkeypatch.setattr(sub_analyst, "_ledger", lambda _ctx: _ledger())
    monkeypatch.setattr(sub_analyst.pb, "compile_request", _compile)

    out = await handle_message(lambda: _Db(store), "sess_q11", Q11, max_turns=6)

    # — the intent was turned into the desk's language, by somebody —
    assert compiled, "the analyst compiled the lead's lines"
    names = [b["name"] for b in compiled[0]["program"]["let"]]
    assert "room_to_warning" in names and "room_to_breach" in names, \
        "the room the lead asked for is a node of the program, not a subtraction in prose"
    assert [n for n, _a, _actor in tool_calls] == ["run"], "one program, once"
    ran = [b["name"] for b in tool_calls[0][1]["program"]["let"]]
    assert "move_to_breach" in ran and "over_8pct" in ran, \
        "the analyst added what the request syntax could not say — that is why it is an analyst"
    # V37/M1: the call says who made it, so the trace does not have to guess
    assert [a for _n, _a, a in tool_calls] == ["sub:book_limits_and_triggers"]

    # — the boundary was crossed with everything accounted for —
    assert out["meta"]["delegations"][0]["coverage"] == {"asked": 4, "done": 4, "not_done": 0, "refused": 0}
    assert out["meta"]["delegations"][0]["status"] == "verified"

    # — and the answer passed —
    assert "gate" not in out["meta"], out["meta"].get("gate_refusals")
    assert out["text"].startswith("MSFT is nearest")
    assert display(0.20 - 0.16039003, "RATIO") in out["text"]            # the room, as the desk computed it
    assert display((0.20 - 0.16039003) / 0.16039003, "RATIO") in out["text"]   # and the move
    assert len(out["citations"]) >= 8
    assert all(c in ledger.by_id for c in out["citations"])

    # — the trace says who did what —
    assert [(s["actor"], s["step_type"]) for s in steps] == [
        (None, "delegate"),
        ("sub:book_limits_and_triggers", "tool_call"),      # compile
        ("sub:book_limits_and_triggers", "brief"),
        (None, "answer"),
    ]
    assert len(lead) == 2 and len(sub) == 3


@pytest.mark.asyncio
async def test_the_lead_is_never_handed_the_desks_vocabulary():
    """What V35 gave the lead — method names, a program syntax, an id — and what
    it wrote back with them is the reason for all of this. The lead's own
    surface must not contain them."""
    from exposure_workbench.analytics import skill

    surface = meta_agent._SYSTEM + json.dumps(skill.roster()) + json.dumps(delegation.DELEGATE_TOOL)
    for name in skill.METHODS:
        if "_" in name or "." in name:
            assert name not in surface, f"the lead is handed {name}"
    assert '"fn"' not in surface and '"let"' not in surface
    assert "never name a measure, a program or a fact id" in meta_agent._SYSTEM.lower()


# ── V37/A2: the lead's reply re-sent unchanged is not a second attempt ─────────

@pytest.mark.asyncio
async def test_a_reply_re_sent_word_for_word_does_not_spend_the_second_attempt(monkeypatch):
    """Round B's Q03 and Q18 each sent their answer twice, word for word, and
    ended on the gate-exhausted text: given the same prose and the same ledger the
    check returns the same refusal, and hearing it again cost one of the two
    attempts. The first repeat is told it repeated itself, with the token the
    check named; the second ends the turn, because a third identical payload has
    never once been the one that passed."""
    from contextlib import asynccontextmanager

    # Once a verdict stands the turn is a tool call by construction, so a repeat
    # reaches the check the way round B's did: through `repair_answer`, with a
    # replacement that reproduces the sentence it replaced. Q18's two answers were
    # byte-identical and its second attempt was spent hearing the same refusal.
    bad = "The desk holds $1.23B of it."          # a figure no ledger accounts for
    same = {"replacements": [{"tag": "S1", "text": bad}]}
    turns = [("text", bad), ("repair", same), ("repair", same), ("text", "")]
    seen: list[list[dict]] = []
    ledger = Ledger.of_facts(_rows())

    class _Llm:
        def for_actor(self, actor):
            return self

        async def chat(self, messages, tools=None, **kw):
            seen.append(list(messages))
            kind, payload = turns.pop(0) if turns else ("text", "")
            if kind == "text":
                return payload, None
            return "", [{"id": "r1", "function": {"name": meta_agent.REPAIR_TOOL_NAME,
                                                  "arguments": json.dumps(payload)}}]

    class _Tools:
        tools: list = []

        async def call(self, name, args, *, actor=None):
            raise AssertionError("the lead fetches nothing here")

    class _Db:
        def add(self, _row):
            pass

        async def execute(self, *_a, **_k):
            class _R:
                @staticmethod
                def scalars():
                    class _S:
                        @staticmethod
                        def all():
                            return []
                    return _S()
            return _R()

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_e):
            return False

    @asynccontextmanager
    async def _fake_llm(*_a, **_k):
        yield _Llm()

    @asynccontextmanager
    async def _fake_tools(*_a, **_k):
        yield _Tools()

    async def _no_briefing(_f, _t):
        return {"subjects": {"tickers": [], "portfolios": [], "runs": []}}

    monkeypatch.setattr(meta_agent, "llm_session", _fake_llm)
    monkeypatch.setattr(meta_agent, "tool_session", _fake_tools)
    monkeypatch.setattr(meta_agent, "_briefing", _no_briefing)
    monkeypatch.setattr(meta_agent, "_load_ledger", lambda *_a, **_k: _await(ledger))
    monkeypatch.setattr(meta_agent, "_record_answer", _noop4)

    out = await meta_agent.handle_message(_Db, "sess_repeat", "how much is held?", max_turns=6)

    assert out["meta"]["gate"] == "exhausted", out["meta"]
    refusals = out["meta"]["gate_refusals"]
    assert refusals == ["unsourced_figure", "repeated_answer"], \
        "one refusal earned, then the turn ended because the reply stopped changing"
    told = json.dumps([m.get("content") for m in seen[-1] if m.get("role") == "tool"])
    assert "byte-identical" in told and "1.23" in told


async def _await(value):
    return value


async def _noop4(*_a, **_k):
    return None
