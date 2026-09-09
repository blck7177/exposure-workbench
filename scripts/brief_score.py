#!/usr/bin/env python3
"""Score a brief battery: what the briefs rendered, against what the desk holds.

    python scripts/brief_score.py docs/spikes/v31/BRIEF_R1.json [more.json …]

Two things, kept apart because they answer different questions.

COST AND FRICTION, from the battery's own counters — tool calls, prompt tokens,
submit attempts, and which SECTION each gate refusal named. The sections are
checked in order and the first refusal returns, so a brief wrong in section six
is refused six times while the model walks forward; reading attempts without the
section names would call that model incompetence when it is the order of the
check.

RECALL, against tests/battery/gold_brief.json — the figures the desk's own seven
issuer domains produce for that issuer, matched by VALUE at a relative
tolerance, never by name. This is a denominator, not a checklist: a brief is six
sections and an analyst chooses, so 40% is not 60% wrong. The number is
comparable between arms of the same battery and means nothing on its own.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests" / "battery" / "gold_brief.json"
TOL = 0.005
SECTIONS = ("financial_summary", "key_changes", "management_explanation",
            "market_context", "portfolio_implications", "open_questions")


def _values(blocks) -> list[float]:
    """Every figure a rendered section shows the reader."""
    out: list[float] = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("fact"), dict):
                v = node["fact"].get("value")
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out.append(float(v))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(blocks)
    return out


def _hit(v: float, gold: list[float]) -> bool:
    return any(abs(v - g) <= TOL * max(1.0, abs(g)) for g in gold)


def score(path: str, gold: dict) -> dict:
    briefs = json.loads(Path(path).read_text())
    rows, per_section = [], {s: [0, 0] for s in SECTIONS}
    for b in briefs:
        g = gold.get(b["ticker"], {})
        gold_values = list((g.get("figures") or {}).values())
        blocks = ((b.get("brief") or {}).get("blocks")) or {}
        rendered, matched = 0, 0
        for name in SECTIONS:
            vals = _values(blocks.get(name))
            hits = sum(1 for v in vals if _hit(v, gold_values))
            per_section[name][0] += hits
            per_section[name][1] += len(vals)
            rendered += len(vals)
            matched += hits
        c = b.get("counts") or {}
        rows.append({
            "ticker": b["ticker"], "submitted": b.get("submitted"),
            "tool_calls": c.get("tool_calls", 0), "prompt_tokens": c.get("prompt_tokens", 0),
            "submit_attempts": c.get("submit_attempts", 0), "gate_refusals": c.get("gate_refusals", 0),
            "sections_refused": c.get("sections_refused", []),
            "rendered": rendered, "in_gold": matched,
            "gold_figures": len(gold_values),
            "gold_recall": round(matched / len(gold_values), 3) if gold_values else 0.0,
        })
    return {"file": Path(path).stem, "briefs": rows, "per_section": per_section}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip().splitlines()[2].strip()); return 2
    gold = json.loads(GOLD.read_text()) if GOLD.exists() else {}
    if not gold:
        print(f"no gold at {GOLD.relative_to(ROOT)} — run scripts/gold_brief.py first"); return 2
    reports = [score(p, gold) for p in argv]
    for rep in reports:
        print(f"\n=== {rep['file']}")
        print(f"{'issuer':<8}{'ok':>4}{'calls':>7}{'tokens':>10}{'submits':>9}{'refused':>9}"
              f"{'shown':>7}{'in gold':>9}{'recall':>8}  sections refused")
        for r in rep["briefs"]:
            print(f"{r['ticker']:<8}{'y' if r['submitted'] else 'n':>4}{r['tool_calls']:>7}"
                  f"{r['prompt_tokens']:>10,}{r['submit_attempts']:>9}{r['gate_refusals']:>9}"
                  f"{r['rendered']:>7}{r['in_gold']:>9}{r['gold_recall']:>8.1%}  "
                  f"{','.join(r['sections_refused']) or '-'}")
        ok = [r for r in rep["briefs"] if r["submitted"]]
        if ok:
            print(f"{'MEDIAN':<8}{'':>4}{statistics.median(r['tool_calls'] for r in ok):>7.0f}"
                  f"{statistics.median(r['prompt_tokens'] for r in ok):>10,.0f}"
                  f"{statistics.median(r['submit_attempts'] for r in ok):>9.0f}"
                  f"{statistics.median(r['gate_refusals'] for r in ok):>9.0f}"
                  f"{statistics.median(r['rendered'] for r in ok):>7.0f}"
                  f"{statistics.median(r['in_gold'] for r in ok):>9.0f}"
                  f"{statistics.mean(r['gold_recall'] for r in ok):>8.1%}")
        print("\n  figures shown per section (in gold / shown):")
        for name, (hit, tot) in rep["per_section"].items():
            print(f"    {name:<26}{hit:>5} / {tot:<5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
