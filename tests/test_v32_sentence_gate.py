"""V32 — the gate's unit becomes the sentence.

`_check_relation` takes one claim and `check` ran it over the claims
independently, so an answer whose claims are each impeccable and which together
say something false was unreachable. Two such sentences were accepted in V26_C3
(docs/AGENT_GAP_2026-09-10.md §§10-11, §13).
"""

from __future__ import annotations

import pytest

from exposure_workbench.services import claims as C
from exposure_workbench.services import facts as F
from exposure_workbench.services.ledger import Ledger

MSFT_CHECK = "limit_checks.issuer_concentration:MSFT.current_value"
ROOM = "subtract(limit_checks.breach_level, limit_checks.current_value)"


def _f(kind, measure, **kw):
    return F.fact(kind, measure, **kw)


# ── the splitter, because a desk's sentences are full of decimal points ──────

def test_a_decimal_point_does_not_end_a_sentence():
    """`[^.!?]+` cut "-26.0%" into "-26" and "0%", and every rule below then
    looked at fragments. The estimate that reported 0 hits on answers plainly
    ordering figures is what caught it."""
    s = "MSFT was the worst at -26.0% (#1), then LLY at -20.6% (#2). The book fell 12.0%."
    assert C.sentences_of(s) == ["MSFT was the worst at -26.0% (#1), then LLY at -20.6% (#2).",
                                 "The book fell 12.0%."]


# ── one quantity, written twice ─────────────────────────────────────────────

def test_one_reading_stated_twice_in_a_sentence_is_not_a_comparison():
    """W05-half-taken-back t1, accepted in C3: "concentration at 8.76%, down
    from 8.76%" — two `level` claims on the same check of two scenario rows."""
    before = _f(F.SCALAR, MSFT_CHECK, subject="calc_A", unit="RATIO", value=0.0875769, as_of="2026-09-04", params={"node": "a"})
    after = _f(F.SCALAR, MSFT_CHECK, subject="calc_B", unit="RATIO", value=0.0875769, as_of="2026-09-04", params={"node": "b"})
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": after.id},
                            {"id": "c2", "relation": "level", "of": before.id}],
                 "prose": ["concentration is {c1}, down from {c2}."]}, Ledger.of_facts([before, after]))
    assert v.error == "same_figure_twice"
    assert v.problems[0]["claim"] == "c1" and v.problems[0]["against"] == "c2"


def test_two_holders_that_happen_to_be_level_is_a_true_sentence():
    """The guard on the rule above: "MSFT is 10.0% and JPM is 10.0%" states two
    readings of two holders. Only subjects that are ledger handles — the same
    quantity on two runs — are the case this refuses."""
    a = _f(F.SCALAR, "issuer_exposures.weight", subject="MSFT", unit="RATIO", value=0.10, as_of="2026-09-04", params={"node": "w", "label": "MSFT"})
    b = _f(F.SCALAR, "issuer_exposures.weight", subject="JPM", unit="RATIO", value=0.10, as_of="2026-09-04", params={"node": "w", "label": "JPM"})
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": a.id},
                            {"id": "c2", "relation": "level", "of": b.id}],
                 "prose": ["MSFT is {c1} and JPM is {c2}."]}, Ledger.of_facts([a, b]))
    assert v.ok, (v.error, v.problems)


def test_the_same_reading_in_two_different_sentences_is_left_alone():
    """The unit is the sentence. Restating a figure in a later sentence is
    repetition, not a comparison with itself."""
    a = _f(F.SCALAR, MSFT_CHECK, subject="calc_A", unit="RATIO", value=0.0875769, as_of="2026-09-04", params={"node": "a"})
    b = _f(F.SCALAR, MSFT_CHECK, subject="calc_B", unit="RATIO", value=0.0875769, as_of="2026-09-04", params={"node": "b"})
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": a.id},
                            {"id": "c2", "relation": "level", "of": b.id}],
                 "prose": ["Concentration is {c1}. After the sale it is {c2}."]}, Ledger.of_facts([a, b]))
    assert v.ok, (v.error, v.problems)


# ── an ordering asserted over figures the sentence states ────────────────────

def _three_rooms():
    return [_f(F.SCALAR, ROOM, subject=s, unit="RATIO", value=x, as_of="2026-09-04",
               params={"node": "room", "label": s})
            for s, x in (("daily_loss", 0.0186), ("conc:MSFT", 0.0390), ("conc:LLY", -0.0070))]


def test_a_sentence_that_orders_two_readings_of_one_measure_needs_a_rank():
    """C3 accepted 23 answers (upper bound, scripts/v32_estimate.py) whose prose
    ordered figures — "the worst name is NVDA at 1.92x (#1), then AMZN at 1.43x
    (#2)" — with no rank claim and nothing that computed the ordering."""
    rooms = _three_rooms()
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": rooms[0].id},
                            {"id": "c2", "relation": "level", "of": rooms[1].id}],
                 "prose": ["The closest to its stop is {c1}, then {c2}."]}, Ledger.of_facts(rooms))
    assert v.error == "ordering_not_computed"
    assert '"fn": "rank"' in v.problems[0]["detail"] and "$room" in v.problems[0]["detail"]


def test_the_same_sentence_passes_once_the_ordering_is_computed():
    rooms = _three_rooms()
    ranked = _f(F.SCALAR, ROOM, subject="daily_loss", unit="RATIO", value=0.0186, as_of="2026-09-04",
                params={"node": "ord", "label": "daily_loss", "rank": 1})
    second = _f(F.SCALAR, ROOM, subject="conc:MSFT", unit="RATIO", value=0.0390, as_of="2026-09-04",
                params={"node": "ord", "label": "conc:MSFT", "rank": 2})
    v = C.check({"claims": [{"id": "c1", "relation": "rank", "of": ranked.id},
                            {"id": "c2", "relation": "rank", "of": second.id}],
                 "prose": ["The closest to its stop is {c1}, then {c2}."]},
                Ledger.of_facts(rooms + [ranked, second]))
    assert v.ok, (v.error, v.problems)


def test_one_figure_and_an_ordering_word_is_left_alone():
    """Precision over recall, because this refuses a reader's answer. "The
    closest thing I have is {c1}" orders nothing; the looser rule (one figure
    that is an entry of a vector) fired on 30% of C3's accepted answers, several
    of that shape. The cost is a miss, stated in the code."""
    rooms = _three_rooms()
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": rooms[0].id}],
                 "prose": ["The closest thing I actually have is {c1}."]}, Ledger.of_facts(rooms))
    assert v.ok, (v.error, v.problems)


def test_a_sentence_with_no_ordering_word_is_left_alone():
    rooms = _three_rooms()
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": rooms[0].id},
                            {"id": "c2", "relation": "level", "of": rooms[1].id}],
                 "prose": ["Room to breach is {c1} on the loss check and {c2} on MSFT."]},
                Ledger.of_facts(rooms))
    assert v.ok, (v.error, v.problems)


# ── the rule reaches the model, and the desk counts what it refuses ──────────

def test_the_model_is_told_the_sentence_is_read():
    from exposure_workbench.agents import meta_agent
    from exposure_workbench.tools.registries import build_meta_registry
    assert "rank claim" in meta_agent._SYSTEM
    assert "SENTENCE is read too" in build_meta_registry().tools["respond"].description


def test_the_counter_and_the_gate_order_by_one_list():
    """A word the gate refuses a sentence for and a word the desk counts as a
    superlative are the same word, or the two numbers drift."""
    import importlib.util
    import pathlib
    path = pathlib.Path(C.__file__).resolve().parents[3] / "scripts" / "battery_counters.py"
    spec = importlib.util.spec_from_file_location("counters_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._SUPERLATIVE is C.ORDERING_WORDS


# ── G4 runs last, so the model fixes one thing at a time ────────────────────

def test_an_unaccounted_digit_is_still_reported_before_the_sentence_rule():
    rooms = _three_rooms()
    v = C.check({"claims": [{"id": "c1", "relation": "level", "of": rooms[0].id},
                            {"id": "c2", "relation": "level", "of": rooms[1].id}],
                 "prose": ["The closest to its stop is {c1}, then {c2}, and leverage is 3.7x."]},
                Ledger.of_facts(rooms))
    assert v.error == "unsourced_figure"
