"""The one fact boundary (V2 P5, design v0.4 §10): every sentence a model writes
about a figure goes through this function, whatever channel it arrives in.

WHY THIS EXISTS. The check was always one function (services/answer_check.check),
but it was called from five places under five names — the lead's reply, an
analyst's finding, a caveat, an unsettled line's why, a follow-up, and now a
state proposal — and a rule that has to hold across all of them ("moving a
figure from a finding into a caveat changes nothing", acceptance A2) had no
single place to be stated or tested. This module is that place: `check_text`
is the boundary, `CHANNELS` is the closed list of ways a sentence reaches it,
and tests/test_v2_boundary_channels pins that the verdict does not depend on
the channel.

WHAT IT IS NOT. Not a second validator, not a wrapper that adds a rule: it is
answer_check.check with the channel written on the problems it returns. A
sentence a model writes that is not in one of these channels does not reach the
record at all.
"""

from __future__ import annotations

from exposure_workbench.services import answer_check
from exposure_workbench.services.ledger import Ledger

# Every way a model's sentence about a figure reaches the desk's record.
CHANNELS: tuple[str, ...] = ("answer", "finding", "caveat", "why", "follow_up", "state_proposal")


def check_text(channel: str, text: str, ledger: Ledger, question: str | None = None) -> answer_check.Verdict:
    """The boundary. `channel` labels the problems (`where`, unless the caller has
    already placed them more precisely) and must be one of CHANNELS — a new way
    for a model's sentence to reach the record is a decision taken here, once."""
    if channel not in CHANNELS:
        raise ValueError(f"{channel!r} is not a channel a model's sentence reaches the record through: {CHANNELS}")
    verdict = answer_check.check(text or "", ledger, question=question)
    for p in verdict.problems:
        p.setdefault("where", channel)
        p.setdefault("channel", channel)
    return verdict
