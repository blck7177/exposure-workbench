"""The observer against the recorded Q07 analysis view (tests/fixtures/q07_view.json,
built by services/analysis_execution on the frozen fixture: three Technology names,
cash conversion against the comparable twelve months a year earlier, weight against
the previous run, both ranked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from exposure_workbench.services import observer as ob

VIEW = json.loads((Path(__file__).resolve().parent / "fixtures" / "q07_view.json").read_text())
VIEW.pop("_facts", None)
Q = ("Rank our five technology holdings by cash conversion, operating cash flow over net income, for the trailing twelve "
     "months and by the change in that ratio against the prior twelve months. Which name has the weakest conversion, and "
     "is it also the one whose weight in the book grew most since the previous run?")

CORRECT = """The book holds three Technology names, not five: AAPL, MSFT and NVDA.

On the latest twelve months MSFT converts best at 135.9%, AAPL follows at 114.4% and NVDA is weakest at 69.7%. Against the comparable twelve months a year earlier AAPL improved by 1.79 percentage points and MSFT by 0.62 percentage points, while NVDA fell 19.3 percentage points.

NVDA has the weakest conversion and the sharpest deterioration. NVDA is not the name whose weight grew most: AAPL's weight rose 0.47 percentage points between the prior and latest runs, while NVDA's slipped 0.11 pp."""

WRONG_UNITS = """The portfolio has three Technology holdings, not five—AAPL, MSFT and NVDA.

Latest trailing-twelve-month cash conversion: MSFT 135.9%, AAPL 114.4%, NVDA 69.7%.

Change from each issuer's prior trailing twelve months: AAPL up 1.79%. MSFT up 0.62%. NVDA -19.3%.

NVDA has the weakest conversion. AAPL had the largest weight increase, 0.47%, between the prior and latest runs."""


def observe(text: str) -> ob.Verdict:
    return ob.observe(text, question=Q, views=[VIEW])


def test_a_correct_answer_in_percentage_points_is_supported_and_complete():
    v = observe(CORRECT)
    assert v.ok, v.feedback()
    s = v.summary()
    assert s["figures"] == 8 and s["supported"] == 8 and s["contradicted"] == 0 and s["unsourced"] == 0
    assert v.completion["status"] == "full"
    assert {r.get("measure") or "scope": r["status"] for r in v.completion["requests"]} == {
        "cash_conversion": "covered", "book.weight": "covered", "scope": "covered"}
    assert len(v.citations) == 8
    assert all(s["status"] == ob.SUPPORTED for s in v.superlatives)


def test_a_change_written_as_a_percent_is_contradicted_with_the_pp_figure():
    v = observe(WRONG_UNITS)
    assert not v.ok
    bad = [p for p in v.propositions if p.status == ob.CONTRADICTED]
    assert {p.token for p in bad} == {"1.79%", "0.62%", "-19.3%", "0.47%"}
    assert all(p.reason == "unit_kind" for p in bad)
    fb = v.feedback()
    assert "percentage POINTS" in fb and "-19.3 pp" in fb and "+1.79 pp" in fb
    assert "f_" not in fb                      # business feedback carries no pointer protocol
    assert v.completion["status"] == "partial"


@pytest.mark.parametrize("text, expect_ok", [
    ("NVDA's cash conversion fell 19.3 percentage points.", True),
    ("NVDA's cash conversion changed by -19.3 pp.", True),
    ("NVDA's cash conversion fell by 19.3%.", False),              # a percent is not percentage points
    ("NVDA's cash conversion rose 19.3 percentage points.", False),  # the direction is wrong
    ("NVDA's cash conversion is 69.7%.", True),
    ("NVDA's cash conversion is 69.7 percentage points.", False),   # a level is not a change
])
def test_kind_and_direction_are_read_off_the_sentence(text, expect_ok):
    v = observe(text)
    assert v.ok is expect_ok, (text, v.feedback())


def test_a_figure_the_desk_never_computed_is_unsupported():
    v = observe("AAPL's cash conversion is 12.5% on the latest twelve months.")
    assert [p.status for p in v.propositions if p.token == "12.5%"] == [ob.UNSUPPORTED]
    assert "matches nothing the desk computed" in v.feedback()


def test_a_superlative_is_read_against_the_orderings():
    assert observe("NVDA has the weakest cash conversion of the three.").ok
    assert observe("AAPL had the largest weight increase.").ok
    assert observe("NVDA shows the sharpest deterioration in cash conversion.").ok    # a decline's superlative is the bottom
    v = observe("MSFT has the weakest cash conversion of the three.")
    assert not v.ok and v.superlatives[0]["status"] == ob.CONTRADICTED
    assert "MSFT 135.9% > AAPL 114.4% > NVDA 69.7%" in v.feedback()


def test_a_negated_superlative_is_the_models_judgement():
    v = observe("NVDA is not the name whose weight grew most.")
    assert v.ok and v.superlatives == []


def test_a_sentence_without_a_figure_is_judgement_not_a_problem():
    v = observe("The premise needs correcting: the book holds three Technology names, and the weakest converter is also the one shedding weight.")
    assert v.ok
    assert all(s["status"] == ob.JUDGEMENT for s in v.sentences)


def test_a_partial_answer_is_honest_about_what_it_covers():
    v = observe("I can only speak to AAPL: its weight rose from 14.7% to 15.2%, a +0.47 percentage point move.")
    assert v.ok
    assert v.completion["status"] == "partial"
    by = {r.get("measure") or "scope": r["status"] for r in v.completion["requests"]}
    assert by["cash_conversion"] == "not_stated" and by["book.weight"] == "partial"


def test_numbers_of_the_question_and_dates_are_not_figures():
    v = observe("Over 2025-03-30 to 2026-03-28 AAPL, one of the five holdings you named, converts 114.4%.")
    kinds = {p.token: p.status for p in v.propositions}
    assert kinds["114.4%"] == ob.SUPPORTED
    assert all(st in (ob.IDENTITY, ob.QUESTION, ob.SUPPORTED) for st in kinds.values())
