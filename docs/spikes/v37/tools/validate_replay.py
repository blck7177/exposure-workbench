"""Replay fidelity: for a completion whose only tool call was one evidence call,
the next completion's recorded read.chars is that tool message's length."""
import asyncio, json, sys
from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from sqlalchemy.ext.asyncio import create_async_engine
import v36_forensics as vf
db, rj, rows_path = sys.argv[1:4]
rows = {(r["q"], r["seq"]): r for r in json.load(open(rows_path)) if "chars" in r}
async def main():
    eng = create_async_engine(vf._url(db))
    pairs = []
    for conv in json.load(open(rj)):
        steps = await vf._steps(eng, conv["session_id"])
        q = conv["tag"][:3]
        by_actor = {}
        for st in steps:
            a = st["actor"] or "meta"
            by_actor.setdefault(a, []).append(st)
        for a, sts in by_actor.items():
            for i, st in enumerate(sts):
                if st["step_type"] == "tool_call" and st["tool_name"] == "run" and (q, st["seq"]) in rows:
                    prev = [x for x in sts[:i] if x["step_type"] == "llm_call"]
                    nxt = [x for x in sts[i+1:] if x["step_type"] == "llm_call"]
                    if not prev or not nxt or "1 tool call" not in (prev[-1]["result_summary"] or ""):
                        continue
                    # only this call between the two completions
                    between = [x for x in sts if prev[-1]["seq"] < x["seq"] < nxt[0]["seq"] and x["step_type"] in ("tool_call", "brief")]
                    if len(between) != 1:
                        continue
                    rd = (vf._j(nxt[0]["args"]) or {}).get("read") or {}
                    if rd.get("chars"):
                        pairs.append((q, st["seq"], rows[(q, st["seq"])]["chars"], rd["chars"]))
    await eng.dispose()
    exact = sum(1 for p in pairs if p[2] == p[3])
    close = sum(1 for p in pairs if abs(p[2] - p[3]) <= 0.05 * p[3])
    print(f"{len(pairs)} single-run reads: exact {exact}, within 5% {close}")
    for p in pairs:
        if abs(p[2] - p[3]) > 0.05 * p[3]:
            print("  off:", p)
asyncio.run(main())
