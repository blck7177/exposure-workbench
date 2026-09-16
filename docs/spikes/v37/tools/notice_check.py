"""Of the facts a `return`-named node lost to the tool cap or the digest fit,
how many does the held-back notice the analyst read actually name?"""
import asyncio, json, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from sqlalchemy.ext.asyncio import create_async_engine
import v36_forensics as vf
from exposure_workbench.services import facts as F, ledger as L
db, rj, rows_path, tag = sys.argv[1:5]
rows = [r for r in json.load(open(rows_path)) if r.get("tool") == "run" and "error" not in r and "fact_states" in r]
SP = Path(rows_path).parent
async def main():
    eng = create_async_engine(vf._url(db))
    sids = {c["tag"][:3]: c["session_id"] for c in json.load(open(rj))}
    named = unnamed = 0
    node_named = node_unnamed = 0
    for r in rows:
        lost = {fid for fid, st in r["fact_states"].items() if st in ("HELD_TOOL_CAP", "CUT_FIT")}
        if not lost:
            continue
        steps = await vf._steps(eng, sids[r["q"]])
        st = next(s for s in steps if s["seq"] == r["seq"])
        made = {x["id"]: x for x in L.facts_in(vf._j(st["evidence_refs"]) or [])}
        text = json.loads((SP / tag / r["q"] / f"{r['seq']:03d}_{r['actor']}_run.json").read_text())
        listed = set()
        for b in text.get("boundaries") or []:
            listed |= set(b.get("measures") or [])
        per_node = {}
        for fid in lost:
            f = made[fid]
            node = (f.get("params") or {}).get("node")
            if node not in r["returns"]:
                continue
            key = f"{f.get('subject') or ''}:{f.get('measure')}".strip(":")
            ok = key in listed
            named += ok; unnamed += (not ok)
            per_node.setdefault(node, []).append(ok)
        for node, oks in per_node.items():
            if any(oks): node_named += 1
            else: node_unnamed += 1
    await eng.dispose()
    print(f"{tag}: lost facts of return-named nodes: named in the notice {named}, not named {unnamed}; "
          f"nodes with at least one lost fact named {node_named}, nodes with none named {node_unnamed}")
    print("  (a notice never names a node; it lists up to 20 / 30 'subject:measure' strings, sorted)")
asyncio.run(main())
