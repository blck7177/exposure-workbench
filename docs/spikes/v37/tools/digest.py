#!/usr/bin/env python3
"""One session as a flat, citable log: the lead's tasks line by line, each
analyst's calls with the program's bindings and parameters, what came back
(node kinds, absence texts), each brief (findings, not_done with the desk's
words, caveats, check problems), each gated answer with its problems.

    python digest.py <db> <round.json> <out_dir>
"""
import asyncio, json, os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(".env", override=True)
sys.path.insert(0, "src"); sys.path.insert(0, "scripts")
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text as sql
import v36_forensics as vf
from exposure_workbench.services import answer_check, ledger as ledger_svc

def j(x):
    return vf._j(x)

def short(v, n=160):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"

def expr_text(e):
    if not isinstance(e, dict):
        return short(e, 60)
    fn = e.get("fn")
    rest = {k: v for k, v in e.items() if k != "fn"}
    parts = []
    for k, v in rest.items():
        if isinstance(v, dict) and "fn" in v:
            parts.append(f"{k}={expr_text(v)}")
        elif isinstance(v, dict):
            parts.append(f"{k}={{" + ", ".join(f"{kk}:{expr_text(vv) if isinstance(vv, dict) and 'fn' in vv else short(vv, 40)}" for kk, vv in v.items()) + "}")
        else:
            parts.append(f"{k}={short(v, 50)}")
    return f"{fn}(" + ", ".join(parts) + ")"

def program_lines(args):
    prog = (args or {}).get("program") or {}
    lets = prog.get("let") or []
    out = []
    for b in lets:
        if isinstance(b, dict):
            out.append(f"      {b.get('name')} = {expr_text(b.get('expr'))}")
        elif isinstance(b, list) and len(b) == 2:
            out.append(f"      {b[0]} = {expr_text(b[1])}")
    if prog.get("return"):
        out.append(f"      return {prog.get('return')}")
    return out

def facts_of(st):
    refs = j(st["evidence_refs"]) or []
    return ledger_svc.facts_in(refs if isinstance(refs, list) else [])

def fact_short(r):
    p = r.get("params") or {}
    val = r.get("text") if r.get("kind") in ("absence", "passage", "task") else r.get("value")
    extra = " ".join(f"{k}={p[k]}" for k in ("node", "place", "of", "op") if p.get(k) not in (None, ""))
    pts = r.get("points")
    if r.get("kind") == "series" and pts:
        d0 = pts[0][0] if isinstance(pts[0], (list, tuple)) else pts[0]
        d1 = pts[-1][0] if isinstance(pts[-1], (list, tuple)) else pts[-1]
        val = f"series n={len(pts)} {d0}..{d1}"
    return f"{r['id']} {r.get('kind')} {r.get('measure')} [{r.get('subject')}] {short(val, 140)} {r.get('unit') or ''} {extra}"

async def one(eng, conv, out_dir, tagname):
    sid = conv["session_id"]
    t = conv["turns"][0]
    meta = j(t.get("meta"))
    steps = await vf._steps(eng, sid)
    async with eng.connect() as con:
        row = (await con.execute(sql("select content from agent_messages where session_id=:s and role='user' order by created_at limit 1"), {"s": sid})).first()
    question = row[0] if row else t.get("q")
    status = "ERROR" if t.get("error") else ("EXHAUSTED" if meta.get("gate") == "exhausted" else "ANSWERED")
    L = [f"## {conv['tag']}  [{tagname}]  {sid}  {status}", f"Q: {question}", ""]
    for st in steps:
        kind, tool, actor, a = st["step_type"], st["tool_name"], st["actor"] or "meta", j(st["args"])
        seq = st["seq"]
        if kind == "llm_call":
            rs = st["result_summary"] or ""
            rd = (a or {}).get("read") if isinstance(a, dict) else None
            L.append(f"[{seq}] {actor} completion p{st['prompt_tokens']}/c{st['completion_tokens']}"
                     + (f" read {rd.get('chars')}ch" if isinstance(rd, dict) else "") + f" → {rs.split(': ',1)[-1]}")
        elif kind == "delegate":
            for tk in (a or {}).get("tasks") or []:
                L.append(f"[{seq}] DELEGATE → {tk.get('domain')} subjects={tk.get('subjects')} constraints={short(tk.get('constraints') or {}, 200)}")
                if tk.get("context"):
                    L.append(f"      context: {short(tk.get('context'), 300)}")
                for w in tk.get("want_to_know") or []:
                    L.append(f"      - {short(w, 260)}")
        elif kind == "bad_delegate" or (kind == "delegate" and st["status"] != "completed"):
            L.append(f"[{seq}] BAD DELEGATE {short(st['result_summary'], 200)}")
        elif kind == "tool_call":
            L.append(f"[{seq}] {actor} → {tool} ({st['status']}) {short(st['result_summary'], 300)}")
            if tool == "run":
                L += program_lines(a)
            elif tool == "compile":
                L.append(f"      request: {short((a or {}).get('request'), 400)}")
            else:
                L.append(f"      args: {short(a, 300)}")
            fs = facts_of(st)
            kinds = {}
            for r in fs:
                kinds[r.get("kind")] = kinds.get(r.get("kind"), 0) + 1
            if fs:
                L.append(f"      facts minted: {kinds}")
        elif kind == "delegation":
            L.append(f"[{seq}] {actor} → {tool} ({st['status']}) args={short(a, 200)} → {short(st['result_summary'], 160)}")
        elif kind == "boundary":
            for r in facts_of(st):
                L.append(f"[{seq}] {actor} BOUNDARY {r['id']}: {short(r.get('text'), 420)}")
        elif kind == "brief":
            b = (a or {}).get("brief") or {}
            cov = (a or {}).get("coverage") or {}
            L.append(f"[{seq}] {actor} BRIEF {st['status']} coverage={cov}")
            for f in b.get("findings") or []:
                L.append(f"      finding w{f.get('want')}: {short(f.get('finding'), 500)}")
            for n in b.get("not_done") or []:
                L.append(f"      not_done w{n.get('want')}: {short(n.get('why'), 300)} | boundary={n.get('boundary')}")
            for c in b.get("caveats") or []:
                L.append(f"      caveat: {short(c, 300)}")
            for p in (a or {}).get("problems") or []:
                if isinstance(p, dict):
                    L.append(f"      PROBLEM {p.get('where')} {p.get('reason')} {short(p.get('figure') or p.get('id') or p.get('word') or p.get('phrase') or '', 40)} :: {short(p.get('fix'), 220)}")
            if set(a or {}) == {"task_id"}:
                L.append(f"      (fallback: {short(st['result_summary'], 120)})")
        elif kind == "report":
            L.append(f"[{seq}] {actor} REPORT {short(st['result_summary'], 160)}")
        elif kind == "read_report":
            L.append(f"[{seq}] meta READ_REPORT {short(a, 80)} → {short(st['result_summary'], 160)}")
        elif kind == "answer":
            text = (a or {}).get("text") or ""
            led = vf._ledger_before(steps, seq)
            v = answer_check.check(text, led, question=question)
            L.append(f"[{seq}] meta ANSWER {st['status']} ({len(text)}ch) replay ok={v.ok} problems={len(v.problems)}")
            for p in v.problems:
                L.append(f"      PROBLEM {p.get('at')} {p.get('reason')} {short(p.get('figure') or p.get('id') or p.get('word') or p.get('phrase') or p.get('quote') or '', 60)} :: {short(p.get('fix'), 220)}")
        else:
            L.append(f"[{seq}] {actor} {kind} {tool} {st['status']} {short(st['result_summary'], 200)}")
    L.append("")
    L.append(f"FINAL ({status}): {short(t.get('answer') or t.get('error') or '', 3000)}")
    L.append(f"meta.gate_refusals={meta.get('gate_refusals')}")
    out = Path(out_dir) / f"{conv['tag'][:3]}_{tagname}.txt"
    out.write_text("\n".join(L), encoding="utf-8")
    return out

async def main():
    db, rj, out_dir, tagname = sys.argv[1:5]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    eng = create_async_engine(vf._url(db))
    try:
        for conv in json.load(open(rj)):
            await one(eng, conv, out_dir, tagname)
    finally:
        await eng.dispose()
    print("done", out_dir)

asyncio.run(main())
