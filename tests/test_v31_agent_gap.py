"""V31 — the three things the V26 traces said cost the agent its work.

Read off `docs/spikes/v29/V26_R2.json` (140 turns, pinned at `e6c290b`, which is
what production runs) and written up in `docs/AGENT_GAP_2026-09-10.md`:

  1. an exit refused and re-sent UNCHANGED, up to eight times in one turn;
  2. a batch that held three correct calls behind a sibling's bad parameter;
  3. an adapter that discarded every figure in a result over one key it could
     not name;

and the standing hazard behind all three — a refusal that routes the model to a
tool no face carries any more.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from exposure_workbench.agents import batch, repeats as rp
from exposure_workbench.services import fact_adapters as fa

from tests.test_meta_agent_gate import (  # the loop harness, unchanged
    _factory, _stub_llm, _stub_tools,
)
from exposure_workbench.agents.meta_agent import _GATE_EXHAUSTED_TEXT, handle_message


# ── 1. an unchanged resubmission is not a second attempt ─────────────────────

_SAME = json.dumps({"claims": [{"id": "c1", "relation": "level", "of": "f_1"}],
                    "prose": ["ExxonMobil's debt is 92% fixed-rate."]})
_REFUSED = {"error": "unsourced_figure",
            "problems": [{"at": "prose[0]", "reason": "unsourced_figure", "figure": "92%"}],
            "detail": "every number in the prose is a fact's value or date on the ledger"}


def _respond_call(args: str):
    return [{"id": "c1", "function": {"name": "respond", "arguments": args}}]


@pytest.mark.asyncio
async def test_the_same_refused_answer_sent_again_and_again_stops_costing_turns(monkeypatch):
    """W01-xom-maturity-wall t2: eight byte-identical `respond` calls, 17.3k →
    24.7k prompt tokens, ending on the gate-exhausted text. It ends on the same
    text now — nothing is published that the gate did not accept — at three."""
    async def _always_the_same(**_kw):
        return ("", _respond_call(_SAME))

    _stub_llm(monkeypatch, _always_the_same)
    session = _stub_tools(monkeypatch, _REFUSED)
    out = await handle_message(_factory([]), "sess_r1", "is that fixed or floating", max_turns=16)

    sent = [c for c in session.calls if c[0] == "respond"]
    assert len(sent) == 1 + rp.STOP, f"three submissions, not sixteen: {len(sent)}"
    assert out["text"] == _GATE_EXHAUSTED_TEXT, "the gate still decides what is published"
    assert out["meta"]["gate"] == "exhausted"


@pytest.mark.asyncio
async def test_the_first_repeat_is_told_it_is_one_and_which_tokens_the_gate_named(monkeypatch):
    """The model that re-sends has, on the evidence of three turns, not read
    `problems`. So it is handed them again, with the fact that it repeated."""
    seen_messages: list[list[dict]] = []

    async def _always_the_same(**kw):
        seen_messages.append(list(kw["messages"]))
        return ("", _respond_call(_SAME))

    _stub_llm(monkeypatch, _always_the_same)
    _stub_tools(monkeypatch, _REFUSED)
    await handle_message(_factory([]), "sess_r2", "is that fixed or floating", max_turns=16)

    nudges = [m for turn in seen_messages for m in turn
              if m["role"] == "user" and "byte-identical" in (m.get("content") or "")]
    assert nudges, "the repeat is named"
    said = nudges[0]["content"]
    assert "prose[0]" in said and "92%" in said, f"the token, not just the rule: {said}"
    assert "unsourced_figure" in said


@pytest.mark.asyncio
async def test_an_answer_that_changes_is_never_held_however_many_times_it_is_sent(monkeypatch):
    """The bound is on repetition, never on effort. A model working through its
    refusals gets every turn it has."""
    n = {"i": 0}

    async def _different_each_time(**_kw):
        n["i"] += 1
        return ("", _respond_call(json.dumps({"claims": [], "prose": [f"try {n['i']}"]})))

    _stub_llm(monkeypatch, _different_each_time)
    session = _stub_tools(monkeypatch, _REFUSED)
    await handle_message(_factory([]), "sess_r3", "q", max_turns=6)

    assert len([c for c in session.calls if c[0] == "respond"]) == 6


def test_a_payload_reserialised_in_another_key_order_is_the_same_answer():
    r = rp.Repeats()
    assert r.record({"a": 1, "b": [2, 3]}) == 1
    assert r.record({"b": [2, 3], "a": 1}) == 2, "the gate reads values, not key order"
    assert r.record({"b": [3, 2], "a": 1}) == 1, "a different answer is a different answer"


# ── 2. a batch holds the belief that was wrong, and only that ────────────────

def test_an_argument_refusal_does_not_hold_a_sibling_sent_with_other_arguments():
    """L02-days-arent-price t1: price.volatility(window_days=20) was refused
    `invalid_params`, and volatility(252), window_return(3m) and drawdown(1y)
    were held behind it. All three were correct; all three succeeded unchanged
    on the next round trip."""
    refusal = {"error": "invalid_params", "detail": "window_days is one of 21, 63, 252"}
    bad = {"method": "price.volatility", "params": {"window_days": 20}}

    assert batch.holds(refusal, bad, bad) is True, "the identical call is still held"
    for sibling in ({"method": "price.volatility", "params": {"window_days": 252}},
                    {"method": "price.window_return", "params": {"window": "3m"}},
                    {"method": "price.drawdown", "params": {"window": "1y"}}):
        assert batch.holds(refusal, sibling, bad) is False, sibling


def test_a_refusal_about_a_name_still_holds_every_later_call_to_that_tool():
    """V21-S1's class stays closed: ten calls composed under one wrong belief
    about how a tool is called are still not ten round trips."""
    refusal = {"error": "unknown_formula", "detail": "net_income is a filed metric"}
    assert batch.holds(refusal, {"formula": "anything"}, {"formula": "net_income"}) is True


def test_a_refusal_that_names_its_argument_still_holds_only_that_value():
    """V23's held_on is untouched and still wins over the V31 rule."""
    refusal = {"error": "metric_not_filed", "held_on": {"metric": "capex"}}
    assert batch.holds(refusal, {"metric": "capex"}, {"metric": "capex"}) is True
    assert batch.holds(refusal, {"metric": "revenue"}, {"metric": "capex"}) is False


@pytest.mark.asyncio
async def test_the_L02_batch_end_to_end_sends_the_three_calls_it_used_to_hold():
    calls = [{"id": f"c{i}", "function": {"name": "compute", "arguments": json.dumps(a)}}
             for i, a in enumerate((
                 {"method": "price.volatility", "params": {"window_days": 20}},
                 {"method": "price.volatility", "params": {"window_days": 252}},
                 {"method": "price.window_return", "params": {"window": "3m"}},
                 {"method": "price.drawdown", "params": {"window": "1y"}}))]

    class _Session:
        def __init__(self): self.sent = []

        async def call(self, name, args):
            self.sent.append(args)
            if args.get("params", {}).get("window_days") == 20:
                return {"error": "invalid_params", "detail": "window_days is one of 21, 63, 252"}
            return {"quantity": 1.0, "table": {"figures": []}}

    s = _Session()
    out = await batch.dispatch(s, calls, free=())
    assert len(s.sent) == 4, "every call whose belief was its own goes out"
    assert not any(r.get("error") == batch.NOT_ATTEMPTED for _tc, _a, r in out)


# ── 3. one key the adapter cannot name costs the key, not the call ───────────

def test_a_result_with_one_unnameable_key_keeps_every_figure_that_typed():
    """§4.2's class: `compute` raised UnknownUnit on `unmatched_periods` and the
    wrapper returned `fact_adapter_error`, discarding the figures that HAD
    typed. Three of 191 baseline turns, and once in L02 where the model had
    asked for a single honest `abs`."""
    payload = {"method": "issuer.series_ops", "subject": "XOM", "as_of": "2026-09-04",
               "ratio": {"value": 0.42, "unit_class": "RATIO"},
               "unmatched_periods": 3}
    facts, note, _held = fa.adapt("compute", {"method": "issuer.series_ops"}, payload)

    assert [f.value for f in facts] == [0.42], "the declared figure survived"
    assert note["unmatched_periods"] == "untyped:unmatched_periods"
    assert "unmatched_periods" in note["untyped"], "and the model is told why it cannot point at it"
    assert fa.numeric_leaves(note) == [], "I1: still no bare number reaches the model"


def test_quality_flags_is_diagnostics_and_passes_through_as_the_resolver_says():
    """`typed_calculator._is_single_valued` has excluded quality_flags from a
    row's figures since V29. The adapter walking it for figures was the adapter
    doing the producer's job."""
    assert "quality_flags" in fa.PASSTHROUGH_KEYS
    flags = {"unmatched_periods": 3, "note": "two periods did not align"}
    _facts, note, _h = fa.adapt("compute", {"method": "m"},
                                {"method": "m", "subject": "XOM", "as_of": "2026-09-04",
                                 "quality_flags": flags})
    assert note["quality_flags"] == flags, "verbatim, not harvested"


# ── the standing hazard: a refusal that names a tool no face carries ─────────

_RETIRED = ("read_fundamentals(", "read_prices(", "compute(")

# Where `compute` still legitimately spells itself: it is a registered tool with
# a service behind it, and Phase 3 deletes both. What matters is that nothing an
# agent can REACH routes it to a door that is not on its face.
_STILL_COMPUTE_S_OWN = {"compute_service.py", "definitions.py"}


def _model_facing_strings(path: pathlib.Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_no_refusal_on_the_run_path_routes_the_model_to_a_retired_tool():
    """`meta_agent._SYSTEM` says figures come from ONE tool, `run(program)`, and
    since V31 Phase 2 `read_fundamentals`, `read_prices` and `compute` are on
    neither face. A refusal that tells the model to call one of them is advice
    it cannot take — and it is read at exactly the moment the model is stuck."""
    root = pathlib.Path(fa.__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.name in _STILL_COMPUTE_S_OWN or "__pycache__" in str(path):
            continue
        for lineno, text in _model_facing_strings(path):
            for retired in _RETIRED:
                if retired in text:
                    offenders.append(f"{path.relative_to(root)}:{lineno}: …{text[:90]}…")
    assert offenders == [], (
        "these strings route a model to a tool no face carries:\n  " + "\n  ".join(offenders))
