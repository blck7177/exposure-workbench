"""V3-D1 — retrieval quality, measured (run: python scripts/eval_retrieval.py).

Retrieval quality in this system has never been measured. MODULE_NOTES M5 says
so in its own words — no rerank, no hybrid, no HNSW, "检索质量实测后再议" — and
the re-arguing never happened because there was no number to argue with. This
produces the number.

It writes docs/spikes/V3_RETRIEVAL_BASELINE.json. That file is the baseline, not
a target: the first run establishes where we are, and
tests/test_eval_retrieval_live.py fails when a later change drops more than 10%
below it. There is no CI in this repository, so this is a live-marked test a
human runs, and saying so is better than pretending a pipeline exists.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env", override=True)

from exposure_workbench.services import company_service, filing_retrieval_service as frs  # noqa: E402

GOLDEN = ROOT / "data" / "eval" / "retrieval_golden.yaml"
BASELINE = ROOT / "docs" / "spikes" / "V3_RETRIEVAL_BASELINE.json"
URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")


def _hit(item_code: str | None, expected: list[str]) -> bool:
    """Whether a returned passage sits in an item the answer could live in.

    Prefix match, because the corpus writes the same item two ways depending on
    the form: a 10-K has "Item 1A" and a 10-Q has "Part II, Item 1A".
    """
    if not item_code:
        return False
    code = item_code.strip().lower()
    return any(code.endswith(e.strip().lower()) or e.strip().lower().endswith(code)
               for e in expected)


async def evaluate() -> dict:
    spec = yaml.safe_load(GOLDEN.read_text())
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)

    per_query: list[dict] = []
    try:
        async with mk() as db:
            for q in spec["queries"]:
                try:
                    company = await company_service.get_by_ticker(db, q["ticker"])
                except company_service.CompanyNotFound:
                    per_query.append({**q, "skipped": "company_not_found"})
                    continue
                try:
                    passages = await frs.search_passages(db, company.id, q["query"], k=10)
                except frs.NotIndexed:
                    per_query.append({**q, "skipped": "not_indexed"})
                    continue

                items = [p.item_code for p in passages]
                hits = [_hit(i, q["expect_items"]) for i in items]
                per_query.append({
                    "id": q["id"], "ticker": q["ticker"], "intent": q["intent"],
                    "recall_at_5": int(any(hits[:5])),
                    "recall_at_10": int(any(hits[:10])),
                    # The metric that actually moves — see the note in main().
                    "precision_at_5": round(sum(hits[:5]) / max(len(hits[:5]), 1), 4),
                    "precision_at_10": round(sum(hits) / max(len(hits), 1), 4),
                    "returned_items": items[:5],
                })
    finally:
        await engine.dispose()

    scored = [r for r in per_query if "skipped" not in r]
    n = len(scored) or 1
    by_intent: dict[str, dict] = {}
    for r in scored:
        b = by_intent.setdefault(r["intent"], {"n": 0, "r5": 0, "r10": 0})
        b["n"] += 1
        b["r5"] += r["recall_at_5"]
        b["r10"] += r["recall_at_10"]
        b["p5"] = b.get("p5", 0.0) + r["precision_at_5"]

    return {
        "queries": len(per_query),
        "scored": len(scored),
        "skipped": [r["id"] for r in per_query if "skipped" in r],
        "recall_at_5": round(sum(r["recall_at_5"] for r in scored) / n, 4),
        "recall_at_10": round(sum(r["recall_at_10"] for r in scored) / n, 4),
        "precision_at_5": round(sum(r["precision_at_5"] for r in scored) / n, 4),
        "precision_at_10": round(sum(r["precision_at_10"] for r in scored) / n, 4),
        "by_intent": {k: {"n": v["n"], "recall_at_5": round(v["r5"] / v["n"], 4),
                          "precision_at_5": round(v["p5"] / v["n"], 4)}
                      for k, v in sorted(by_intent.items())},
        "detail": per_query,
    }


def main() -> None:
    result = asyncio.run(evaluate())
    write = "--write-baseline" in sys.argv
    # Measured first, then read honestly: recall@5 came back 1.000 on all 24
    # queries, which does not mean retrieval is perfect — it means "did ANY of
    # the top 5 land in the right SEC item" is too easy a question on a corpus
    # where 7 of every 10 returned passages already do. A saturated metric
    # cannot detect a regression, so precision@k is the number the regression
    # test guards, and recall@5 is kept as a floor check that would catch
    # retrieval breaking outright.
    print(json.dumps({k: v for k, v in result.items() if k != "detail"}, indent=2))
    if write:
        BASELINE.write_text(json.dumps(result, indent=2) + "\n")
        print(f"\nbaseline written to {BASELINE.relative_to(ROOT)}")
    else:
        print("\n(run with --write-baseline to record this as the reference)")


if __name__ == "__main__":
    main()
