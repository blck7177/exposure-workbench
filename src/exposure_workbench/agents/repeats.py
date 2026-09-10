"""V31. An exit re-sent unchanged after a refusal is not a second attempt.

THE CLASS THIS ENDS. The gate is not a negotiation. Given the same claims and
the same prose it returns the same refusal, and it costs a provider round trip
to say so again. Three turns of the V26 baseline (`docs/spikes/v29/V26_R2.json`)
sent one byte-identical `respond` EIGHT times and ended on the gate-exhausted
text — the reader told the desk could not answer, on turns where it could:

  W01-xom-maturity-wall t2   "is that fixed or floating" — answered correctly
                             and with the filing cited at attempt 1, refused
                             `unsourced_figure` eight times for the digits in
                             the prose. 17.3k → 24.7k prompt tokens.
  NEW06-what-you-havent-got t2   `id_in_prose` and `not_on_ledger` alternating
                             over one sentence that wrote both the id AND the
                             number. Eight attempts, unchanged.
  FQ04-their-story-against-my-line t3   eight.

Across the 140 turns, `respond` is called 284 times and refused 143; 134 of
those 143 are about how a figure was WRITTEN rather than whether it is true.
The model that re-sends has, on the evidence, not read `problems` — where the
gate already names the token and its place. So the first repeat says so, in
the desk's own words, with the tokens on the line; and the second ends the
turn, because a third identical payload has never once been the one that
passed and the budget it spends belongs to the next question.

WHAT IS NOT DONE HERE. Nothing is accepted that the gate refused, and no
refusal is softened: an exhausted turn ends exactly where it ended before, on
the same text, having spent less. A payload that CHANGED goes out unhindered
however many times it is sent — the bound is on repetition, never on effort.
"""

from __future__ import annotations

import hashlib
import json

# The repeat that ends the turn. 1 = tell the model it repeated itself; 2 = stop.
# Two rather than one because the first repeat has never been told it is one,
# and a nudge naming the tokens is the cheapest thing this desk can try.
STOP = 2


def digest(args: dict) -> str:
    """The payload, as the model sent it. `sort_keys` so a re-serialisation in a
    different key order is still the same answer — the gate reads the values."""
    try:
        return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
    except (TypeError, ValueError):  # noqa: BLE001 — an unhashable payload is simply never a repeat
        return ""


def where(result: dict) -> str:
    """The tokens the gate named, one line. `problems` carries `at` (which
    paragraph or claim) and the offending `figure` / `id` / `relation`; the
    model is handed them again because the evidence is that it did not read
    them the first time."""
    problems = result.get("problems")
    if not isinstance(problems, list):
        return ""
    bits = []
    for p in problems[:6]:
        if not isinstance(p, dict):
            continue
        what = p.get("figure") or p.get("id") or p.get("quote") or p.get("relation")
        at, reason = p.get("at"), p.get("reason")
        one = f"{at} {reason}" if at else str(reason or "")
        if what:
            one += f" ({what!r})"
        bits.append(one)
    return "; ".join(b for b in bits if b.strip())


def nudge(name: str, result: dict) -> str:
    """What the model is told on its first repeat: that it repeated itself, that
    the gate will not move, and exactly which tokens it named."""
    named = where(result)
    return (
        f"That {name} call was byte-identical to the one refused before it, and the gate "
        f"returned the same {result.get('error')!r}. It does not change its mind: sent a third "
        f"time it is refused a third time. "
        + (f"What it named: {named}. " if named else "")
        + "Change those, or drop the figure and say it in prose the ledger can account for."
    )


class Repeats:
    """Per-turn memory of the exit payloads this turn has already been refused.

    Constructed inside a turn, so nothing leaks between turns: a model that
    fixes its evidence and re-sends the same wording next turn is asking a
    question that has changed, and it goes out.
    """

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def record(self, args: dict) -> int:
        """Count this refused payload; return how many times it has now been
        refused. 1 is the first refusal (not a repeat), 2 the first repeat."""
        key = digest(args)
        if not key:
            return 1
        self._seen[key] = self._seen.get(key, 0) + 1
        return self._seen[key]

    def repeats_of(self, args: dict) -> int:
        """How many REPEATS this payload has had: 0 on its first refusal."""
        return max(0, self._seen.get(digest(args), 0) - 1)
