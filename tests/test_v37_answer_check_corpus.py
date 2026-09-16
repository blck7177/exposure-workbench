"""V37 Phase B — every new rule, run over the answers a round already accepted.

A rule that refuses a false sentence can refuse a true one, and the expensive
way to find that out is another twenty-question live round. This is the cheap way
that works: round B's fifteen accepted answers, each with the ledger it was
accepted on (`scripts/v37_corpus.py`, rebuilt per round), replayed offline.

Two questions, and the second is the one that matters:

  1. does the check still accept what it accepted — the corpus reproducing the
     round is what makes any of this evidence
  2. does each new rule refuse EXACTLY the sentences the analysis named, and
     nothing else

So the expectations below are per rule and by name. A rule that fires on a
sixteenth sentence fails here, and it should: the analysis read all fifteen
answers, and a refusal it did not predict is either a finding nobody has written
down or a rule that is too wide.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from exposure_workbench.services import answer_check
from exposure_workbench.services.ledger import Ledger

CORPUS = Path(__file__).resolve().parent / "data" / "v36b_accepted.json.gz"


def _answers() -> list[dict]:
    if not CORPUS.exists():
        pytest.skip(f"{CORPUS.name} not built; scripts/v37_corpus.py makes it from a round + its db")
    return json.loads(gzip.decompress(CORPUS.read_bytes()))["answers"]


def _verdicts() -> dict[str, object]:
    """The check's verdict on every accepted answer, by question tag."""
    return {a["tag"][:3]: answer_check.check(a["text"], Ledger.of(a["facts"]), question=a["question"])
            for a in _answers()}


# The rules Phase B added, by reason. The reproduce test below reads the corpus
# WITHOUT them, so it keeps answering its own question — is this corpus faithful
# to the round — while each rule's own test owns the refusals it introduced. A
# rule added without a line here makes the reproduce test fail, which is the
# point: a new refusal is either predicted or it is a finding nobody has written
# down.
RULES_ADDED_SINCE_THE_ROUND = ("period_mismatch",)


def test_the_corpus_reproduces_the_round_it_was_taken_from():
    """Fifteen answers round B accepted, accepted again offline. If this fails,
    nothing else in this file is evidence about anything: either the ledger was
    rebuilt differently from the way the check read it, or a rule changed without
    its effect being written down."""
    answers = _answers()
    assert len(answers) == 15, "round B accepted fifteen"
    left = {tag: sorted({p["reason"] for p in v.problems} - set(RULES_ADDED_SINCE_THE_ROUND))
            for tag, v in _verdicts().items()}
    assert {tag: r for tag, r in left.items() if r} == {}, \
        "the check that accepted these still accepts them, apart from the rules added since"


# ── V4: the period a sentence claims, against the readings' own dates ─────────

# What the analysis of round B named, by question and by count of sentences. Q02
# made the same false claim three times ("the same four quarter-ends were …" for
# each of leverage, coverage and cash generation), which is three sentences and
# one mistake.
V4_EXPECTED = {"Q02": 3, "Q04": 1, "Q09": 1, "Q12": 1}


def test_the_period_rule_refuses_exactly_the_sentences_the_analysis_named():
    """Five of round B's eleven false statements were this class, and every one
    of them had its own evidence's dates printed in the same sentence:

      Q02  "One year earlier, the same four quarter-ends were …" — five ANNUAL points
      Q04  "over the last twelve quarters: 19.7%, 21.9%, 15.4%, 23.5%, 31.7%" — five annual
      Q09  "the three-year low … and the three-year high" — six annual points over five years
      Q12  "over the last three years was 12.66×, 12.21×, 13.46×" — three QUARTER-ends

    The other eleven accepted answers must come through untouched. A sixteenth
    refusal here is not a bonus: the analysis read all fifteen, so it would mean
    either a finding nobody wrote down or a rule that is too wide."""
    got: dict[str, int] = {}
    for tag, v in _verdicts().items():
        n = len([p for p in v.problems if p["reason"] == "period_mismatch"])
        if n:
            got[tag] = n
    assert got == V4_EXPECTED


def test_the_period_rule_is_the_only_thing_that_changed_about_these_answers():
    """Whatever else the round accepted, it still accepts: a new rule that also
    moved an old one would make the count above unreadable."""
    for tag, v in _verdicts().items():
        others = sorted({p["reason"] for p in v.problems if p["reason"] != "period_mismatch"})
        assert others == [], (tag, others)


def test_a_refused_period_says_what_the_readings_are():
    """The analyst is told what it has, not only that it is wrong: a sentence
    that says "twelve quarters" over five annual points cannot be fixed by
    rewording alone, and the way out is either the period the desk showed or a
    request for the series the question asked for."""
    v = _verdicts()["Q04"]
    [p] = [p for p in v.problems if p["reason"] == "period_mismatch"]
    assert p["word"] == "twelve quarters"
    assert "5 annual reading(s)" in p["holds"] and "2021-12-31..2025-12-31" in p["holds"]
    assert "request the series the question asked for" in p["fix"]
