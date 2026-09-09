#!/usr/bin/env python3
"""Figure recall: the SHARE of a turn's `must` gold figures the answer rendered.

`figures_present` in rubric_battery is all-or-nothing, which saturates on the V26
set where a turn asks for as many as thirteen must-figures: one miss and the turn
scores zero, so the criterion cannot see an arm improve from two-of-thirteen to
ten-of-thirteen. This reads the same files and the same value matching (relative
tolerance, never names) and reports the fraction. It changes no stored score.

    scripts/v30_figure_recall.py docs/spikes/v30/V26_R2.json v26 [more.json set ...]
"""
from __future__ import annotations
import json, sys
from pathlib import Path

TOL = 0.005


def rendered_values(turn: dict) -> list[float]:
    out = []
    for m in ((turn.get("meta") or {}).get("verified") or {}).get("matches") or []:
        v = m.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
    return out


def recall(path: str, gold_set: str) -> dict:
    gold = json.loads(Path(f"tests/battery/gold_{gold_set}.json").read_text())
    convs = json.loads(Path(path).read_text())
    hit = tot = turns = full = 0
    for c in convs:
        for t in c.get("turns", []):
            g = gold.get(f"{c['tag']}#t{t['turn']}")
            if not g:
                continue
            musts = [f for f in g.get("figures", []) if f.get("must", True)]
            if not musts:
                continue
            vals = rendered_values(t)
            got = sum(1 for f in musts
                      if any(abs(r - float(f["value"])) <= TOL * max(1.0, abs(float(f["value"]))) for r in vals))
            hit += got; tot += len(musts); turns += 1
            full += (got == len(musts))
    return {"file": Path(path).stem, "turns_scored": turns, "must_figures": tot,
            "rendered": hit, "recall": round(hit / tot, 3) if tot else 0.0,
            "turns_complete": full, "turns_complete_share": round(full / turns, 3) if turns else 0.0}


if __name__ == "__main__":
    args = sys.argv[1:]
    rows = [recall(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    w = max(len(r["file"]) for r in rows)
    print(f"{'round':<{w}}  recall  must  rendered  turns  all-present")
    for r in rows:
        print(f"{r['file']:<{w}}  {r['recall']:>6.1%}  {r['must_figures']:>4}  {r['rendered']:>8}  "
              f"{r['turns_scored']:>5}  {r['turns_complete']:>3}/{r['turns_scored']} ({r['turns_complete_share']:.0%})")
