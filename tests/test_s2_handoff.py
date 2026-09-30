"""Evidence-first handoff: shared factual boundary and item-preserving repairs."""
import copy

import pytest

from exposure_workbench.agents import handoff
from exposure_workbench.services import answer_check, fact_boundary
from exposure_workbench.services.ledger import Ledger
from tests.test_v2_state import WEIGHT, WEIGHT_AGAIN, UNREAD

FID = WEIGHT["id"]
LEDGER = Ledger.of([WEIGHT, WEIGHT_AGAIN, UNREAD])
TEXT = "MSFT weighs 16.0% of the book."


def test_block_refs_render_the_same_fact_links_as_inline_refs():
    canonical, verdict = fact_boundary.check_block("finding", TEXT, [FID], LEDGER)
    inline = f"MSFT weighs 16.0% [{FID}] of the book."
    assert canonical == inline and verdict.ok, verdict.problems
    old = fact_boundary.check_text("finding", inline, LEDGER)
    assert answer_check.accepted(canonical, verdict, LEDGER) == answer_check.accepted(inline, old, LEDGER)


@pytest.mark.parametrize("text,refs,reason", [
    ("MSFT weighs 99.0% of the book.", [FID], "unsourced_figure"),
    ("AAPL weighs 16.0% of the book.", [FID], "subject_mismatch"),
    ("MSFT weighs $16.0 of the book.", [FID], "unsourced_figure"),
    (f"MSFT weighs 16.0% [{FID}] of the book.", [], "not_on_ledger"),
    ("MSFT weighs 12.0% of the book.", [FID], "unsourced_figure"),
    (TEXT, ["f_missing1234"], "not_on_ledger"),
])
def test_block_scope_does_not_let_unrelated_evidence_validate_a_note(text, refs, reason):
    _, verdict = fact_boundary.check_block("finding", text, refs, LEDGER)
    assert not verdict.ok and reason in {p["reason"] for p in verdict.problems}


def test_same_value_under_different_subjects_is_not_guessed():
    other = {**UNREAD, "value": WEIGHT["value"]}
    ledger = Ledger.of([WEIGHT, other])
    _, bad = fact_boundary.check_block("finding", TEXT, [FID, other["id"]], ledger)
    assert "ambiguous_reference" in {p["reason"] for p in bad.problems}
    _, good = fact_boundary.check_block("finding", TEXT, [FID], ledger)
    assert good.ok


def test_same_value_on_two_dates_needs_an_explicit_point():
    series = {**WEIGHT, "id": "f_series12345", "kind": "series", "value": None,
              "points": [["2024-12-31", .16], ["2025-12-31", .16]]}
    ledger = Ledger.of([series])
    _, bad = fact_boundary.check_block("finding", TEXT, [series["id"]], ledger)
    assert not bad.ok and any(p["reason"] == "ambiguous_reference" for p in bad.problems)
    _, good = fact_boundary.check_block("finding", "MSFT weighs 16.0% [f_series12345@2024-12-31].", [series["id"]], ledger)
    assert good.ok, good.problems


def test_passage_units_are_not_inferred_from_a_block_reference():
    passage = {**WEIGHT, "id": "f_passage1234", "kind": "passage", "value": None,
               "text": "Revenue was $100 million during the year."}
    ledger = Ledger.of([passage])
    _, bad = fact_boundary.check_block("finding", "Revenue was $100 million.", [passage["id"]], ledger)
    assert not bad.ok and "passage_requires_pointer" in {p["reason"] for p in bad.problems}
    _, good = fact_boundary.check_block("finding", 'The filing states “Revenue was $100 million during the year.”', [passage["id"]], ledger)
    assert good.ok, good.problems


def test_submission_preserves_each_good_item_and_assigns_ids_for_repairs():
    state = handoff.Submission()
    reply = state.apply(handoff.parse({"evidence": [FID, "f_absent1234"], "notes": [
        {"text": TEXT + " The current run is the basis.", "refs": [FID]},
        {"text": "MSFT weighs 99.0%.", "refs": [FID]}]}), LEDGER, "How big is MSFT?")
    good, bad = [entry["id"] for entry in reply["note_ids"]]
    before = copy.deepcopy(state.notes[good])
    assert not reply["accepted"] and state.evidence == [FID] and list(state.notes) == [good]
    reply = state.apply({"evidence": [], "notes": [{"id": bad, "text": TEXT, "refs": [FID]}]}, LEDGER, "")
    assert reply["accepted"] and set(state.notes) == {good, bad}
    assert state.notes[good] == before
    # A bad revision cannot delete the previous accepted version or qualification.
    state.apply({"evidence": [], "notes": [{"id": good, "text": "MSFT weighs 99.0%.", "refs": [FID]}]}, LEDGER, "")
    assert state.notes[good] == before
    state.apply({"evidence": [], "notes": [{"id": good, "text": "", "refs": []}]}, LEDGER, "")
    assert state.ok and good not in state.notes


def test_evidence_only_needs_no_line_closure_or_synthetic_boundary():
    state = handoff.Submission()
    assert state.apply(handoff.parse({"evidence": [FID]}), LEDGER, "")['accepted']
    assert state.notes == {} and state.evidence == [FID]
    with pytest.raises(handoff.BadSubmission, match="old lines"):
        handoff.parse({"lines": [{"n": 1, "settled": True}]})


def test_refs_cannot_borrow_an_unnamed_policy():
    _, verdict = fact_boundary.check_block("finding", "The desk does not forecast [f_policy_no_forecast].", [], LEDGER)
    assert not verdict.ok and any(p["reason"] == "not_on_ledger" for p in verdict.problems)


def test_unknown_note_id_can_be_corrected_without_a_permanent_repair_obligation():
    state = handoff.Submission()
    state.apply({"evidence": [FID], "notes": [{"id": "invented", "text": TEXT, "refs": [FID]}]}, LEDGER, "")
    assert not state.ok
    reply = state.apply({"evidence": [], "notes": [{"text": TEXT, "refs": [FID]}]}, LEDGER, "")
    assert reply["accepted"] and len(state.notes) == 1


def test_block_adapter_preserves_period_checks_and_explicit_chart_rendering():
    from tests.test_v33_answer_check import _series
    series = _series("f_annual1234", "net_margin", "LLY", [
        ["2021-12-31", .197], ["2022-12-31", .219], ["2023-12-31", .154],
        ["2024-12-31", .235], ["2025-12-31", .317]])
    ledger = Ledger.of([series])
    for period, ok in [("twelve quarters", False), ("five fiscal years", True)]:
        canonical, verdict = fact_boundary.check_block("finding",
            f"Net margin over the last {period} was 19.7% and 31.7%.", [series["id"]], ledger)
        assert verdict.ok == ok, verdict.problems
        assert verdict.ok == fact_boundary.check_text("finding", canonical, ledger).ok
        if not ok:
            assert any(p["reason"] == "period_mismatch" for p in verdict.problems)
    canonical, verdict = fact_boundary.check_block("finding", "[chart: s_lly]", [series["id"]], ledger)
    assert verdict.ok
    assert answer_check.accepted(canonical, verdict, ledger)["blocks"][0]["type"] == "chart"


@pytest.mark.parametrize("text,refs,reason", [
    ("AMZN has the highest capex intensity at 18.4%.", ["f_ciamzn"], "superlative_without_rank"),
    ("Revenue fell 12.4% year over year.", ["f_yoy001"], "direction_conflict"),
])
def test_block_adapter_keeps_comparison_and_direction_boundaries(text, refs, reason):
    from tests.test_v33_answer_check import LEDGER as corpus
    _, verdict = fact_boundary.check_block("finding", text, refs, corpus)
    assert not verdict.ok and reason in {p["reason"] for p in verdict.problems}
