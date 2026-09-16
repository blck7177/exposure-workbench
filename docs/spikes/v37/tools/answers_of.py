#!/usr/bin/env python3
"""Every gated text of one session in full (answer and brief findings + report),
replayed on the ledger as it stood at that step, every problem in full.

    python answers_of.py <db> <session_id> [--briefs]
"""
import asyncio, json, os, sys
from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from sqlalchemy.ext.asyncio import create_async_engine
import v36_forensics as vf
from exposure_workbench.services import answer_check

async def main():
    db, sid = sys.argv[1], sys.argv[2]
    briefs = "--briefs" in sys.argv
    eng = create_async_engine(vf._url(db))
    steps = await vf._steps(eng, sid)
    from sqlalchemy import text as _sql
    async with eng.connect() as con:
        row = (await con.execute(_sql("select content from agent_messages where session_id=:s and role='user' order by created_at limit 1"), {"s": sid})).first()
    question = row[0] if row else None
    await eng.dispose()
    q = None
    for st in steps:
        if st["step_type"] not in ("answer",) + (("brief",) if briefs else ()):
            continue
        a = vf._j(st["args"])
        led = vf._ledger_before(steps, st["seq"])
        if st["step_type"] == "answer":
            texts = [("answer", a.get("text") or "")]
        else:
            b = a.get("brief") or {}
            texts = [(f"finding want={f.get('want')}", f.get("finding") or "") for f in b.get("findings") or []]
            texts += [(f"not_done want={n.get('want')}", json.dumps(n, ensure_ascii=False)) for n in b.get("not_done") or []]
            texts += [("caveats", json.dumps(b.get("caveats"), ensure_ascii=False))]
            texts += [("report", (a.get("report") or {}).get("text") or "")]
        print(f"===== seq {st['seq']} {st['step_type']} {st['actor'] or 'meta'} {st['status']} =====")
        for label, t in texts:
            print(f"--- {label} ---\n{t}")
        if st["step_type"] == "answer":
            v = answer_check.check(a.get("text") or "", led, question=question)
            for p in v.problems:
                print("  PROBLEM", json.dumps({k: p.get(k) for k in ("at", "reason", "figure", "id", "word", "fix", "holds") if p.get(k) is not None}, ensure_ascii=False)[:600])
        else:
            for p in a.get("problems") or []:
                print("  PROBLEM", json.dumps({k: p.get(k) for k in ("where", "at", "reason", "figure", "id", "word", "fix", "holds") if p.get(k) is not None}, ensure_ascii=False)[:600])
        print()

asyncio.run(main())
