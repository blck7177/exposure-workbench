#!/usr/bin/env python3
"""V35 — a round's forensics: every answer step replayed through the check on
the LEDGER AS IT STOOD AT THAT STEP, every problem listed, the counts by reason.

The check's verdict is not stored with the step (only its summary is), and a
replay on the session's final ledger misreads early refusals (V32: an
`unsourced_figure` becomes an `unverified_quote` once later steps fill the
ledger). So the ledger is rebuilt from the evidence_refs of the completed steps
BEFORE the answer step, exactly what the check read.

    python scripts/v35_forensics.py docs/spikes/v33/V33H.json \\
        --out docs/spikes/v33/V33H_forensics.txt --answers docs/spikes/v33/V33H_answers.txt
"""
from __future__ import annotations

import argparse
import asyncio
import collections
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

from exposure_workbench.services import answer_check, ledger as ledger_svc   # noqa: E402


def _url(db: str) -> str:
    return os.environ["DATABASE_URL_LOCAL"].replace("/exposure_workbench", "/" + db)


def _j(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:  # noqa: BLE001
            return {"_raw": x}
    return x or {}


async def _steps(engine, session_id: str) -> list[dict]:
    async with engine.connect() as con:
        rows = (await con.execute(sql("select seq, step_type, tool_name, status, args, result_summary, evidence_refs "
                                      "from agent_steps where session_id = :s order by seq"), {"s": session_id})).all()
    return [dict(r._mapping) for r in rows]


def _ledger_before(steps: list[dict], seq: int):
    led = ledger_svc.Ledger()
    for st in steps:
        if st["seq"] >= seq or st["status"] != "completed":
            continue
        refs = st["evidence_refs"]
        if isinstance(refs, str):
            refs = json.loads(refs)
        for rec in ledger_svc.facts_in(refs or []):
            led.add(rec)
    return led


def _one_line(p: dict) -> str:
    what = p.get("figure") or p.get("id") or p.get("node") or p.get("quote") or p.get("word") or p.get("phrase") or ""
    extra = ""
    if p.get("candidates"):
        extra = " → " + str([f"{c.get('id')} {c.get('measure')} {c.get('subject')}" for c in p["candidates"][:4]])
    if p.get("holds"):
        extra += f" holds={p['holds']!r}"
    return f"- {p.get('at')} {p['reason']} {what!r}{extra}  fix={str(p.get('fix') or '')[:150]}"


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round_json")
    ap.add_argument("--db", default=os.getenv("BATTERY_DB", "exposure_battery"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--answers", required=True)
    args = ap.parse_args(argv)
    data = json.load(open(args.round_json))
    engine = create_async_engine(_url(args.db))
    out: list[str] = []
    answers: list[str] = []
    counts: collections.Counter = collections.Counter()
    first_counts: collections.Counter = collections.Counter()
    answered = 0
    try:
        for convo in data:
            sid = convo["session_id"]
            steps = await _steps(engine, sid)
            for t in convo["turns"]:
                meta = _j(t.get("meta"))
                out.append(f"## {convo['tag']}  session={sid}  elapsed={t.get('elapsed_s')}s  meta={json.dumps(meta, ensure_ascii=False)[:600]}")
                out.append(f"Q: {t['q']}")
                out.append(f"ANSWER: {t.get('answer')}")
                answers.append(f"## {convo['tag']}\n{t.get('answer')}\n")
                if "gate" not in meta:
                    answered += 1
                out.append("--- STEPS ---")
                attempt = 0
                for st in steps:
                    a = _j(st["args"])
                    kind = st["step_type"]
                    if kind == "request":
                        out.append(f"  [{st['seq']:>3}] REQUEST  {json.dumps(a.get('items'), ensure_ascii=False)[:1200]}")
                    elif kind == "digest":
                        out.append(f"  [{st['seq']:>3}] DIGEST   {st['result_summary']}")
                    elif kind == "answer":
                        attempt += 1
                        text = a.get("text") or ""
                        led = _ledger_before(steps, st["seq"])
                        v = answer_check.check(text, led, question=t["q"])
                        kinds = collections.Counter(r.get("kind") for r in led.by_id.values())
                        out.append(f"  [{st['seq']:>3}] ANSWER   {st['status']}  {st['result_summary'][:200]}")
                        out.append("        text: " + text.replace("\n", " ⏎ ")[:1500])
                        out.append(f"        replay: ok={v.ok} error={v.error} problems={len(v.problems)} | ledger {len(led.by_id)} facts {dict(kinds)}")
                        for p in v.problems:
                            out.append("          " + _one_line(p))
                            counts[p["reason"]] += 1
                            if attempt == 1:
                                first_counts[p["reason"]] += 1
                    elif kind == "tool_call":
                        out.append(f"  [{st['seq']:>3}] {str(st['tool_name']):12} {st['status']} {str(st['result_summary'])[:160]}")
                    elif kind == "llm_call":
                        continue
                    else:
                        out.append(f"  [{st['seq']:>3}] {kind:12} {str(st['result_summary'])[:160]}")
                out.append("")
    finally:
        await engine.dispose()
    out.append("=== problems by reason (all attempts / first attempts) ===")
    for r, n in counts.most_common():
        out.append(f"{r:28} {n:>4} {first_counts[r]:>4}")
    out.append(f"answered: {answered}/{sum(len(c['turns']) for c in data)}")
    Path(args.out).write_text("\n".join(out), encoding="utf-8")
    Path(args.answers).write_text("\n".join(answers), encoding="utf-8")
    print("\n".join(out[-len(counts) - 2:]))
    print("written", args.out, "and", args.answers)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
