"""V3-D2 — faithfulness of what this system has already said (run it directly).

Three metrics, all deterministic. No LLM judge: rules-based verification is the
stronger instrument wherever it reaches, and reaching for a judge before the
deterministic checks are exhausted would mean grading our own homework with a
second, less reliable copy of the thing being graded.

  1. citation resolution — every cited id resolves. The gate already guarantees
     this at write time; here it is checked at READ time, which is different:
     evidence is append-only, but a citation that stopped resolving would mean
     that promise had been broken somewhere.
  2. numeric verification — every stated number matches a value the evidence
     cited FOR IT actually holds. This is A1's verify(), reused rather than
     reimplemented, so the eval cannot drift from the gate.
  3. number-bearing answers with no citations at all — must be zero after A0-1.

It replays the corpus already in the database rather than generating fresh
answers. That is the point, not a shortcut: an answer produced after A1 has by
construction already passed A1, so it can only ever score 100% and measures
nothing. The pre-A1 text is the only sample that can say what the new rules
actually refuse — which is the evidence 拍板点 1 (full-strict numeric matching)
gets re-argued on.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env", override=True)

from exposure_workbench.db.models import AgentMessage, IssuerBrief  # noqa: E402
from exposure_workbench.services import evidence_trail_service as trail  # noqa: E402
from exposure_workbench.services import numeric_verification as nv  # noqa: E402

URL = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
# open_questions is measured too, against the union of the brief's citations —
# the same rule submit_brief enforces (V3-R5), and the honest one for a block
# that carries no citations of its own. Leaving it out of the metric was how the
# gap stayed invisible: the eval and the gate agreed, and both were looking away.
BLOCKS = ("financial_summary", "key_changes", "management_explanation",
          "market_context", "portfolio_implications", "open_questions")


async def _resolves(db, ids) -> tuple[int, list[str]]:
    dangling = [i for i in ids if not await trail._exists_in_db(db, i)]
    return len(ids), dangling


async def evaluate() -> dict:
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    out: dict = {"chat": {}, "briefs": {}, "refusals": []}
    try:
        async with mk() as db:
            # ── chat ────────────────────────────────────────────────────────
            msgs = (await db.execute(
                select(AgentMessage).where(AgentMessage.role == "assistant")
            )).scalars().all()
            numbers = bad = cited = dangling_total = uncited_with_numbers = 0
            for m in msgs:
                stated = nv.extract_numbers(m.content or "")
                ids = list(m.citations or [])
                if stated and not ids:
                    uncited_with_numbers += 1
                    out["refusals"].append({"where": m.id, "reason": "numbers_without_citations",
                                            "numbers": nv.raw_forms(stated)})
                    continue
                n, dangling = await _resolves(db, ids)
                cited += n
                dangling_total += len(dangling)
                if not stated:
                    continue
                values, quoted = await nv.resolve_cited_values(db, ids)
                problems = nv.verify(stated, values, quoted)
                numbers += len(stated)
                bad += len(problems)
                for p in problems:
                    out["refusals"].append({"where": m.id, "reason": "unverified_number", **p})
            out["chat"] = {"messages": len(msgs), "numbers": numbers, "unverified": bad,
                           "citations": cited, "dangling_citations": dangling_total,
                           "number_bearing_uncited": uncited_with_numbers}

            # ── briefs (per block, against that block's own citations) ──────
            briefs = (await db.execute(select(IssuerBrief))).scalars().all()
            b_numbers = b_bad = b_cited = b_dangling = 0
            for b in briefs:
                per_block = b.block_citations or {}
                for name in BLOCKS:
                    text = getattr(b, name) or ""
                    stated = nv.extract_numbers(text)
                    if not stated:
                        continue
                    # Briefs written before V3 kept only a flat list; measuring
                    # them against it is the honest reading of what they carry.
                    # open_questions has no list of its own by design and is
                    # measured against the union, which is the flat list.
                    ids = (list(b.citations or []) if name == "open_questions"
                           else per_block.get(name) or list(b.citations or []))
                    n, dangling = await _resolves(db, ids)
                    b_cited += n
                    b_dangling += len(dangling)
                    values, quoted = await nv.resolve_cited_values(db, ids)
                    problems = nv.verify(stated, values, quoted)
                    b_numbers += len(stated)
                    b_bad += len(problems)
                    for p in problems:
                        out["refusals"].append({"where": f"{b.id}:{name}",
                                                "reason": "unverified_number", **p})
            out["briefs"] = {"briefs": len(briefs), "numbers": b_numbers, "unverified": b_bad,
                             "citations": b_cited, "dangling_citations": b_dangling,
                             "with_block_citations": sum(1 for b in briefs if b.block_citations)}
    finally:
        await engine.dispose()
    return out


def main() -> None:
    r = asyncio.run(evaluate())
    print(json.dumps({k: v for k, v in r.items() if k != "refusals"}, indent=2))
    print(f"\n{len(r['refusals'])} refusals:")
    for x in r["refusals"][:40]:
        near = x.get("nearest")
        near_s = f" nearest={near['value']:.6g} ({near['label']})" if near else ""
        print(f"  {x['where']:38s} {x['reason']:24s} {x.get('number', '')}{near_s}")


if __name__ == "__main__":
    main()
