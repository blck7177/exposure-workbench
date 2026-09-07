#!/usr/bin/env python3
"""Turn the research workflow's verified question set into the two files the
runners read, and refuse anything the battery cannot score.

Input: a JSON array of designed conversations, each
    {tag, note, domain, turns: [...], criteria_per_turn: [[...], ...],
     expected_shape, trap}

Output:
    <out>/conversations_v26.json   -> scripts/conversation_battery.py
    <out>/criteria_v26.json        -> scripts/rubric_battery.py
    <out>/DESIGN_v26.json          -> expected_shape and trap, kept beside the run

Refusals, applied here rather than discovered at scoring time:
  * a criterion not in the rubric's closed vocabulary
  * `follows_on` on a first turn (nothing to follow on from)
  * a turn with no criteria at all
  * a duplicate tag
  * a tag that collides with the existing V21/V24 batteries

    python scripts/v26_assemble_battery.py designed.json --out tests/battery
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The rubric's closed vocabulary (scripts/rubric_battery.py). Structural criteria
# are not assigned per question here; only the semantic ones are.
SEMANTIC = {"ranking", "netting", "trigger", "so_what", "grounded_claims",
            "honest_absence", "follows_on", "precision"}
STRUCTURAL = {"read_required_inputs", "no_linear_locating"}
VOCAB = SEMANTIC | STRUCTURAL

TAG_RX = re.compile(r"^[A-Za-z][A-Za-z0-9]*-[a-z0-9-]+$")


def _existing_tags(battery_dir: Path) -> set[str]:
    tags: set[str] = set()
    for name in ("conversations_v21.json", "conversations_v24.json"):
        p = battery_dir / name
        if p.exists():
            tags |= {c["tag"] for c in json.load(open(p))}
    return tags


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("designed")
    ap.add_argument("--out", default="tests/battery")
    ap.add_argument("--prefix", default="W", help="tag prefix for this batch")
    args = ap.parse_args(argv)

    out_dir = ROOT / args.out
    designed = json.load(open(args.designed))
    if isinstance(designed, dict):
        designed = designed.get("final_set") or designed.get("conversations") or []

    taken = _existing_tags(out_dir)
    convos, criteria, design, dropped = [], [], [], []
    seen: set[str] = set()

    for i, c in enumerate(designed, 1):
        tag = str(c.get("tag") or "").strip()
        turns = [str(t).strip() for t in (c.get("turns") or []) if str(t).strip()]
        per = c.get("criteria_per_turn") or []
        why = []

        if not tag or not TAG_RX.match(tag):
            tag = f"{args.prefix}{i:02d}-{re.sub(r'[^a-z0-9]+', '-', str(c.get('domain') or 'question').lower()).strip('-')[:28]}"
        if tag in seen or tag in taken:
            tag = f"{tag}-{i:02d}"
        if not turns:
            why.append("no turns")
        if len(per) != len(turns):
            why.append(f"criteria_per_turn has {len(per)} entries for {len(turns)} turns")
        for j, cs in enumerate(per[:len(turns)], 1):
            bad = [x for x in (cs or []) if x not in VOCAB]
            if bad:
                why.append(f"t{j}: criteria outside the vocabulary: {bad}")
            if not (cs or []):
                why.append(f"t{j}: no criteria")
            if j == 1 and "follows_on" in (cs or []):
                why.append("t1 carries follows_on, which needs a previous turn")

        if why:
            dropped.append({"tag": tag, "why": why, "conversation": c})
            continue

        seen.add(tag)
        convos.append({"tag": tag, "note": c.get("note") or c.get("domain") or "", "turns": turns})
        for j, (q, cs) in enumerate(zip(turns, per), 1):
            criteria.append({"tag": f"{tag}#t{j}", "q": q,
                             "asks": (c.get("expected_shape") or "")[:160],
                             "criteria": sorted(set(cs))})
        design.append({"tag": tag, "domain": c.get("domain"), "note": c.get("note"),
                       "expected_shape": c.get("expected_shape"), "trap": c.get("trap"),
                       "turns": turns, "criteria_per_turn": per})

    out_dir.mkdir(parents=True, exist_ok=True)
    json.dump(convos, open(out_dir / "conversations_v26.json", "w"), indent=1, ensure_ascii=False)
    json.dump(criteria, open(out_dir / "criteria_v26.json", "w"), indent=1, ensure_ascii=False)
    json.dump(design, open(ROOT / "docs/spikes/v26/DESIGN_v26.json", "w"), indent=1, ensure_ascii=False)

    print(f"kept    {len(convos)} conversations, {len(criteria)} turns")
    print(f"dropped {len(dropped)}")
    for d in dropped:
        print(f"  {d['tag']}: {'; '.join(d['why'])}")
    from collections import Counter
    print("\ncriteria coverage across the batch:")
    for k, v in Counter(x for c in criteria for x in c["criteria"]).most_common():
        print(f"  {k:18} {v}")
    print("\ndomains:")
    for k, v in Counter(d.get("domain") or "?" for d in design).most_common():
        print(f"  {k:36} {v}")
    print(f"\nwritten {out_dir/'conversations_v26.json'} and {out_dir/'criteria_v26.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
