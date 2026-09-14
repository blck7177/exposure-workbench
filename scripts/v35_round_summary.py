#!/usr/bin/env python3
"""One round of the 20-question battery as the six-round table reads it
(docs/spikes/v33/ACCEPTANCE_V33.md §12): answered, refusals, type_errors, writer
completions, prompt median, and how the second attempts went.

    python scripts/v35_round_summary.py docs/spikes/v33/V33H.json [more.json]
"""
from __future__ import annotations

import collections
import json
import statistics
import sys


def _j(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:  # noqa: BLE001
            return {"_raw": x}
    return x or {}


def summarise(path: str) -> dict:
    data = json.load(open(path))
    turns = [t for c in data for t in c["turns"]]
    metas = [_j(t.get("meta")) for t in turns]
    answered = sum(1 for m in metas if "gate" not in m)
    refusals = collections.Counter(r for m in metas for r in (m.get("gate_refusals") or []))
    type_errors = 0
    writer = sum(int(m.get("writer_calls") or 0) for m in metas)
    prompts = [int(m.get("prompt_tokens") or 0) for m in metas if m.get("prompt_tokens")]
    requests = sum(int(m.get("requests") or 0) for m in metas)
    second: collections.Counter = collections.Counter()
    repairs = 0
    for t in turns:
        steps = t.get("steps") or []
        answers = [s for s in steps if s.get("step_type") == "answer"]
        for s in steps:
            if s.get("step_type") == "tool_call" and "type_errors" in str(s.get("result") or ""):
                type_errors += 1
            if s.get("step_type") == "llm_call" and "repair_answer" in str(s.get("result") or ""):
                repairs += 1
        if len(answers) >= 2:
            a, b = (_j(answers[0].get("args")).get("text") or ""), (_j(answers[1].get("args")).get("text") or "")
            second["identical" if a.strip() == b.strip() else "changed"] += 1
    return {"file": path, "answered": f"{answered}/{len(turns)}", "gate_refusals": sum(refusals.values()),
            "by_reason": dict(refusals.most_common()), "type_errors": type_errors, "writer_completions": writer,
            "requests": requests, "prompt_median": statistics.median(prompts) if prompts else None,
            "second_attempts": dict(second), "repair_tool_calls": repairs}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(summarise(p), ensure_ascii=False, indent=1))
