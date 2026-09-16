#!/usr/bin/env python3
"""V37 — the accepted answers of a round, with the ledger each was accepted on.

WHY THIS EXISTS. Phase B adds rules to `services/answer_check`, and every rule
that refuses a sentence can also refuse a true one. The cheap way to find that
out is the expensive one: another 20-question live round. This is the cheap way
that works — the answers a round already accepted, each paired with the ledger as
it stood at its `answer` step, so a new check can be run over them offline and
asked one question: which of these does it now refuse, and is that list exactly
the sentences the analysis said were false?

Round B is the first corpus (15 accepted answers, 2,661 facts). The ledger is
stored whole, not trimmed to the facts the answer cites: half of what the check
does is decide that a bare number resolves to NOTHING, and a trimmed ledger
would answer that differently. It is read as `services/ledger.load` reads it —
the fact records of completed steps, in seq order — which is what the check read
at the moment it accepted.

    .venv/bin/python scripts/v37_corpus.py docs/spikes/v36/V36B.json \
        --out tests/data/v36b_accepted.json.gz
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv(".env", override=True)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.services import ledger as ledger_svc   # noqa: E402


def _url(db: str) -> str:
    return os.environ["DATABASE_URL_LOCAL"].replace("/exposure_workbench", "/" + db)


async def _accepted(con, session_id: str) -> list[dict]:
    """Every accepted `answer` of one session, with the facts that were on the
    ledger when it was accepted.

    `status='completed'` on the answer step is the gate having accepted it, and
    the facts are those of the completed steps BEFORE it — a replay on the
    session's final ledger reads a different ledger than the check did (V32).
    """
    rows = (await con.execute(sql(
        "select seq, step_type, status, args, evidence_refs from agent_steps "
        "where session_id = :s order by seq"), {"s": session_id})).all()
    steps = [dict(r._mapping) for r in rows]
    out = []
    for st in steps:
        if st["step_type"] != "answer" or st["status"] != "completed":
            continue
        args = st["args"] if isinstance(st["args"], dict) else json.loads(st["args"] or "{}")
        facts: list[dict] = []
        seen: set[str] = set()
        for earlier in steps:
            if earlier["seq"] >= st["seq"] or earlier["status"] != "completed":
                continue
            refs = earlier["evidence_refs"]
            if isinstance(refs, str):
                refs = json.loads(refs or "[]")
            for rec in ledger_svc.facts_in(refs or []):
                if rec["id"] not in seen:
                    seen.add(rec["id"])
                    facts.append(rec)
        out.append({"seq": st["seq"], "text": args.get("text") or "", "facts": facts})
    return out


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round_json")
    ap.add_argument("--db", default=os.getenv("BATTERY_DB", "exposure_battery"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    rounds = json.loads(Path(args.round_json).read_text())
    engine = create_async_engine(_url(args.db))
    corpus = []
    async with engine.connect() as con:
        for conv in rounds:
            for turn in conv["turns"]:
                for a in await _accepted(con, conv["session_id"]):
                    corpus.append({"tag": conv["tag"], "question": turn["q"], **a})
    await engine.dispose()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Gzipped when the name says so: the whole ledger of fifteen answers is 2.2 MB
    # of JSON and 390 KiB compressed, and a fixture nobody wants to open in an
    # editor should not cost that much of a checkout.
    body = json.dumps({"round": Path(args.round_json).stem, "answers": corpus},
                      ensure_ascii=False, separators=(",", ":")).encode()
    if out.suffix == ".gz":
        import gzip
        out.write_bytes(gzip.compress(body, 9))
    else:
        out.write_bytes(body)
    print(f"wrote {out}  {len(corpus)} accepted answer(s), "
          f"{sum(len(a['facts']) for a in corpus)} facts, {out.stat().st_size // 1024} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
