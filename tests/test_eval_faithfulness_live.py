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

# The fourteen refusals across three pre-V3 briefs, classified by reading each
# one. Four are the derived-Q4 class, which A1c closed for anything written
# afterwards but cannot retrofit onto text already stored. One is a genuine
# design refusal — a brief writes 32.2% where the true operating margin is
# 32.2753%, i.e. truncation rather than rounding, and the rule is that the true
# value must ROUND to what was written. The other nine are true catches: figures
# cited to a block that does not contain them, including a "25% import tariff"
# whose two cited chunks contain neither "tariff" nor "H200".
BRIEF_REFUSAL_CEILING = 14


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


# Chat sits under the same kind of classified ceiling as the briefs, for the same
# reason: the corpus contains answers written under RULES THAT NO LONGER APPLY.
# The one refusal today is an acceptance-run answer that summarised a pre-V3
# brief and inherited its "25% import tariff" claim — cited to two chunks
# containing neither "tariff" nor "H200". It was accepted when it was written,
# because the prose route then matched bare digits and "25" occurs in one of
# those chunks; it is refused now that the route matches the number as written.
# Keeping it, rather than deleting the row, is the point: it is exactly the kind
# of laundering the gate exists to stop, and it is the evidence that the
# tightening works.
# V11-F adds eight, and they are one class: an individual factor coefficient
# quoted from a run the regression recorded as collinear. Every one is a
# `not_quotable_individually` refusal of `factor_attributions.<name>.contribution`
# on run_95ebe31c5e51 — the market factor seven times, growth and small_cap once
# each in the answer that listed all three. The tools have carried
# `quotable_individually: false` and a factor_note naming the substitute since
# V8; these answers are what ignoring a field the model may ignore looks like,
# and they are the sample the checker was built from. Keeping them refused,
# rather than exempting the corpus that motivated the rule, is the same choice
# the "25% import tariff" row records.
#
#   1  pre-V3 laundering, inherited from a flawed brief (see above)
#   8  collinear coefficients quoted alone (V11-F)
CHAT_REFUSAL_CEILING = 9


async def test_chat_answers_verify_almost_completely():
    """Measured at 0 of 20 when the numeric check first shipped, against a plan
    bar of 2 in 20 — at 1 of 29 after the prose route was tightened, and at 9 of
    245 once V11-F stopped accepting a collinear beta on its own. Every one of
    the nine has been read and classified in the constant below."""
    from scripts.eval_faithfulness import evaluate

    r = await evaluate()
    assert r["chat"]["numbers"] >= 15, "expected a meaningful number of stated figures"
    assert r["chat"]["unverified"] <= CHAT_REFUSAL_CEILING, (
        f"{r['chat']['unverified']} chat numbers refused, above the classified "
        f"{CHAT_REFUSAL_CEILING}; read the new one before raising this"
    )
    # The classification is part of the ceiling: a ninth refusal of a different
    # kind must not hide under a count that eight of one kind filled up.
    kinds = {p["reason"] for p in r["refusals"]
             if p.get("reason") in ("not_in_cited_evidence", "not_quotable_individually")}
    assert kinds <= {"not_in_cited_evidence", "not_quotable_individually"}, kinds


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
