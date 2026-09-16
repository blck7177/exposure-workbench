"""How much of what the tool made and showed belongs to nodes the program did NOT name in `return`."""
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
    c = Counter()
    for r in rows:
        steps = await vf._steps(eng, sids[r["q"]])
        st = next(s for s in steps if s["seq"] == r["seq"])
        prog = (vf._j(st["args"]) or {}).get("program") or {}
        if not prog.get("return"):
            c["runs without return"] += 1
            continue
        c["runs with return"] += 1
        made = L.facts_in(vf._j(st["evidence_refs"]) or [])
        ret = set(prog["return"])
        for f in made:
            node = (f.get("params") or {}).get("node")
            side = "returned" if node in ret else "not returned"
            c[f"made {side}"] += 1
            if r["fact_states"].get(f["id"]) == "SHOWN":
                c[f"shown {side}"] += 1
        if any(r["fact_states"].get(f["id"]) in ("HELD_TOOL_CAP", "CUT_FIT") and (f.get("params") or {}).get("node") in ret for f in made) \
           and any(r["fact_states"].get(f["id"]) == "SHOWN" and (f.get("params") or {}).get("node") not in ret for f in made):
            c["runs where a returned figure was dropped while an unreturned one was shown"] += 1
    await eng.dispose()
    print(tag, dict(c))
asyncio.run(main())
