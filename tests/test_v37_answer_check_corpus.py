"""V37 Phase B — every new rule, run over the answers a round already accepted.

A rule that refuses a false sentence can refuse a true one, and the expensive
way to find that out is another twenty-question live round. This is the cheap way
that works: round B's fifteen accepted answers, each with the ledger it was
accepted on (`scripts/v37_corpus.py`, rebuilt per round), replayed offline.

One table answers both questions this file exists to ask — does the corpus still
reproduce the round, and does each new rule refuse exactly the sentences the
analysis named. A rule that fires on a sixteenth sentence fails here, and it
should: the analysis read all fifteen answers, so an unpredicted refusal is
either a finding nobody has written down or a rule that is too wide.
"""
from __future__ import annotations

import collections
import gzip
import json
from pathlib import Path

import pytest

from exposure_workbench.services import answer_check
from exposure_workbench.services.ledger import Ledger

CORPUS = Path(__file__).resolve().parent / "data" / "v36b_accepted.json.gz"

# WHAT THE RULES ADDED SINCE ROUND B REFUSE, by question and reason. Every entry
# is a sentence `docs/spikes/v36/ACCEPTANCE_V36B.md` §4 named as false; every
# question absent from this table was accepted then and is accepted now.
#
#   V4 · period_mismatch — the period a sentence claims, against its readings' dates
#     Q02  "One year earlier, the same four quarter-ends were …" ×3 — five ANNUAL points
#     Q04  "over the last twelve quarters: 19.7%, 21.9%, 15.4%, 23.5%, 31.7%" — five annual
#     Q09  "the three-year low … and the three-year high" — six annual points over five years
#     Q12  "over the last three years was 12.66×, 12.21×, 13.46×" — three QUARTER-ends
#   V1 · superlative_without_rank — a superlative with no figure beside it
#     Q11  "The closest issuer-concentration warning is for LLY." — LLY's room to
#          warning is 19th of 20, the second smallest, and fifty-one placed facts
#          for LLY hold no end place at all
#   V2 · subject_mismatch — whose figure it is, when the sentence says the book's
#     Q02  "The book's beta to USO is 0.33×" over `XOM.beta.USO` — one name's
#          sensitivity offered as the whole book's, and the analyst had written the
#          truth into a caveat the lead never read. The eleventh false statement,
#          which the round's own audit missed.
#   V3 · id_in_prose — a report id reaching the reader
#     Q06  "… not as-of a past date [rep_3d15ad4012b4]" — round A did it five
#          times in one answer
ADDED_SINCE_THE_ROUND = {
    "Q02": {"period_mismatch": 3, "subject_mismatch": 1},
    "Q04": {"period_mismatch": 1},
    # S3: eight table values had no currency mark at the selected location.
    # The old matcher discarded the dollar sign; quantities extracted with
    # table headers/scale are required to support those monetary assertions.
    "Q05": {"mark_mismatch": 8},
    "Q06": {"id_in_prose": 1},
    "Q09": {"period_mismatch": 1},
    "Q11": {"superlative_without_rank": 1},
    "Q12": {"period_mismatch": 1},
}


def _answers() -> list[dict]:
    if not CORPUS.exists():
        pytest.skip(f"{CORPUS.name} not built; scripts/v37_corpus.py makes it from a round + its db")
    return json.loads(gzip.decompress(CORPUS.read_bytes()))["answers"]


def _verdicts() -> dict[str, object]:
    """The check's verdict on every accepted answer, by question tag."""
    return {a["tag"][:3]: answer_check.check(a["text"], Ledger.of(a["facts"]), question=a["question"])
            for a in _answers()}


def test_the_corpus_reproduces_the_round_apart_from_the_rules_added_since():
    """The one assertion that makes everything else in this file evidence.

    Fifteen answers round B accepted; the check that accepted them still accepts
    them, apart from the refusals named above. A failure here is one of three
    things: the ledger was rebuilt differently from the way the check read it, a
    new rule is wider than its author thought, or a rule was added without its
    effect being written down."""
    assert len(_answers()) == 15, "round B accepted fifteen"
    got = {tag: dict(collections.Counter(p["reason"] for p in v.problems))
           for tag, v in _verdicts().items()}
    assert {tag: r for tag, r in got.items() if r} == ADDED_SINCE_THE_ROUND


def test_a_refused_period_says_what_the_readings_are():
    """The analyst is told what it has, not only that it is wrong: a sentence
    saying "twelve quarters" over five annual points cannot be fixed by rewording
    alone, and the way out is either the period the desk showed or a request for
    the series the question asked for."""
    [p] = [p for p in _verdicts()["Q04"].problems if p["reason"] == "period_mismatch"]
    assert p["word"] == "twelve quarters"
    assert "5 annual reading(s)" in p["holds"] and "2021-12-31..2025-12-31" in p["holds"]
    assert "request the series the question asked for" in p["way_out"]


def test_a_refused_superlative_says_where_the_subject_actually_sits():
    """Which ordering a figure-less sentence means is exactly what it does not
    say, so the refusal names the places the subject DOES hold rather than
    guessing who is at the end — the first draft of this rule offered
    `daily_loss` as the answer to "closest to its issuer-concentration warning"."""
    [p] = [p for p in _verdicts()["Q11"].problems if p["reason"] == "superlative_without_rank"]
    assert p["word"] == "closest"
    assert "19 of 20" in p["way_out"] and "8 of 20" in p["way_out"]
    assert "Point at the figure whose place you mean" in p["way_out"]
    assert all(str(c["subject"]).endswith("LLY") for c in p["candidates"]), "its own places, not somebody else's"
