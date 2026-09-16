#!/usr/bin/env python3
"""What every domain analyst READ from each evidence call, rebuilt in record
order, and where each figure it made went.

For each run/read_filings/search_web/start step of a sub-analyst: the recorded
facts (generation order) -> F.cap (the tool's own cap) -> digest.render with the
analyst's `seen` carried across its calls and the completion's room (16000 //
tool calls in that completion, floor 4000) -> ejson.dumps_capped(room). An error
result has no facts; its words are the boundary step that follows it.

Every made fact gets one state:
  SHOWN                    its id is in the text the analyst read
  TWIN_SHOWN               collapsed into an earlier figure of this call that is shown (same reading)
  HELD_TOOL_CAP            F.cap dropped it
  SEEN_SHOWN_EARLIER       same reading registered by an EARLIER call, where it was shown (by design)
  SWALLOWED_NEVER_SHOWN    same reading registered by an EARLIER call that never showed it (defect 2)
  SWALLOWED_TWIN_CUT       collapsed into a figure of this call that fit then cut
  CUT_FIT                  digest.fit cut it
  CUT_DUMP                 rendered, then dropped by dumps_capped
  NOT_RENDERED             not a scalar or series and absent from the text (this round: refusals dropped by dumps_capped)

    python replay_read.py <db> <round.json> <tag> <out_dir>
"""
import asyncio, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from sqlalchemy.ext.asyncio import create_async_engine
import v36_forensics as vf
from exposure_workbench.services import digest as dg, facts as F, ledger as L, fact_adapters as FA
from exposure_workbench.utils import json as ejson

EVIDENCE = ("run", "read_filings", "search_web", "start")


def nodes_of(summary: str) -> dict:
    if "nodes: " not in (summary or ""):
        return {}
    out = {}
    for part in summary.split("nodes: ", 1)[1].split(", "):
        if "=" in part:
            n, k = part.split("=", 1)
            out[n.strip()] = {"kind": k.strip()}
    return out


def ncalls(summary: str) -> int:
    m = re.search(r"(\d+) tool calls?", summary or "")
    return int(m.group(1)) if m else 1


async def one(eng, conv, tag, out_dir, rows):
    sid, q = conv["session_id"], conv["tag"][:3]
    steps = await vf._steps(eng, sid)
    seen: dict[str, dict] = defaultdict(dict)
    shown_ids: dict[str, set] = defaultdict(set)      # ids that reached the analyst's eyes so far
    room: dict[str, int] = {}
    qdir = Path(out_dir) / tag / q
    qdir.mkdir(parents=True, exist_ok=True)
    for i, st in enumerate(steps):
        actor = st["actor"] or "meta"
        if st["step_type"] == "delegate" and st["status"] == "completed":
            doms = [t.get("domain") for t in (vf._j(st["args"]) or {}).get("tasks") or []]
            for d in doms:
                seen["sub:" + str(d)] = {}          # a new analyst: run_sub_analyst starts with seen = {}
                shown_ids["sub:" + str(d)] = set()
            if len(doms) != len(set(doms)):
                rows.append({"tag": tag, "q": q, "seq": st["seq"], "warning": f"parallel tasks share a domain: {doms}"})
            continue
        if not actor.startswith("sub:"):
            continue
        if st["step_type"] == "llm_call":
            room[actor] = max(4000, 16000 // max(1, ncalls(st["result_summary"])))
            continue
        if st["step_type"] != "tool_call" or st["tool_name"] not in EVIDENCE:
            continue
        tool, seq = st["tool_name"], st["seq"]
        args = vf._j(st["args"]) or {}
        cap = room.get(actor, 16000)
        made = [F.from_record(x) for x in L.facts_in(vf._j(st["evidence_refs"]) or [])]
        summ = st["result_summary"] or ""
        name = f"{seq:03d}_{actor[4:]}_{tool}"
        if not made and summ.startswith("error"):
            nxt = steps[i + 1] if i + 1 < len(steps) else None
            words = [r.get("text") for r in L.facts_in(vf._j(nxt["evidence_refs"]) or [])] if nxt and nxt["step_type"] == "boundary" else []
            (qdir / f"{name}.txt").write_text(f"{summ}\n" + "\n".join(w or "" for w in words), encoding="utf-8")
            rows.append({"tag": tag, "q": q, "seq": seq, "actor": actor[4:], "tool": tool, "error": summ, "words": words})
            continue
        kept, held = F.cap(made)
        kept_ids = {f.id for f in kept}
        res = {"program_id": "p", "returns": (args.get("program") or {}).get("return"),
               "nodes": nodes_of(summ), "facts": F.block_for_model(kept)}
        if held:
            held["how"] = FA.READ_BY_NAME.get(tool, "ask for fewer names")
            res["held_back"] = held
        minter = dg.Minter()
        before = dict(seen[actor])
        shown = dg.render(res, mint=minter, seen=seen[actor], cap=cap, call={"tool": tool, "args": args})
        text = ejson.dumps_capped(shown, cap)
        (qdir / f"{name}.json").write_text(text, encoding="utf-8")
        # where each made fact went
        fig_ids = [f["id"] for f in shown.get("figures") or []]
        twin_of = {a: f["id"] for f in shown.get("figures") or [] for a in f.get("also", [])}
        # collapsed figures whose twin was cut: their twin is in seen but not in fig_ids
        seen_now = seen[actor]
        state = {}
        for f in made:
            if f.id in text:
                state[f.id] = "SHOWN"
            elif f.id not in kept_ids:
                state[f.id] = "HELD_TOOL_CAP"
            elif f.kind != F.SCALAR:
                state[f.id] = "CUT_DUMP" if f.kind in (F.SERIES, F.PASSAGE) else "NOT_RENDERED"
            else:
                key = (f.subject, f.measure, f.as_of, str(dg.display(f.value, f.unit)))
                if key in before:
                    state[f.id] = ("SEEN_SHOWN_EARLIER" if before[key].get("id") in shown_ids[actor]
                                   else "SWALLOWED_NEVER_SHOWN")
                elif f.id in twin_of:
                    state[f.id] = "TWIN_SHOWN" if twin_of[f.id] in text else "SWALLOWED_TWIN_CUT"
                else:
                    first = seen_now.get(key)
                    if first is not None and first.get("id") != f.id:
                        state[f.id] = "TWIN_SHOWN" if first.get("id") in text else "SWALLOWED_TWIN_CUT"
                    elif f.id in fig_ids:
                        state[f.id] = "CUT_DUMP"
                    else:
                        state[f.id] = "CUT_FIT"
        shown_ids[actor] |= set(re.findall(r"f_[0-9a-f]{12}", text))
        returns = (args.get("program") or {}).get("return") or []
        ret_states = {}
        for f in made:
            node = (f.params or {}).get("node")
            if node in returns:
                ret_states.setdefault(node, Counter())[state[f.id]] += 1
        rows.append({"tag": tag, "q": q, "seq": seq, "actor": actor[4:], "tool": tool, "cap": cap,
                     "made": len(made), "kept": len(kept), "chars": len(text),
                     "states": dict(Counter(state.values())), "returns": returns,
                     "return_states": {k: dict(v) for k, v in ret_states.items()},
                     "boundaries": [b.get("text") for b in shown.get("boundaries") or []],
                     "fact_states": state})


async def main():
    db, rj, tag, out_dir = sys.argv[1:5]
    rows: list = []
    eng = create_async_engine(vf._url(db))
    try:
        for conv in json.load(open(rj)):
            await one(eng, conv, tag, out_dir, rows)
    finally:
        await eng.dispose()
    Path(out_dir, f"{tag}_rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(tag, len(rows), "evidence calls")


asyncio.run(main())
