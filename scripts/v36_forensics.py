#!/usr/bin/env python3
"""V36 — a round read as COMMUNICATION between nodes.

What a round is judged by, since 2026-09-15: how many times each pair of nodes
talked, what each message carried, and under what schema. A step table ordered
by seq does not answer that — a `run` call looks the same whichever agent made
it, and the two questions a design review actually asks ("did this round trip
contribute anything?", "was the intent readable at the other end?") need the
direction and the payload's shape beside each other.

So each row here is an EDGE: from → to, the carrier, the size, the top-level
keys of what was sent, and a one-line summary. Per turn it prints the table,
the per-pair counts, and a replay of every gated step (`answer`, `brief`) on
the ledger AS IT STOOD AT THAT STEP — a replay on the session's final ledger
misreads early refusals (V32), so the ledger is rebuilt from the evidence_refs
of the completed steps before it, which is exactly what the check read.

`--samples` prints one full payload per distinct carrier: that is the schema
half of the reading, taken from the round rather than from the source.

    python scripts/v36_forensics.py docs/spikes/v33/V33J.json --out /tmp/J.txt
    python scripts/v36_forensics.py docs/spikes/v36/V36A.json --out ... --samples ...

Reads V35 rounds too: rows written before the `actor` column are the lead
analyst's by definition, and in a V35 session the tool calls were the broker's
(the session's own `request`/`digest` steps are what say so).

ONE ATTRIBUTION IS INFERRED, and it is worth knowing which. A `tool_call` row is
written by the registry wrapper, which lives behind the MCP door and is not told
who is calling — the bearer carries the session and the message, not the actor.
So an actor-less tool call in a V36 session is attributed to the analyst that
spoke last, which is exact while analysts run one at a time and stops being
exact the moment they run in parallel (Phase 3). The fix belongs in the token,
not here; until it exists the inferred rows are marked with `~`.
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

# The nodes of the architecture, as the design names them. `ctx` is not an
# agent: it is what a completion read, and a completion is a node working
# rather than two nodes talking — printed with no arrow, so the table never
# implies an edge that is not one.
LEAD = "meta"
CTX = "ctx"


def _url(db: str) -> str:
    return os.environ["DATABASE_URL_LOCAL"].replace("/exposure_workbench", "/" + db)


def _j(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:  # noqa: BLE001
            return {"_raw": x}
    return x if isinstance(x, (dict, list)) else {}


async def _steps(engine, session_id: str) -> list[dict]:
    async with engine.connect() as con:
        rows = (await con.execute(sql(
            "select seq, step_type, tool_name, actor, status, args, result_summary, evidence_refs, "
            "       prompt_tokens, completion_tokens, message_id "
            "from agent_steps where session_id = :s order by seq"), {"s": session_id})).all()
    return [dict(r._mapping) for r in rows]


def _ledger_before(steps: list[dict], seq: int):
    """The ledger the check read at that step: the facts of every completed step
    before it (v35_forensics._ledger_before, kept identical on purpose)."""
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


def _short_actor(actor: str | None, legacy_caller: str) -> str:
    if not actor:
        return legacy_caller
    return actor if not actor.startswith("sub:") else "sub:" + actor[4:][:22]


def _edge(st: dict, legacy_caller: str, speaking: str | None = None) -> tuple[str, str | None, str]:
    """(from, to, carrier). `to` is None for a completion: one node working."""
    kind, tool, actor = st["step_type"], st["tool_name"], st["actor"]
    fallback = LEAD if kind == "llm_call" else (speaking or legacy_caller)
    who = _short_actor(actor, fallback)
    if kind == "llm_call":
        return (CTX, None, "completion")
    if kind == "request":                       # V35: the analyst's evidence request
        return (LEAD, "broker", "request_evidence")
    if kind == "digest":                        # V35: the broker's answer to it
        return ("broker", LEAD, "digest")
    if kind == "boundary":                      # V36: what the desk could not do, put on the ledger
        return (who, "ledger", "boundaries")
    if kind == "delegate":                      # V36
        return (LEAD, "sub", "delegate")
    if kind == "brief":                         # V36: the sub-analyst's submission
        return (who, "check", "submit")
    if kind == "report":                        # V36: the verified report, stored
        return (who, "store", "report")
    if kind == "read_report":                   # V36.1: the lead opening a report (was inferred before)
        return (LEAD, "store", "read_report")
    if kind in ("answer", "respond"):
        return (LEAD, "gate", kind)
    if kind == "delegation":                    # a background task was registered
        return (who, "worker", tool or kind)
    if kind == "tool_call":
        return (who, "tools", tool or "tool")
    return (who, None, kind)


def _keys(args) -> str:
    a = _j(args)
    if isinstance(a, dict):
        return ",".join(list(a)[:6]) or "-"
    return "-"


def _summary(st: dict, args: dict) -> str:
    kind = st["step_type"]
    if kind == "llm_call":
        return str(st["result_summary"] or "")
    if kind == "request":
        items = args.get("items") or []
        return "; ".join(
            f"[{','.join(i.get('subjects') or [])}] want {','.join(i.get('want') or [])}"
            + (f" window {i['window']}" if i.get("window") else "")
            + (f" compare {i['compare']}" if i.get("compare") else "")
            + (f" derive×{len(i['derive'])}" if i.get("derive") else "")
            + (" ask✓" if i.get("ask") else "")
            for i in items if isinstance(i, dict))
    if kind == "delegate":
        tasks = args.get("tasks") or []
        return "; ".join(
            f"{t.get('domain')} [{','.join(t.get('subjects') or [])}] "
            f"{len(t.get('want_to_know') or [])} line(s)"
            + (f" +{len(t['facts_to_derive'])} derive" if t.get("facts_to_derive") else "")
            for t in tasks if isinstance(t, dict))
    if kind == "brief":
        cov = args.get("coverage") or {}
        probs = args.get("problems") or []
        return (f"coverage {cov.get('done', '?')}/{cov.get('asked', '?')}"
                f" not_done {cov.get('not_done', 0)} refused {cov.get('refused', 0)}"
                f" · {st['status']}"
                + (f" · {len(probs)} problem(s): " + ", ".join(sorted({str(p.get('reason')) for p in probs if isinstance(p, dict)})[:4])
                   if probs else ""))
    return str(st["result_summary"] or "")


def _sizes(st: dict, args) -> str:
    if st["step_type"] == "llm_call":
        read = (args or {}).get("read") if isinstance(args, dict) else None
        tail = f" · read {read.get('chars')} ch/{read.get('results')} res" if isinstance(read, dict) else ""
        return f"p{st['prompt_tokens'] or 0}/c{st['completion_tokens'] or 0} tok{tail}"
    n_args = len(args if isinstance(args, str) else json.dumps(args, ensure_ascii=False, default=str))
    n_res = len(st["result_summary"] or "")
    return f"in {n_args} · out {n_res}"


def _legacy_caller(steps: list[dict]) -> str:
    """Who made the tool calls of a session whose rows predate `actor`. A V35
    session is the one that has request/digest steps, and in it every tool call
    was the broker's; anything else is the loop that owns the session."""
    return "broker" if any(s["step_type"] in ("request", "digest") for s in steps) else LEAD


def _one_line(p: dict) -> str:
    what = p.get("figure") or p.get("id") or p.get("node") or p.get("quote") or p.get("word") or p.get("phrase") or ""
    extra = ""
    if p.get("candidates"):
        extra = " → " + str([f"{c.get('id')} {c.get('measure')} {c.get('subject')}" for c in p["candidates"][:4]])
    if p.get("holds"):
        extra += f" holds={p['holds']!r}"
    return f"- {p.get('at')} {p['reason']} {what!r}{extra}  fix={str(p.get('fix') or '')[:130]}"


def _table(rows: list[tuple]) -> list[str]:
    if not rows:
        return ["  (no steps)"]
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return ["  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows]


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round_json")
    ap.add_argument("--db", default=os.getenv("BATTERY_DB", "exposure_battery"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--samples", help="write one full payload per distinct carrier here")
    ap.add_argument("--only", action="append", default=[], help="only these tags")
    args = ap.parse_args(argv)

    data = json.load(open(args.round_json))
    if args.only:
        data = [c for c in data if any(o in c["tag"] for o in args.only)]
    engine = create_async_engine(_url(args.db))
    out: list[str] = []
    pairs_total: collections.Counter = collections.Counter()
    carriers_total: collections.Counter = collections.Counter()
    samples: dict[str, dict] = {}
    problem_counts: collections.Counter = collections.Counter()

    try:
        for convo in data:
            sid = convo["session_id"]
            steps = await _steps(engine, sid)
            legacy = _legacy_caller(steps)
            by_msg: dict[str | None, list[dict]] = collections.defaultdict(list)
            for st in steps:
                by_msg[st["message_id"]].append(st)

            for t in convo["turns"]:
                meta = _j(t.get("meta"))
                turn_steps = steps if len(convo["turns"]) == 1 and len(by_msg) <= 1 else None
                if turn_steps is None:
                    # one turn = one message id; the round file does not carry it,
                    # so take the message ids in order of first seq
                    order = sorted(by_msg, key=lambda m: min(s["seq"] for s in by_msg[m]))
                    idx = (t.get("turn") or 1) - 1
                    turn_steps = by_msg[order[idx]] if idx < len(order) else []

                out.append(f"## {convo['tag']}  session={sid}  elapsed={t.get('elapsed_s')}s")
                out.append(f"Q: {t['q']}")
                out.append(f"meta: {json.dumps(meta, ensure_ascii=False)[:400]}")
                out.append("--- 沟通表 ---")
                rows = [("seq", "from", "→", "to", "carrier", "status", "size", "schema keys", "content")]
                pairs: collections.Counter = collections.Counter()
                completions: collections.Counter = collections.Counter()
                speaking: str | None = None          # the analyst whose turn it is; see the module docstring
                for st in turn_steps:
                    if st["actor"]:
                        speaking = _short_actor(st["actor"], LEAD)
                    elif st["step_type"] in ("delegate", "answer", "respond"):
                        speaking = None              # the lead took the floor back
                    frm, to, carrier = _edge(st, legacy, speaking)
                    inferred = "~" if (st["actor"] is None and speaking and st["step_type"] != "llm_call") else ""
                    a = _j(st["args"])
                    if to is None:
                        completions[_short_actor(st["actor"], LEAD)] += 1
                    else:
                        pairs[f"{frm} → {to}"] += 1
                        pairs_total[f"{frm} → {to}"] += 1
                        carriers_total[carrier] += 1
                        samples.setdefault(f"{frm} → {to} · {carrier}",
                                           {"tag": convo["tag"], "seq": st["seq"], "args": a,
                                            "result_summary": st["result_summary"]})
                    rows.append((st["seq"], inferred + frm, "·" if to is None else "→",
                                 to or _short_actor(st["actor"], LEAD), carrier, st["status"],
                                 _sizes(st, st["args"]), _keys(st["args"]), _summary(st, a)[:150]))
                out += _table(rows)

                out.append("--- 往返计数 ---")
                out += ["  " + f"{k:<24} {v}" for k, v in sorted(pairs.items())]
                out.append("  " + "completions              " + " · ".join(f"{k} {v}" for k, v in sorted(completions.items())))

                gated = [s for s in turn_steps if s["step_type"] in ("answer", "brief")]
                if gated:
                    out.append("--- 当步账本重放 ---")
                for st in gated:
                    a = _j(st["args"])
                    text = a.get("text") or ""
                    if st["step_type"] == "brief":
                        text = "\n".join(f.get("finding", "") for f in (a.get("brief") or {}).get("findings") or [])
                    led = _ledger_before(turn_steps, st["seq"])
                    v = answer_check.check(text, led, question=t["q"]) if text else None
                    kinds = collections.Counter(r.get("kind") for r in led.by_id.values())
                    out.append(f"  [{st['seq']:>3}] {st['step_type'].upper()} {st['status']}  "
                               f"ledger {len(led.by_id)} facts {dict(kinds)}")
                    out.append("        text: " + text.replace("\n", " ⏎ ")[:900])
                    if v is not None:
                        out.append(f"        replay: ok={v.ok} error={v.error} problems={len(v.problems)}")
                        for p in v.problems:
                            out.append("          " + _one_line(p))
                            problem_counts[p["reason"]] += 1
                out.append("")
    finally:
        await engine.dispose()

    out.append("=== 全轮往返计数 ===")
    for k, v in pairs_total.most_common():
        out.append(f"{k:<28} {v}")
    out.append("=== 载体 ===")
    for k, v in carriers_total.most_common():
        out.append(f"{k:<28} {v}")
    if problem_counts:
        out.append("=== 重放问题 ===")
        for k, v in problem_counts.most_common():
            out.append(f"{k:<28} {v}")
    Path(args.out).write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {args.out}  ({len(out)} lines)")

    if args.samples:
        s: list[str] = ["# 每种沟通的 schema：取自本轮的真实载荷", ""]
        for key, sample in sorted(samples.items()):
            s.append(f"## {key}")
            s.append(f"（{sample['tag']} seq {sample['seq']}）")
            s.append("```json")
            s.append(json.dumps(sample["args"], ensure_ascii=False, indent=1, default=str)[:4000])
            s.append("```")
            if sample["result_summary"]:
                s.append(f"→ {str(sample['result_summary'])[:400]}")
            s.append("")
        Path(args.samples).write_text("\n".join(s), encoding="utf-8")
        print(f"wrote {args.samples}  ({len(samples)} carriers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
