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


# ── A. a refusal that says WHERE the figure lives ────────────────────────────

def _ledger_with(passage: str, pid: str = "chunk_7a3f"):
    """A ledger holding one passage and nothing else — the shape a turn has
    after `read_filings` and before it has filed a single claim."""
    from exposure_workbench.services import ledger as L
    led = L.Ledger()
    led.passages[pid] = passage
    return led


_XOM = ("The Corporation's debt portfolio is predominantly fixed-rate. At year-end, "
        "$22,965 million of long-term debt was outstanding, of which 4.2% carried "
        "floating-rate terms under the commercial paper program.")


def test_a_number_the_session_retrieved_is_routed_to_the_passage_that_states_it():
    """W01-xom-maturity-wall t2's class. `read_filings` put the debt note on the
    table, the model wrote a correct sentence about it, and every digit in that
    sentence was refused eight times — while the passage holding them sat on the
    same ledger, one quote claim away. The rule does not move; what the model is
    told does."""
    from exposure_workbench.services import claims

    led = _ledger_with(_XOM)
    v = claims.check({"claims": [], "prose": ["The debt is mostly fixed: only 4.2% floats."]},
                     led, question="is that fixed or floating")

    assert v.ok is False, "the figure is still not accounted for — acceptance is unchanged"
    assert v.error == "unsourced_figure"
    problem = next(p for p in v.problems if p["reason"] == "unsourced_figure")
    assert problem["in_passages"] == ["chunk_7a3f"]
    assert "quote claim" in problem["route"]
    assert "chunk_7a3f" in v.detail, "the route is on the line the model certainly reads"


def test_a_number_nowhere_on_the_ledger_is_refused_with_no_route_invented():
    from exposure_workbench.services import claims
    led = _ledger_with(_XOM)
    v = claims.check({"claims": [], "prose": ["Leverage is 3.7x."]}, led, question="q")
    problem = next(p for p in v.problems if p["reason"] == "unsourced_figure")
    assert "in_passages" not in problem and "route" not in problem


def test_the_route_is_exactly_as_precise_as_acceptance_would_be():
    """The guard `resolve_in_passages` carries: a bare short integer matches
    nearly any filing, and the 2026-09-05 battery linked an invented "low-20s
    percent" to a 10-K that happened to contain the digits 20. A hint is never
    offered where accepting would have manufactured a source."""
    from exposure_workbench.services import claims
    led = _ledger_with("There were 22 board meetings and 965 employees at four sites.")
    v = claims.check({"claims": [], "prose": ["It runs 22 sites."]}, led, question="q")
    problem = next(p for p in v.problems if p["reason"] == "unsourced_figure")
    assert "route" not in problem, "a bare short integer is not a source"


def test_a_passage_a_quote_claim_already_cites_is_not_offered_as_news():
    """The route names passages NOT already cited: one that is cited was
    searched by acceptance itself, and if the figure still failed, the passage
    is not the answer."""
    from exposure_workbench.services import claims
    led = _ledger_with(_XOM)
    v = claims.check({"claims": [], "prose": ["The rate is 9.9%."]}, led, question="q")
    problem = next(p for p in v.problems if p["reason"] == "unsourced_figure")
    assert "route" not in problem, "9.9% is in no passage at all"


# ── C. the rubric can see a reading, and a number off its basis ──────────────

def _rubric():
    import importlib.util
    path = pathlib.Path(fa.__file__).resolve().parents[3] / "scripts" / "rubric_battery.py"
    spec = importlib.util.spec_from_file_location("rubric_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_rubric_asks_whether_the_reading_holds_on_every_answered_turn():
    """Every criterion before V31 scored sourcing, coverage or form. None asked
    whether the conclusion follows from the figures, which is why V30 could
    halve the cost of a turn and report correctness "a dead heat"."""
    rb = _rubric()
    assert "reading_holds" in rb.SEMANTIC
    assert rb.ALWAYS_SEMANTIC == ("reading_holds",)
    d = rb.SEMANTIC["reading_holds"]
    assert "not whether the claim is true in the world" in d, "bounded to internal entailment"


def test_the_new_criterion_stays_out_of_the_totals_every_earlier_score_used():
    """A criterion applied to every turn would move every score line on
    unchanged code. This desk has already withdrawn one conclusion that was
    replicate noise; a second one that was a denominator change would be worse."""
    rb = _rubric()
    src = pathlib.Path(rb.__file__).read_text()
    assert "scored_now = {n: c for n, c in criteria.items() if n not in ALWAYS_SEMANTIC}" in src


def test_the_basis_detector_fires_on_the_two_defects_the_rounds_produced():
    """0 hits is only worth reporting if the instrument has teeth. These are the
    two documented cases: a days measure on a quarter grid (PHASE0 defect 1,
    days_inventory at 424–479 where annualised is ~106) and a ratio rendered as
    a percent (V29, a $1,135,470 spread shown as 113547000.0%)."""
    rb = _rubric()
    gold = [{"key": "dinv.MSFT", "value": 106.0, "unit": "COUNT", "subject": "MSFT",
             "note": "days_inventory"}]
    not_annualised = {"label": "days_inventory", "subject": "MSFT", "unit_class": "COUNT", "value": 429.9}
    assert "not annualised" in (rb._off_by_a_basis(not_annualised, gold) or "")

    gold_pct = [{"key": "spread", "value": 1135470.0, "unit": "MONEY", "subject": "port_001",
                 "note": "rank.spread"}]
    as_percent = {"label": "rank.spread", "subject": "port_001", "unit_class": "MONEY", "value": 113547000.0}
    assert "percent" in (rb._off_by_a_basis(as_percent, gold_pct) or "")


def test_two_different_quantities_a_round_multiple_apart_are_not_a_finding():
    """What the name constraint buys. Without it the detector fired 637 times on
    V26_R2; the five that survived subject+unit were `daily_return` against
    `window_return` and `contribution ÷ weight` against `contribution` — real
    figures, different quantities, a round multiple apart by chance."""
    rb = _rubric()
    gold = [{"key": "hr.AAPL", "value": -0.101768, "unit": "RATIO", "subject": "AAPL",
             "note": "holdings.window_return"}]
    other = {"label": "issuer_exposures.daily_return", "subject": "AAPL",
             "unit_class": "RATIO", "value": -0.0251059}
    assert rb._off_by_a_basis(other, gold) is None


# ── the scripts compile on the Python this project declares ─────────────────

def test_every_script_compiles_on_the_declared_minimum_python():
    """Found while building C. `scripts/brief_battery.py` — the instrument V31
    Phase 2 exists to build — could not be imported at all on Python 3.11: it
    put an implicit string concatenation inside an f-string replacement field,
    which is PEP 701 and needs 3.12, while pyproject declares >=3.11. The
    offline suite never imported it, so 2,254 tests were green over a script
    that could not start.

    The same shape as V28-R's `not`, one layer down: green tests over a thing
    nobody executed."""
    import py_compile

    root = pathlib.Path(fa.__file__).resolve().parents[3]
    broken = []
    for path in sorted((root / "scripts").rglob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True, cfile=str(path) + "c")
        except py_compile.PyCompileError as exc:
            broken.append(f"{path.relative_to(root)}: {exc.msg.splitlines()[-1][:120]}")
        finally:
            pathlib.Path(str(path) + "c").unlink(missing_ok=True)
    assert broken == [], "scripts that do not compile:\n  " + "\n  ".join(broken)


# ── 2. a quotation is routed to the passage that holds the words ─────────────

_HEDGE = ("The Corporation maintains a fixed-rate debt hedging program using "
          "fixed-for-floating interest rate swaps to manage its exposure.")


def test_a_verbatim_quotation_is_routed_to_the_uncited_passage_it_came_from():
    """`unverified_quote` is the second commonest refusal this desk issues (31
    of 143). A model that ran read_filings, read the words and reproduced them
    EXACTLY was told its quotation was unverified, while the passage it copied
    them from sat on the same ledger, uncited."""
    from exposure_workbench.services import claims

    led = _ledger_with(_HEDGE)
    v = claims.check({"claims": [],
                      "prose": ['The filing describes a "fixed-rate debt hedging program".']},
                     led, question="is that fixed or floating")

    assert v.ok is False and v.error == "unverified_quote", "acceptance is unchanged"
    problem = next(p for p in v.problems if p["reason"] == "unverified_quote")
    assert problem["in_passages"] == ["chunk_7a3f"]
    assert "quote claim" in problem["route"]
    assert "chunk_7a3f" in v.detail


def test_a_quotation_in_no_passage_at_all_is_refused_with_nothing_invented():
    from exposure_workbench.services import claims
    led = _ledger_with(_HEDGE)
    v = claims.check({"claims": [], "prose": ['It calls itself "the largest refiner in Texas".']},
                     led, question="q")
    problem = next(p for p in v.problems if p["reason"] == "unverified_quote")
    assert "route" not in problem and "in_passages" not in problem


def test_the_quotation_route_reads_the_words_the_way_the_check_does():
    """One spelling of "the same words": the route imports `gate._normalise`,
    the same function `verify_quotes` uses, so curly quotes, dashes and case
    cannot make the check and the hint disagree."""
    from exposure_workbench.services import claims
    led = _ledger_with(_HEDGE)
    v = claims.check({"claims": [],
                      "prose": ['It runs a “FIXED-RATE debt hedging   program” today.']},
                     led, question="q")
    problem = next(p for p in v.problems if p["reason"] == "unverified_quote")
    assert problem.get("in_passages") == ["chunk_7a3f"], "normalised the same way on both sides"


# ── 3. a domain says which of its methods refuse for THIS subject ────────────

def test_a_domain_names_the_methods_this_issuer_cannot_feed():
    """The desk's own seven issuer domains run over JPM produce 50 figures and
    32 refusals, 18 of them `not_applicable` — days sales outstanding, days
    inventory and the cash conversion cycle asked of a bank
    (tests/battery/gold_brief.json). The reasons existed, in
    `fundamentals.methods_not_computable`, a different section of the same
    payload; a model reading a domain had to cross-reference to learn the
    domain did not apply, and did not."""
    from exposure_workbench.services import catalogue_service as cat
    from exposure_workbench.analytics import formulas as fm

    refuses = {n: "not for a financial issuer"
               for n, f in fm.FORMULAS.items() if f.not_for_financials is not None}
    domains = {d["name"]: d for d in cat._procedures("issuer", False, "JPM", refuses=refuses)}

    credit = domains["issuer_credit_and_balance_sheet"]
    assert set(credit["methods_that_refuse_here"]) == set(credit["methods"]), \
        "every method of the credit domain refuses for a bank, and the domain says so once"
    quality = domains["issuer_earnings_quality"]
    assert {"days_sales_outstanding", "days_inventory", "cash_conversion_cycle"} <= set(
        quality["methods_that_refuse_here"])


def test_a_domain_with_nothing_to_warn_about_says_nothing():
    """The payload grows only where there is something to say — the rule the
    catalogue's `lines` follows too."""
    from exposure_workbench.services import catalogue_service as cat
    for d in cat._procedures("issuer", False, "AAPL", refuses={}):
        assert "methods_that_refuse_here" not in d


def test_the_key_the_payload_gained_is_explained_where_the_keys_are_explained():
    from exposure_workbench.services import catalogue_service as cat
    assert "methods_that_refuse_here" in cat._HOW_TO_READ
