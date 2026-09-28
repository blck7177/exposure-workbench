"""Freeze a round into a corpus the judge can read without a database.

    python -m evals.semantic_review.corpus docs/spikes/v1/V1E.json evals/corpus/V1E.jsonl

One line per turn: the question, the reply's text and its sentences, the check's
refusals with their reasons, and the meta the loop recorded (completion, the
requirements' standing). Nothing is fetched live: what the battery wrote is what
the judge sees, which is what makes two runs of the judge comparable.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SENTENCE_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z\u201c\"(\[])")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text or "") if s.strip()]


def freeze(battery_json: Path) -> list[dict]:
    rounds = json.loads(battery_json.read_text(encoding="utf-8"))
    out: list[dict] = []
    for convo in rounds:
        for turn in convo.get("turns") or []:
            steps = turn.get("steps") or []
            refusals = []
            for s in steps:
                if s.get("step_type") == "answer" and s.get("status") == "rejected":
                    try:
                        problems = json.loads(s.get("problems") or "[]") or []
                    except json.JSONDecodeError:
                        problems = []
                    refusals.append({"seq": s.get("seq"), "reasons": [p.get("reason") for p in problems if isinstance(p, dict)]})
            out.append({"tag": convo.get("tag"), "turn": turn.get("turn"), "question": turn.get("q"),
                        "answer": turn.get("answer"), "sentences": sentences(turn.get("answer") or ""),
                        "meta": {k: v for k, v in (turn.get("meta") or {}).items() if k in ("completion", "requirements", "gate")},
                        "refusals": refusals})
    return out


def main(argv: list[str]) -> int:
    src, dst = Path(argv[1]), Path(argv[2])
    rows = freeze(src)
    dst.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"froze {len(rows)} turn(s) from {src} into {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
