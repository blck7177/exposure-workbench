"""V3-D2 — faithfulness of the corpus this system has already produced (live).

Run with:  pytest -m live -k eval_faithfulness

Replays what is in the database rather than generating fresh answers, and that
is the design rather than a shortcut: an answer produced after A1 has by
construction already passed A1, so it can only score 100% and measures nothing.
The pre-A1 text is the only sample that can say what the new rules refuse.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live

# The thirteen refusals across three pre-V3 briefs, classified by reading each
# one. Four are the derived-Q4 class, which A1c closed for anything written
# afterwards but cannot retrofit onto text already stored. One is a genuine
# design refusal — a brief writes 32.2% where the true operating margin is
# 32.2753%, i.e. truncation rather than rounding, and the rule is that the true
# value must ROUND to what was written. The remaining eight are true catches:
# figures cited to a block that does not contain them.
BRIEF_REFUSAL_CEILING = 13


async def test_no_answer_states_a_number_without_citing_anything():
    """A0-1's invariant, checked against the whole corpus rather than one path.
    Must be exactly zero: this is the hole where an answer made entirely of
    numbers passed the gate untouched."""
    from scripts.eval_faithfulness import evaluate

    r = await evaluate()
    assert r["chat"]["number_bearing_uncited"] == 0


async def test_every_citation_still_resolves():
    """The gate guarantees this at WRITE time. Checked here at read time, which
    is a different claim: the four evidence stores are append-only, so a citation
    that stopped resolving would mean that promise had been broken somewhere."""
    from scripts.eval_faithfulness import evaluate

    r = await evaluate()
    assert r["chat"]["dangling_citations"] == 0
    assert r["briefs"]["dangling_citations"] == 0
    assert r["chat"]["citations"] + r["briefs"]["citations"] > 100, "expected a real corpus"


async def test_chat_answers_verify_completely():
    """Measured at 0 of 20 when V3 shipped, against a plan bar of 2 in 20."""
    from scripts.eval_faithfulness import evaluate

    r = await evaluate()
    assert r["chat"]["numbers"] >= 15, "expected a meaningful number of stated figures"
    assert r["chat"]["unverified"] == 0


async def test_brief_refusals_stay_within_the_classified_set():
    """Not a pass/fail on quality — a ratchet on a known, enumerated list. Every
    one of the thirteen has been read and classified (see the module constant).
    A fourteenth means either a new defect or a change to the rules, and both are
    things to look at rather than absorb."""
    from scripts.eval_faithfulness import evaluate

    r = await evaluate()
    assert r["briefs"]["unverified"] <= BRIEF_REFUSAL_CEILING, (
        f"{r['briefs']['unverified']} refusals across the stored briefs, above the "
        f"classified {BRIEF_REFUSAL_CEILING}; read the new one before raising this"
    )
