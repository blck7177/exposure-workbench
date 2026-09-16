#!/usr/bin/env python3
"""Replay what one analyst READ from its run calls: the tool's own cap (F.cap on
the recorded facts, in recorded order), then digest.render with `seen` carried
across the analyst's calls and the per-completion room. The note (node kinds,
returns) is rebuilt from the step's summary, so sizes are close, not exact.

    python replay_digest.py <db> <session> <actor> <seq,seq,...> [--watch id,id]
"""
import json, subprocess, sys
sys.path.insert(0, "src")
from exposure_workbench.services import digest as dg, facts as F, ledger as L

db, sid, actor, seqs = sys.argv[1], sys.argv[2], sys.argv[3], [int(s) for s in sys.argv[4].split(",")]
watch = set(sys.argv[sys.argv.index("--watch") + 1].split(",")) if "--watch" in sys.argv else set()

def row(seq):
    out = subprocess.run(["docker", "exec", "exposure-postgres", "psql", "-U", "exposure", "-d", db, "-Atc",
                          f"select json_build_object('refs', evidence_refs, 'sum', result_summary, 'args', args) from agent_steps where session_id='{sid}' and seq={seq}"],
                         capture_output=True, text=True).stdout.strip()
    return json.loads(out)

seen = {}
for seq in seqs:
    r = row(seq)
    made = [F.from_record(x) for x in L.facts_in(r["refs"] or [])]
    kept, held = F.cap(made)
    kept_ids = {f.id for f in kept}
    nodes = r["sum"].split("nodes: ", 1)[-1] if "nodes: " in (r["sum"] or "") else ""
    res = {"program_id": "p", "returns": (r["args"].get("program") or {}).get("return"), "nodes": nodes,
           "facts": F.block_for_model(kept)}
    if held:
        res["held_back"] = held
    minted = []
    mint = lambda text, **kw: (minted.append(text), dg.boundary(text, **kw)[0])[1]
    before = set(seen)
    def key_of(f):
        return (f.subject, f.measure, f.as_of, str(dg.display(f.value, f.unit)))
    shown = dg.render(res, mint=mint, seen=seen, cap=16000, call={"tool": "run", "args": r["args"]})
    shown_ids = {f["id"] for f in shown.get("figures") or []} | {s["id"] for s in shown.get("series") or []}
    also = {a for f in shown.get("figures") or [] for a in f.get("also", [])}
    print(f"seq {seq}: made {len(made)}, tool kept {len(kept)}, digest shows {len(shown_ids)} figures "
          f"({len(json.dumps(shown))} chars), swallowed-as-seen {sum(1 for f in kept if f.id not in shown_ids and key_of(f) in before)}")
    for w in sorted(watch):
        if any(f.id == w for f in made):
            fw = next(f for f in made if f.id == w)
            state = ("SHOWN" if w in shown_ids else
                     "held by tool cap" if w not in kept_ids else
                     "swallowed: same reading registered as seen by an earlier call" if key_of(fw) in before else
                     "swallowed: same reading earlier in this call" if w in also else
                     "cut by digest fit")
            print(f"    {w}: {state}")
