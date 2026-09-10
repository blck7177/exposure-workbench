#!/usr/bin/env python3
"""What G4 would have refused, on rounds already run (V32).

    python scripts/v32_estimate.py docs/spikes/v30/V26_C3.json …

G4 (services/claims._paragraph_problems) refuses a sentence that orders a figure
with no rank claim, and one that states a single quantity twice. Both are new, so
before a live round costs anything this reads the ACCEPTED answers of rounds
already on disk and reports how many sentences the rule would have caught.

WHAT THIS IS AND IS NOT. The traces carry each accepted answer's text and its
`meta.verified.matches` in full, and nothing else of the payload: `args` is
stored to 300 characters, and 377 of C3's 378 respond payloads begin `{"prose":`,
so the CLAIMS are not on disk and `claims.check` cannot be replayed. Two
consequences, both stated rather than smoothed:

  * "is any claim in this sentence a rank" cannot be read; the estimate assumes
    NONE is, which is the upper bound. The desk's own counter says 15 of 52
    superlative turns wrote a rank/top node somewhere, so the true figure is
    lower.
  * "is this figure an entry of a node with siblings" needs `params.node`, which
    `matches` does not carry. Approximated by two or more cited figures sharing a
    measure — the same set an ordering would order.

So this bounds the change; it does not measure it. The round measures it.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exposure_workbench.services.claims import ORDERING_WORDS, sentences_of  # noqa: E402


def _renderings(value, unit: str | None) -> list[str]:
    """A few spellings one figure can wear in a stored answer. Approximate on
    purpose: the estimate needs to know whether the sentence STATES the figure,
    and the server's own formatter is in the web bundle."""
    if not isinstance(value, (int, float)):
        return []
    out = []
    if (unit or "").upper() in ("RATIO", "PERCENT"):
        for d in (1, 2):
            out.append(f"{value * 100:.{d}f}%")
    for d in (1, 2, 3, 4):
        out.append(f"{value:.{d}f}")
    if abs(value) >= 1e9:
        out.append(f"{value / 1e9:.1f}")
    elif abs(value) >= 1e6:
        out.append(f"{value / 1e6:.1f}")
    return out


def _two_of_one_measure(sent: str, matches: list) -> bool:
    """Whether the sentence states two or more figures of ONE measure — the
    gate's condition, counted from the values the stored answer renders."""
    per: dict = collections.defaultdict(set)
    for m in matches:
        if any(r in sent for r in _renderings(m.get("value"), m.get("unit_class"))):
            per[m.get("label")].add(m.get("source_id"))
    return any(len(v) > 1 for v in per.values())


def _report(path: str) -> None:
    rounds = json.load(open(path))
    turns = accepted = ordering_hits = twice_hits = 0
    examples: list[str] = []
    for conv in rounds:
        for t in conv.get("turns", []):
            turns += 1
            answer = t.get("answer") or ""
            if not answer or answer.startswith("I could not produce"):
                continue
            accepted += 1
            matches = (t.get("meta") or {}).get("verified", {}).get("matches") or []
            # a value stated by two cited figures of one measure — the shape of
            # "8.76%, down from 8.76%"
            seen: dict[tuple, int] = collections.Counter()
            for m in matches:
                seen[(m.get("label"), m.get("as_of"), m.get("value"))] += 1
            if any(n > 1 for n in seen.values()):
                twice_hits += 1

            for sent in sentences_of(answer):
                # the gate's rule: TWO OR MORE cited figures of one measure in
                # this sentence, and an ordering word. Placeholders are resolved
                # in the stored answer, so the count is of figures the sentence
                # states, which is what the rule counts.
                if ORDERING_WORDS.search(sent) and _two_of_one_measure(sent, matches):
                    ordering_hits += 1
                    if len(examples) < 4:
                        examples.append(f"    {conv['tag']} t{t.get('turn')}: …{sent.strip()[:110]}…")
                    break

    name = Path(path).stem
    print(f"\n===== {name}: {turns} turns, {accepted} accepted answers")
    print(f"  sentences ordering 2+ readings of one measure           : {ordering_hits}"
          f"  ({ordering_hits / accepted:.0%} of accepted answers)")
    print(f"  answers citing one quantity at one period twice        : {twice_hits}")
    for e in examples:
        print(e)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for path in argv:
        _report(path)
    print("\nUpper bound: the claims are not on disk, so a rank claim already present "
          "cannot be seen. See this file's docstring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
