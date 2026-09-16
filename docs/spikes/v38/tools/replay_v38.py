#!/usr/bin/env python3
"""Round C's evidence calls replayed through the V38 tool layer (offline).

For every `run` a domain analyst made in round C: the facts the call recorded
(generation order) and the program it sent are fed back through the CURRENT
`fact_adapters.adapt_all` (T1 return, T2 cap), `digest.render` with the
analyst's `seen` carried across its calls (T2 fold, T3, T4) and
`dumps_capped(room, keep=…)` (T2), exactly as `agents/sub_analyst` does. The
room is the completion's: 16000 // tool calls in that completion, floor 4000.
The facts are round C's own (their identities pre-date S4 and they carry no
made_of): this measures what the tool SHOWS, not what the services now compute.

Every made fact gets one state:
  SHOWN            its id is in the text the analyst read
  REPEATED         a reading the analyst was shown before, named under `repeated`
  TWIN             collapsed into a figure of this call that is shown (`also`)
  FOLDED           a refusal said once under the refusal that stopped it (`blocks`)
  NOT_RETURNED     a node the program did not name in `return` (counted in `nodes`)
  HELD             a returned node too large to show (counted in `held_back`)
  CUT              rendered and cut to fit (counted in the digest's note)
  LOST             none of the above: a fact the analyst was not told about

    python replay_v38.py <db> <round.json> <tag> <out_dir>
"""
import asyncio, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from sqlalchemy.ext.asyncio import create_async_engine

import v36_forensics as vf
from exposure_workbench.agents import sub_analyst as sa
from exposure_workbench.services import digest as dg, facts as F, fact_adapters as FA, ledger as L
from exposure_workbench.services import program_service as ps
from exposure_workbench.utils import json as ejson

_ID = re.compile(r"f_[0-9a-f]{12}")


def nodes_of(summary: str) -> dict:
    if "nodes: " not in (summary or ""):
        return {}
    out = {}
    for part in summary.split("nodes: ", 1)[1].split(", "):
        if "=" in part:
            n, k = part.split("=", 1)
            out[n.strip()] = {"kind": k.strip().rstrip("…")}
    return out


def ncalls(summary: str) -> int:
    m = re.search(r"(\d+) tool calls?", summary or "")
    return int(m.group(1)) if m else 1


def returns_of(program: dict) -> list[str]:
    parsed = ps.parse(program or {})
    if isinstance(parsed, ps.Program):
        return parsed.returns
    return list((program or {}).get("return") or [])


async def one(eng, conv, tag, out_dir, rows):
    sid, q = conv["session_id"], conv["tag"][:3]
    steps = await vf._steps(eng, sid)
    seen: dict[str, dict] = defaultdict(dict)
    shown_ids: dict[str, set] = defaultdict(set)
    room: dict[str, int] = {}
    qdir = Path(out_dir) / tag / q
    qdir.mkdir(parents=True, exist_ok=True)
    for st in steps:
        actor = st["actor"] or "meta"
        if st["step_type"] == "delegate" and st["status"] == "completed":
            for t in (vf._j(st["args"]) or {}).get("tasks") or []:
                seen["sub:" + str(t.get("domain"))] = {}
                shown_ids["sub:" + str(t.get("domain"))] = set()
            continue
        if not actor.startswith("sub:"):
            continue
        if st["step_type"] == "llm_call":
            room[actor] = max(4000, 16000 // max(1, ncalls(st["result_summary"])))
            continue
        if st["step_type"] != "tool_call" or st["tool_name"] != "run":
            continue
        made = L.facts_in(vf._j(st["evidence_refs"]) or [])
        summ = st["result_summary"] or ""
        if not made and summ.startswith("error"):
            continue
        args = vf._j(st["args"]) or {}
        program = args.get("program") or {}
        returns = returns_of(program)
        raw = {"program_id": "calc_replay", "returns": returns, "nodes": nodes_of(summ),
               "settled": 0, "refused": [], "_facts": made}
        kept, note, held, _all = FA.adapt_all("run", args, raw)
        res = {**note, "facts": F.block_for_model(kept)} if kept else dict(note)
        if held:
            res["held_back"] = held
        cap = room.get(actor, 16000)
        before = dict(seen[actor])
        shown = dg.render(res, mint=dg.Minter(), seen=seen[actor], cap=cap, call={"tool": "run", "args": args})
        pre_chars = len(ejson.dumps(shown))
        text = ejson.dumps_capped(shown, cap, keep=sa._KEEP_LAST)
        (qdir / f"{st['seq']:03d}_{actor[4:]}_run.json").write_text(text, encoding="utf-8")
        in_text = set(_ID.findall(text))
        kept_ids = {f.id for f in kept}
        rendered = json.loads(text) if text.startswith("{") else {}
        folded = {n for b in rendered.get("boundaries") or [] for n in b.get("blocks") or []}
        said_nodes = {b.get("node") for b in rendered.get("boundaries") or [] if b.get("node")}
        also = {a for f in rendered.get("figures") or [] for a in f.get("also") or []}
        state = {}
        swallowed_unseen = 0
        for r in made:
            fid, node = r["id"], (r.get("params") or {}).get("node")
            if fid in in_text:
                state[fid] = "SHOWN"
            elif r.get("kind") == "absence" and (node in folded or (
                    (r.get("params") or {}).get("error") == "depends_on_refused"
                    and ((r.get("params") or {}).get("root") or {}).get("node") in said_nodes)):
                state[fid] = "FOLDED"          # said under the refusal that stopped it
            elif node is not None and node not in returns and r.get("kind") != "absence":
                state[fid] = "NOT_RETURNED"
            elif fid not in kept_ids:
                state[fid] = "HELD"
            elif fid in also:
                state[fid] = "TWIN"
            elif r.get("kind") == "scalar":
                model_value = F.row_for_model(F.from_record(r))[5]      # the reader-precision value the digest keys on
                key = (r.get("subject"), r.get("measure"), r.get("as_of"), str(dg.display(model_value, r.get("unit"))))
                first = before.get(key)
                if first is not None:
                    state[fid] = "REPEATED"
                    if first.get("id") not in shown_ids[actor]:
                        swallowed_unseen += 1
                else:
                    state[fid] = "CUT"
            else:
                state[fid] = "CUT" if r.get("kind") in ("series", "passage") else "LOST"
        lost = [(r.get("kind"), (r.get("params") or {}).get("node"), (r.get("text") or "")[:80])
                for r in made if state[r["id"]] == "LOST"]
        shown_ids[actor] |= in_text
        ret_nodes = {}
        for r in made:
            node = (r.get("params") or {}).get("node")
            if node in returns:
                ret_nodes.setdefault(node, Counter())[state[r["id"]]] += 1
        empty = (not any(rendered.get(k) for k in ("figures", "series", "passages", "boundaries", "repeated"))
                 and not any(e.get("kind") == "literal" for e in rendered.get("nodes") or []))
        rows.append({"tag": tag, "q": q, "seq": st["seq"], "actor": actor[4:], "cap": cap, "chars": len(text),
                     "pre_chars": pre_chars,
                     "made": len(made), "states": dict(Counter(state.values())), "returns": returns,
                     "return_states": {k: dict(v) for k, v in ret_nodes.items()},
                     "swallowed_unseen": swallowed_unseen, "empty": empty, "lost": lost,
                     "held_nodes": (held or {}).get("nodes"),
                     "returned_chars": len(json.dumps(F.block_for_model([F.from_record(r) for r in made
                                                                          if (r.get("params") or {}).get("node") in returns])))})


async def main():
    db, rj, tag, out_dir = sys.argv[1:5]
    rows: list = []
    eng = create_async_engine(vf._url(db))
    try:
        for conv in json.load(open(rj)):
            await one(eng, conv, tag, out_dir, rows)
    finally:
        await eng.dispose()
    Path(out_dir, f"{tag}_rows_v38.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    good = ("SHOWN", "REPEATED", "TWIN", "FOLDED")
    nodes = [(r["q"], r["seq"], n, st) for r in rows for n, st in r["return_states"].items()]
    unseen = [x for x in nodes if not any(k in good for k in x[3])]
    partial = [x for x in nodes if any(k not in good for k in x[3]) and any(k in good for k in x[3])]
    refusals_lost = sum(r["states"].get("LOST", 0) for r in rows)
    print(f"{tag}: {len(rows)} runs replayed; states {dict(sum((Counter(r['states']) for r in rows), Counter()))}")
    def over(x):
        big = next(r for r in rows if (r["q"], r["seq"]) == x[:2])
        return max(big["returned_chars"], big["pre_chars"]) > big["cap"]
    print(f"  returned nodes {len(nodes)}; none of it shown {len(unseen)}; partly shown {len(partial)}; "
          f"of those, the run's returned content was over the room: {sum(1 for x in unseen + partial if over(x))}")
    for x in unseen + partial:
        big = next(r for r in rows if (r['q'], r['seq']) == x[:2])
        over = "  OVER ROOM" if max(big["returned_chars"], big["pre_chars"]) > big["cap"] else ""
        print(f"    {x[0]} seq{x[1]} {x[2]}: {x[3]}  (returned facts {big['returned_chars']} chars, room {big['cap']}){over}")
    for r in rows:
        if r["states"].get("LOST"):
            print(f"    LOST in {r['q']} seq{r['seq']}: {r['lost']}")
    print(f"  swallowed although never shown: {sum(r['swallowed_unseen'] for r in rows)}; empty results: "
          f"{sum(1 for r in rows if r['empty'])}; facts nobody was told about: {refusals_lost}")


asyncio.run(main())
