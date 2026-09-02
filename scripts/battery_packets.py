#!/usr/bin/env python3
"""Turn an agent_battery.py run into one grading packet per question.

A packet is everything a grader needs to decide what the desk actually did,
with nothing it would have to reconstruct: the prose it wrote, every slot with
the ref/name/value the ledger resolved, the tool calls in order, every gate
refusal in order, and the session id so the grader can go read calc_ledger.

Not a scorer. Scoring a battery is a judgement about whether a sentence means
what the numbers under it say, and that is the one thing this file must not
pretend to automate — it lays the evidence out and stops.

    python scripts/battery_packets.py docs/spikes/R20.json out_dir/ [questions.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _slots(node, out: list) -> None:
    """Every slot in a rendered block tree, in reading order."""
    if isinstance(node, dict):
        if "slot" in node and isinstance(node["slot"], dict):
            out.append(node["slot"])
            return
        for v in node.values():
            _slots(v, out)
    elif isinstance(node, list):
        for v in node:
            _slots(v, out)


def _prose(node, out: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("text", "title") and isinstance(v, str):
                out.append(v)
            else:
                _prose(v, out)
    elif isinstance(node, list):
        for v in node:
            _prose(v, out)
    elif isinstance(node, str):
        out.append(node)


def packet(r: dict, design: dict | None) -> dict:
    steps = r.get("steps") or []
    blocks = (r.get("meta") or {}).get("blocks") or []

    slots: list = []
    _slots(blocks, slots)

    calls = [{"seq": s["seq"], "tool": s["tool_name"], "status": s["status"],
              "args": s.get("args"), "result": (s.get("result") or "")[:180]}
             for s in steps if s.get("step_type") in ("tool_call", "delegation")
             and s.get("tool_name")]

    refusals = [{"seq": s["seq"], "result": (s.get("result") or "")[:400],
                 "attempted": (s.get("args") or "")[:900]}
                for s in steps if s.get("step_type") == "respond"
                and "error" in (s.get("result") or "")]

    block_shapes = [{"type": b.get("type"), "cites": b.get("cites", [])}
                    for b in blocks if isinstance(b, dict)]

    prose: list = []
    _prose([{k: v for k, v in b.items() if k != "cites"} for b in blocks
            if isinstance(b, dict)], prose)

    return {
        "tag": r["tag"],
        "question": r["question"],
        "session_id": r["session_id"],
        "elapsed_s": r.get("elapsed_s"),
        "error": r.get("error"),
        "design": design or {},
        "answer_text": r.get("answer"),
        "prose_runs": [p for p in prose if isinstance(p, str) and p.strip()],
        "slots": slots,
        "block_shapes": block_shapes,
        "citations": r.get("citations", []),
        "tool_calls": calls,
        "n_calls": len(calls),
        "gate_refusals": refusals,
        "n_refusals": len(refusals),
        "prompt_peak": (r.get("meta") or {}).get("prompt_tokens"),
        "gate_exhausted": (r.get("meta") or {}).get("gate") == "exhausted",
    }


def main(argv: list[str]) -> int:
    results = json.load(open(argv[0]))
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    design = {}
    if len(argv) > 2:
        for q in json.load(open(argv[2])):
            design[q["tag"]] = q

    index = []
    for r in results:
        p = packet(r, design.get(r["tag"]))
        (out / f"{p['tag']}.json").write_text(json.dumps(p, indent=1, default=str))
        index.append({"tag": p["tag"], "calls": p["n_calls"], "refusals": p["n_refusals"],
                      "slots": len(p["slots"]), "exhausted": p["gate_exhausted"],
                      "head": (p["answer_text"] or "")[:90].replace("\n", " ")})
    (out / "_index.json").write_text(json.dumps(index, indent=1))
    for row in index:
        print(f"{row['tag']:34s} calls={row['calls']:3d} refusals={row['refusals']} "
              f"slots={row['slots']:3d}  {row['head']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
