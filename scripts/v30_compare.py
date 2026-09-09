#!/usr/bin/env python3
"""V30 — one table over the scored battery outputs (scripts/v30_score.sh).

    python scripts/v30_compare.py docs/spikes/v30/V24_R1.json docs/spikes/v30/V24_B1.json …
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROWS = [("turns", "counters", "turns"), ("no answer", "counters", "no_answer"), ("gate exhausted", "counters", "gate_exhausted"),
        ("round trips p50", "counters", "round_trips_median"), ("tool calls p50", "counters", "tool_calls_median"),
        ("respond attempts", "counters", "respond_attempts_mean"), ("prompt tokens p50", "counters", "prompt_tokens_median"),
        ("elapsed s p50", "counters", "elapsed_s_median"),
        ("spelling refusals/turn", "refusal", "spelling"), ("gate refusals/turn", "refusal", "gate"),
        ("algebra refusals/turn", "refusal", "algebra"), ("data refusals/turn", "refusal", "data"),
        ("double-figure artifacts", "counters", "answers_with_double_figure_artifact"),
        ("passage mark as figure", "counters", "answers_with_passage_mark_as_figure"),
        ("superlatives w/o rank", "counters", "superlative_without_rank"),
        ("figures_present", "struct", "figures_present"),
        ("so_what", "judged", "so_what"), ("follows_on", "judged", "follows_on"), ("honest_absence", "judged", "honest_absence")]


def load(p: Path) -> dict:
    base = str(p)[:-5]
    out = {}
    for k in ("counters", "struct", "judged"):
        f = Path(f"{base}_{k}.json")
        out[k] = json.loads(f.read_text()) if f.exists() else {}
    return out


def cell(d: dict, kind: str, key: str) -> str:
    if kind == "counters":
        v = d["counters"].get(key)
        return "" if v is None else (f"{v:g}" if isinstance(v, (int, float)) else str(v))
    if kind == "refusal":
        r = (d["counters"].get("refusals") or {}).get(key)
        return f"{r['per_turn']:.2f}" if r else "0"
    if kind in ("struct", "judged"):
        bc = (d[kind].get("by_criterion") or {}).get(key)
        return f"{bc[0]}/{bc[1]}" if bc else ""
    return ""


def main(paths: list[str]) -> int:
    data = {Path(p).stem: load(Path(p)) for p in paths}
    names = list(data)
    print("| metric | " + " | ".join(names) + " |")
    print("|---|" + "---|" * len(names))
    for label, kind, key in ROWS:
        print(f"| {label} | " + " | ".join(cell(data[n], kind, key) for n in names) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
