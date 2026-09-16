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


def test_the_corpus_reproduces_the_round_it_was_taken_from():
    """Fifteen answers round B accepted, accepted again offline. If this fails,
    nothing else in this file is evidence about anything: either the ledger was
    rebuilt differently from the way the check read it, or a rule changed without
    its effect being written down."""
    answers = _answers()
    assert len(answers) == 15, "round B accepted fifteen"
    refused = {tag: v.error for tag, v in _verdicts().items() if not v.ok}
    assert refused == {}, "the check that accepted these still accepts them"
