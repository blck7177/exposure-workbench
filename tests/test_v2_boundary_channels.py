"""V2 P1.1 (design v0.4 G1, acceptance A2): one boundary for every channel the
analyst writes in. A figure moved from a finding into a caveat, an unsettled
line's why or a follow-up meets the same lookup against the same ledger and gets
the same reason back; a figure that points at its row passes wherever it sits.
Offline: the protocol, the check and the ledger are real.
"""

from __future__ import annotations

import pytest

from exposure_workbench.agents import delegation as dl
from exposure_workbench.services import analysis_state as S, fact_boundary
from exposure_workbench.services.ledger import Ledger

WEIGHT = {"id": "f_w1a2b3c4d5e6", "kind": "scalar", "measure": "issuer_exposures.weight", "subject": "MSFT", "unit": "RATIO",
          "value": 0.16, "as_of": "2026-09-10", "window": None, "params": {"pull": "r_1", "of": "run_x"},
          "standalone": True, "sources": ["run_x"], "group": "composition", "means": {}}
LEDGER = Ledger.of([WEIGHT])
TASK = dl.Task("tsk_1", "risk", ("port_001",), ("how big MSFT is in the book", "where MSFT's weight will be next year"))
UNSOURCED = "MSFT weighs 23.4% of the book."
SOURCED = "MSFT weighs 16.0% [f_w1a2b3c4d5e6] of the book."
POLICY = "f_policy_no_forecast"
WHERE = {"finding": "line 1", "caveat": "caveats[0]", "why": "line 2 / why", "follow_up": "follow_ups[0]"}


def _brief(finding: str = SOURCED, caveat: str | None = None, why: str = "the desk does not forecast",
           follow_up: str | None = None) -> dict:
    return {"lines": [{"n": 1, "settled": True, "finding": finding, "facts": ["f_w1a2b3c4d5e6"]},
                      {"n": 2, "settled": False, "why": why, "boundary": POLICY}],
            "caveats": [{"line": 1, "text": caveat}] if caveat else [],
            "follow_ups": [follow_up] if follow_up else []}


@pytest.mark.parametrize("channel", sorted(WHERE))
def test_the_same_unsourced_sentence_gets_the_same_reason_in_every_channel(channel):
    v = dl.handoff_check(TASK, _brief(**{channel: UNSOURCED}), LEDGER)
    assert not v.ok
    assert {p["reason"] for p in v.problems} == {"unsourced_figure"}
    assert {p["where"] for p in v.problems} == {WHERE[channel]}, "the problem says which channel"
    assert {p.get("rule") for p in v.problems} == {1}, "and which rule of the style guide"


@pytest.mark.parametrize("channel", sorted(WHERE))
def test_the_same_sourced_sentence_passes_in_every_channel(channel):
    v = dl.handoff_check(TASK, _brief(**{channel: SOURCED}), LEDGER)
    assert v.ok, v.problems
    assert [e["n"] for e in v.kept] == [1, 2]
    if channel == "caveat":
        assert v.caveats_ok == [{"line": 1, "text": SOURCED}]
    if channel == "follow_up":
        assert v.follow_ups_ok == [SOURCED]


def test_what_failed_is_not_handed_on_and_what_passed_is():
    v = dl.handoff_check(TASK, _brief(caveat=UNSOURCED, why=UNSOURCED, follow_up=UNSOURCED), LEDGER)
    assert v.caveats_ok == [] and v.follow_ups_ok == []
    assert [e["n"] for e in v.rejected] == [2], "an unsettled line whose why fails is refused like a finding"
    assert [e["n"] for e in v.kept] == [1]
    assert v.coverage == {"asked": 2, "settled": 1, "unsettled": 0, "refused": 1}


def test_a_question_without_a_figure_costs_nothing():
    v = dl.handoff_check(TASK, _brief(follow_up="Which other names in the book hold the same sector?"), LEDGER)
    assert v.ok and v.follow_ups_ok == ["Which other names in the book hold the same sector?"]


# ── V2 P5: the boundary is one function, and every channel is on its list ────

@pytest.mark.parametrize("channel", fact_boundary.CHANNELS)
def test_every_channel_gives_the_same_verdict_for_the_same_sentence(channel):
    bad = fact_boundary.check_text(channel, UNSOURCED, LEDGER, question="how big is MSFT?")
    good = fact_boundary.check_text(channel, SOURCED, LEDGER, question="how big is MSFT?")
    assert [p["reason"] for p in bad.problems] == ["unsourced_figure"] and bad.problems[0]["channel"] == channel
    assert good.ok


def test_a_way_a_sentence_reaches_the_record_is_declared_here_or_refused():
    with pytest.raises(ValueError, match="not a channel"):
        fact_boundary.check_text("memory", SOURCED, LEDGER)
    assert set(fact_boundary.CHANNELS) == {"answer", "finding", "caveat", "why", "follow_up", "state_proposal"}


def test_a_state_proposal_meets_the_same_boundary_as_a_finding():
    st = S.new_turn("sess", "msg", "how big is MSFT?", {"subjects": {"tickers": ["MSFT"], "portfolios": [], "runs": []}})
    as_finding = dl.handoff_check(TASK, _brief(finding=UNSOURCED), LEDGER).problems[0]
    as_proposal = S.check_text("hypothesis", UNSOURCED, LEDGER, "how big is MSFT?").problems[0]
    assert (as_finding["reason"], as_finding["rule"]) == (as_proposal["reason"], as_proposal["rule"]) == ("unsourced_figure", 1)
    assert as_proposal["channel"] == "state_proposal" and as_proposal["where"] == "hypothesis"
    assert st.findings == []


def test_a_possessive_names_the_company():
    """9/19 review ②: "MSFT's revenue was $416B [AAPL's id]" passed because the word
    read was msft's. The possessive names its owner now, and the figure is AAPL's."""
    aapl = {"id": "f_aapl1234567", "kind": "scalar", "measure": "revenue", "subject": "AAPL", "unit": "MONEY",
            "value": 416.2e9, "as_of": "2025-09-27", "window": {"start": "2024-09-29", "end": "2025-09-27"},
            "params": {"pull": "r_9"}, "standalone": True, "sources": ["fact_1"], "group": "fundamentals", "means": {}}
    led = Ledger.of([WEIGHT, aapl])
    wrong = fact_boundary.check_text("answer", "MSFT's revenue was $416B [f_aapl1234567].", led)
    assert [p["reason"] for p in wrong.problems] == ["subject_mismatch"]
    right = fact_boundary.check_text("answer", "AAPL's revenue was $416B [f_aapl1234567].", led)
    assert right.ok, right.problems
