#!/usr/bin/env python3
"""A round's answers file and audit file (the V36A/V36B *_answers.txt and
*_audit.txt shapes), rebuilt because the script that wrote those was never
committed.

answers: every turn, its status and the prose the reader saw.
audit:   every ANSWERED turn, the text the gate accepted WITH its brackets
         (from the completed `answer` step, not the capped copy in the round
         file), then every fact it cites: kind, measure, subject, value or
         text, unit, as_of, window, and for a series its point count, spacing
         and first..last date, plus the rank/node params. A cited id missing
         from the `facts` table is flagged, with whether the ledger holds it.

    python credit/v37c_audit.py docs/spikes/v37/V37C.json --answers ... --audit ...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import create_async_engine

load_dotenv(".env", override=True)
sys.path.insert(0, "src")
from exposure_workbench.services import facts as F, ledger as ledger_svc  # noqa: E402

FID = re.compile(r"\bf_[0-9a-f]{12}\b")


def _j(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:  # noqa: BLE001
            return {}
    return x if isinstance(x, (dict, list)) else {}


def _status(t: dict) -> str:
    meta = _j(t.get("meta"))
    if t.get("error"):
        return "ERROR"
    if meta.get("gate") == "exhausted":
        return "EXHAUSTED"
    if "gate" in meta:
        return "GATE:" + str(meta.get("gate"))
    return "ANSWERED" if t.get("answer") else "EMPTY"


def _num(v):
    if v is None:
        return ""
    return f"{v:.6g}" if isinstance(v, float) else str(v)


def _fact_line(r: dict, on_ledger: bool | None) -> str:
    p = r.get("params") or {}
    kind = r.get("kind") or ""
    cols = [r["id"], kind[:7], (r.get("measure") or "")[:44], (r.get("subject") or "")[:34]]
    if kind in ("passage", "absence", "task"):
        cols.append(repr((r.get("text") or "")[:110]))
    else:
        cols.append(_num(r.get("value")))
    cols.append(r.get("unit") or "")
    cols.append(r.get("as_of") or "")
    w = r.get("window")
    if w:
        cols.append("window=" + json.dumps(w, separators=(",", ":"))[:60])
    pts = r.get("points")
    if kind == "series" and pts:
        dates = [x[0] if isinstance(x, (list, tuple)) else (x.get("date") or x.get("at")) for x in pts]
        cols.append(f"series n={len(pts)} spacing={F.spacing_of(pts)} {dates[0]}..{dates[-1]}")
    extra = " ".join(f"{k}={p[k]}" for k in ("node", "place", "of", "label", "method", "op") if p.get(k) not in (None, ""))
    if extra:
        cols.append(extra)
    line = "  " + "  ".join(str(c) for c in cols if c != "")
    if on_ledger is not None:
        line += f"   <<< NOT IN FACTS TABLE (ledger holds it: {'yes' if on_ledger else 'no'})"
    return line


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("round_json")
    ap.add_argument("--db", default=os.getenv("BATTERY_DB", "exposure_battery"))
    ap.add_argument("--answers", required=True)
    ap.add_argument("--audit", required=True)
    args = ap.parse_args(argv)
    data = json.load(open(args.round_json))
    engine = create_async_engine(os.environ["DATABASE_URL_LOCAL"].replace("/exposure_workbench", "/" + args.db))
    answers, audit = [], []
    try:
        async with engine.connect() as con:
            for c in data:
                sid = c["session_id"]
                for t in c["turns"]:
                    st = _status(t)
                    answers += [f"## {c['tag']}  session={sid}  {st}", f"Q: {t['q']}",
                                str(t.get("answer") or t.get("error") or ""), ""]
                    if st != "ANSWERED":
                        continue
                    steps = [dict(r._mapping) for r in (await con.execute(sql(
                        "select seq, step_type, status, args, evidence_refs from agent_steps "
                        "where session_id=:s order by seq"), {"s": sid})).all()]
                    accepted = [s for s in steps if s["step_type"] == "answer" and s["status"] == "completed"]
                    marked = (_j(accepted[-1]["args"]).get("text") if accepted else None) or t.get("answer") or ""
                    ids = list(dict.fromkeys(list(t.get("citations") or []) + FID.findall(marked)))
                    rows = {r._mapping["id"]: dict(r._mapping) for r in (await con.execute(sql(
                        'select id, kind, measure, subject, unit, value, points, text, as_of, "window", params '
                        "from facts where id = any(:ids)"), {"ids": ids})).all()}
                    ledger = {}
                    for s in steps:
                        if s["status"] == "completed":
                            for rec in ledger_svc.facts_in(_j(s["evidence_refs"]) or []):
                                ledger[rec["id"]] = rec
                    audit += [f"## {c['tag']}  session={sid}", f"Q: {t['q']}",
                              "ANSWER (as the gate accepted it, brackets kept):", marked,
                              "--- the facts it cited ---"]
                    for fid in ids:
                        if fid in rows:
                            audit.append(_fact_line(rows[fid], None))
                        elif fid in ledger:
                            audit.append(_fact_line(ledger[fid], True))
                        else:
                            audit.append(f"  {fid}   <<< NOT IN FACTS TABLE (ledger holds it: no)")
                    audit.append("")
    finally:
        await engine.dispose()
    Path(args.answers).write_text("\n".join(answers), encoding="utf-8")
    Path(args.audit).write_text("\n".join(audit), encoding="utf-8")
    print(f"wrote {args.answers} and {args.audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
