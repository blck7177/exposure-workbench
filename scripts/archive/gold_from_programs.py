#!/usr/bin/env python3
"""Gold from ideal programs (V30 Phase A): execute every program under
tests/battery/programs_<set>/ on exposure_gold and write tests/battery/gold_<set>.json.

A program file is {"tag": "W01-…#t1", "program": {...}, "must": ["node", …],
"note": "…"} or {"tag": …, "skip": "reason"}. The gold figures of a turn are
the values of its returned nodes — scalars as one figure each, vectors and
rankings as one figure per entry — with `must` marking the nodes the question
is directly about. Absences are recorded as skip-with-reason for that node.

    python scripts/gold_from_programs.py v26 [--only TAG] [--db URL]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.auth.context import current_user_ctx           # noqa: E402
from exposure_workbench.services import program_service as ps           # noqa: E402


def _default_db() -> str:
    u = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
    return u.replace("/exposure_workbench", "/exposure_gold")


def _figures(nodes: dict, returns: list[str], must: list[str]) -> tuple[list[dict], list[str]]:
    figs, absent = [], []
    for name in returns:
        n = nodes.get(name) or {}
        is_must = name in must
        if n.get("kind") == "scalar" and n.get("value") is not None:
            figs.append({"key": name, "value": n["value"], "unit": n.get("unit"), "subject": n.get("subject"),
                         "must": is_must, "note": n.get("measure") or ""})
        elif n.get("kind") in ("vector", "ranking", "table"):
            for label, e in (n.get("entries") or {}).items():
                figs.append({"key": f"{name}.{label}", "value": e["value"], "unit": e.get("unit") or n.get("unit"),
                             "subject": label, "must": is_must, "note": n.get("measure") or ""})
        elif n.get("kind") == "series":
            pass                                     # a series is pointed at, not matched by value
        elif n.get("kind") == "absence":
            absent.append(f"{name}: {(n.get('refusal') or {}).get('error')}")
    return figs, absent


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("set")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--db", default=_default_db())
    args = ap.parse_args(argv)
    folder = ROOT / "tests" / "battery" / f"programs_{args.set}"
    out_path = ROOT / "tests" / "battery" / f"gold_{args.set}.json"
    gold = json.loads(out_path.read_text()) if out_path.exists() else {}
    engine = create_async_engine(args.db)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(os.getenv("BATTERY_OWNER_ID", "user_3IDBMeAxLTbecvGorzwV7FCeroR"))
    n_ok = n_skip = n_fail = 0
    try:
        for f in sorted(folder.glob("*.json")):
            spec = json.loads(f.read_text())
            tag = spec["tag"]
            if args.only and tag not in args.only:
                continue
            if spec.get("skip"):
                gold[tag] = {"figures": [], "identity": [], "derived_by": f"programs/{f.name}", "skip": spec["skip"]}
                n_skip += 1
                print(f"[{tag}] skip: {spec['skip']}")
                continue
            async with mk() as db:
                out = await ps.run(db, spec["program"], invoked_by="gold")
                await db.rollback()
            if out.get("error"):
                n_fail += 1
                print(f"[{tag}] FAILED {out['error']}: {out.get('detail')}", file=sys.stderr)
                continue
            figs, absent = _figures(out["nodes"], out["returns"], spec.get("must") or out["returns"])
            gold[tag] = {"figures": figs, "identity": [], "derived_by": f"programs/{f.name}",
                         "skip": None if figs else ("no figure resolved: " + "; ".join(absent) if absent else "no returned figures"),
                         **({"absent": absent} if absent else {}), "note": spec.get("note", "")}
            n_ok += 1
            musts = [x for x in figs if x["must"]]
            print(f"[{tag}] {len(figs)} figures ({len(musts)} must){'; absent ' + ', '.join(absent) if absent else ''}")
    finally:
        await engine.dispose()
    out_path.write_text(json.dumps(gold, indent=1, ensure_ascii=False))
    print(f"written {out_path}: {n_ok} derived, {n_skip} skipped, {n_fail} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
