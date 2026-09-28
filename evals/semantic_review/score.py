"""Score a judge's report against the human labels (V2 P5).

    python -m evals.semantic_review.score evals/reports/V1E.review.json evals/labels/V1E.json evals/reports/V1E.score.json

Reports, per verdict class: how often the judge raised a problem the labeller did
not (false alarms), missed one the labeller raised (misses), and said unknown.
The numbers are the instrument's quality; they decide nothing in the runtime.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROBLEM = {"false", "unsupported"}


def score(review: list[dict], labels: list[dict]) -> dict:
    labelled = {(l["tag"], l["turn"], l["sentence"]): l["verdict"] for l in labels}
    counts: Counter = Counter()
    for r in review:
        key = (r["tag"], r["turn"], r["sentence"])
        if key not in labelled:
            counts["unlabelled"] += 1
            continue
        truth, said = labelled[key], r["verdict"]
        if said == "unknown":
            counts["undecided"] += 1
        elif (said in PROBLEM) and (truth not in PROBLEM):
            counts["false_alarm"] += 1
        elif (said not in PROBLEM) and (truth in PROBLEM):
            counts["miss"] += 1
        else:
            counts["agree"] += 1
    judged = sum(v for k, v in counts.items() if k != "unlabelled")
    return {"sentences": judged, "unlabelled": counts["unlabelled"], **{k: counts[k] for k in ("agree", "false_alarm", "miss", "undecided")},
            "false_alarm_rate": round(counts["false_alarm"] / judged, 3) if judged else None,
            "miss_rate": round(counts["miss"] / judged, 3) if judged else None,
            "undecided_rate": round(counts["undecided"] / judged, 3) if judged else None}


def main(argv: list[str]) -> int:
    review = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    labels = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    out = score(review, labels)
    Path(argv[3]).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
