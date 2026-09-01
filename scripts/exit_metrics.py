#!/usr/bin/env python3
"""The exit, measured (V15-S7): what the gate did on a set of battery sessions.

The V15 plan's switch criteria are about the EXIT, not the answers — how many
respond attempts a turn took, what the refusals were, how many turns produced
no answer, how big the prompt got. Those numbers were computed by hand for the
S0 baseline (docs/spikes/V15_BASELINE_EXIT.json); this is the same computation
as a script, so S7 is compared to S0 by the same instrument.

    python scripts/exit_metrics.py docs/spikes/V15_TRACES.json [--out file.json]

Reads the sessions the traces name and nothing else; prints the summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

from dotenv import load_dotenv

load_dotenv(".env", override=True)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

URL = os.getenv("DATABASE_URL_LOCAL",
                "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")

_STEPS = text(
    "SELECT message_id, step_type, tool_name, status, result_summary, args, prompt_tokens "
    "FROM agent_steps WHERE session_id = :s ORDER BY seq")
_MSGS = text(
    "SELECT id, meta FROM agent_messages WHERE session_id = :s AND role = 'assistant'")


async def measure(session_ids: list[str]) -> dict:
    engine = create_async_engine(URL)
    attempts: list[int] = []
    refusals: Counter = Counter()
    accepted = 0
    no_answer = 0
    turns = 0
    peaks: list[int] = []
    tool_calls = 0
    unknown_names: list[str] = []
    try:
        async with engine.connect() as c:
            for sid in session_ids:
                steps = (await c.execute(_STEPS, {"s": sid})).mappings().all()
                msgs = (await c.execute(_MSGS, {"s": sid})).mappings().all()
                by_msg: dict[str, list] = {}
                for s in steps:
                    by_msg.setdefault(s["message_id"], []).append(s)
                for m in msgs:
                    turns += 1
                    meta = m["meta"] or {}
                    if isinstance(meta, str):
                        meta = json.loads(meta)
                    if meta.get("gate") == "exhausted":
                        no_answer += 1
                    mine = by_msg.get(m["id"], [])
                    responds = [s for s in mine if s["step_type"] == "respond"]
                    attempts.append(len(responds))
                    for s in responds:
                        summary = s["result_summary"] or ""
                        if summary.startswith("error: "):
                            refusals[summary[len("error: "):]] += 1
                        elif s["status"] == "rejected":
                            refusals["invalid_arguments"] += 1
                        else:
                            accepted += 1
                    tool_calls += sum(1 for s in mine if s["step_type"] == "tool_call")
                    pk = [s["prompt_tokens"] for s in mine if s["prompt_tokens"]]
                    if pk:
                        peaks.append(max(pk))
    finally:
        await engine.dispose()
    attempts_sorted = sorted(attempts)
    median = attempts_sorted[len(attempts_sorted) // 2] if attempts_sorted else None
    total = accepted + sum(refusals.values())
    return {
        "sessions": len(session_ids), "turns": turns,
        "respond_attempts": {"total": total, "accepted": accepted,
                             "refused_pct": round(100 * (total - accepted) / total) if total else None,
                             "per_turn_median": median,
                             "per_turn": dict(Counter(attempts))},
        "refusal_mix": dict(refusals),
        "no_answer": {"turns": turns, "no_answer": no_answer},
        "tool_calls_per_turn": round(tool_calls / turns, 1) if turns else None,
        "peak_prompt_tokens": {"avg": round(sum(peaks) / len(peaks)) if peaks else None,
                               "max": max(peaks) if peaks else None},
    }


def main(argv: list[str]) -> int:
    import asyncio
    ap = argparse.ArgumentParser()
    ap.add_argument("traces")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    records = json.load(open(args.traces))
    sids = [r["session_id"] for r in records if r.get("session_id")]
    out = asyncio.run(measure(sids))
    print(json.dumps(out, indent=2))
    if args.out:
        json.dump(out, open(args.out, "w"), indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
