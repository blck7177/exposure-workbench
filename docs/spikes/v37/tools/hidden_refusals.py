"""Refusals (absence facts) a run made that never reached the analyst's eyes."""
import asyncio, json, sys
from collections import Counter
from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from sqlalchemy.ext.asyncio import create_async_engine
import v36_forensics as vf
from exposure_workbench.services import ledger as L
db, rj, rows_path, tag = sys.argv[1:5]
rows = [r for r in json.load(open(rows_path)) if r.get("tool") == "run" and "error" not in r and "fact_states" in r]
async def main():
    eng = create_async_engine(vf._url(db))
    sids = {c["tag"][:3]: c["session_id"] for c in json.load(open(rj))}
    c = Counter(); ex = []
    for r in rows:
        steps = await vf._steps(eng, sids[r["q"]])
        st = next(s for s in steps if s["seq"] == r["seq"])
        for f in L.facts_in(vf._j(st["evidence_refs"]) or []):
            if f.get("kind") != "absence":
                continue
            state = r["fact_states"].get(f["id"])
            c[state] += 1
            if state != "SHOWN":
                root = (f.get("params") or {}).get("error")
                c[f"hidden:{root}"] += 1
                ex.append((r["q"], r["seq"], r["actor"][:22], (f.get("params") or {}).get("node"), (f.get("text") or "")[:110]))
    await eng.dispose()
    print(tag, dict(c))
    for e in ex[:40]:
        print("  ", e)
asyncio.run(main())
