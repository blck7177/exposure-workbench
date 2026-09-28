"""Ask a model about a frozen corpus, offline (V2 P5).

    OPENAI_API_KEY=… python -m evals.semantic_review.review evals/corpus/V1E.jsonl evals/reports/V1E.review.json

For every sentence of every reply the judge answers with one of `true`, `false`,
`unsupported`, `not_a_claim` or `unknown`, and a sentence of its own. It reads the
frozen question and reply and nothing else — no ledger, no database, no labels —
and writes to evals/reports/. It is a measuring instrument: the desk reads its
report against the human labels (score.py) to learn what the deterministic checks
miss. It has no entry point in the runtime and must never be given one.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROMPT = ("You are auditing one sentence of a financial analyst's reply for an offline evaluation. "
          "Given the user's question and the whole reply, say whether THIS sentence is: true (a factual "
          "claim the reply's own evidence supports), false (a factual claim contradicted by the reply's "
          "own evidence or by arithmetic), unsupported (a factual claim nothing in the reply supports), "
          "not_a_claim (judgement, framing or a question), or unknown. Answer as JSON: "
          "{\"verdict\": ..., \"why\": one sentence}.")


def judge(client, model: str, question: str, reply: str, sentence: str) -> dict:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": json.dumps({"question": question, "reply": reply, "sentence": sentence},
                                                         ensure_ascii=False)}],
        response_format={"type": "json_object"},
    )
    try:
        out = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        out = {}
    verdict = str(out.get("verdict") or "unknown").lower()
    return {"verdict": verdict if verdict in ("true", "false", "unsupported", "not_a_claim", "unknown") else "unknown",
            "why": str(out.get("why") or "")[:400], "model": response.model}


def main(argv: list[str]) -> int:
    from openai import OpenAI      # the SDK directly: nothing of the product's client is reused here

    src, dst = Path(argv[1]), Path(argv[2])
    model = os.environ.get("REVIEW_MODEL", "gpt-5.4-mini")
    client = OpenAI()
    rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = []
    for r in rows:
        for i, sentence in enumerate(r.get("sentences") or []):
            out.append({"tag": r["tag"], "turn": r["turn"], "i": i, "sentence": sentence,
                        **judge(client, model, r.get("question") or "", r.get("answer") or "", sentence)})
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"judged {len(out)} sentence(s) into {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
