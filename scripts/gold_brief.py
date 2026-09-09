#!/usr/bin/env python3
"""Gold for the brief battery: what the desk's own issuer domains produce.

    python scripts/gold_brief.py [--tickers NVDA,MSFT] [--db URL]
    -> tests/battery/gold_brief.json

A brief has no single question, so its gold cannot be "the answer to the turn".
What it can be is this: the seven issuer domains are the desk's statement of what
an analyst looks at for an issuer, each one carrying the programs that answer it
(analytics.skill.Procedure.programs). Run them and the settled nodes are the
figures a complete brief could have rested on.

This is a RECALL denominator, not a checklist. A brief that renders 40% of them
is not 60% wrong — a brief is six sections, not thirty figures, and an analyst
chooses. The number is comparable across arms of the same battery, which is the
only claim made for it.

A node that refuses on this issuer is recorded with its reason rather than
dropped, so the denominator does not quietly shrink where the data is thin.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.analytics import skill                       # noqa: E402
from exposure_workbench.auth.context import current_user_ctx         # noqa: E402
from exposure_workbench.db.models import Company                     # noqa: E402
from exposure_workbench.services import program_service as ps        # noqa: E402

OUT = ROOT / "tests" / "battery" / "gold_brief.json"


def _figures(fact: dict) -> list[tuple[str, float]]:
    """(label, value) for every figure one Fact puts on the table.

    Read from the executor's own Facts rather than the node table: a Fact is
    what the model is shown and what a brief's rendered figure is compared
    against, and a vector is already one Fact per entry.
    """
    measure, subject = fact.get("measure") or "", fact.get("subject") or ""
    label = f"{subject}.{measure}" if subject else measure
    if fact.get("kind") == "scalar" and fact.get("value") is not None:
        return [(label, float(fact["value"]))]
    if fact.get("kind") == "series":
        return [(f"{label}@{p[0]}", float(p[1])) for p in (fact.get("points") or [])]
    return []


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=None)
    ap.add_argument("--db", default=os.getenv("DATABASE_URL_LOCAL",
                    "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench").replace(
                        "/exposure_workbench", "/exposure_gold"))
    ap.add_argument("--owner", default=os.getenv("BATTERY_OWNER_ID", "user_3IDBMeAxLTbecvGorzwV7FCeroR"))
    args = ap.parse_args(argv)

    engine = create_async_engine(args.db)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(args.owner)
    domains = [p for p in skill.PROCEDURES.values() if p.subject_kind == "issuer"]
    gold: dict[str, dict] = {}
    try:
        async with mk() as db:
            if args.tickers:
                tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
            else:
                tickers = [t for (t,) in (await db.execute(
                    select(Company.ticker).where(Company.is_investigable.is_(True)).order_by(Company.ticker))).all()]
            for tk in tickers:
                figures: dict[str, float] = {}
                refused: dict[str, str] = {}
                for proc in domains:
                    for title, prog in proc.programs:
                        text = prog.replace("<T1>", tk).replace("<T2>", tk).replace("<T>", tk)
                        out = await ps.run(db, json.loads(text), invoked_by="gold_brief")
                        await db.rollback()
                        if out.get("error"):
                            refused[f"{proc.name}/{title}"] = out["error"]
                            continue
                        for name, node in (out.get("nodes") or {}).items():
                            if not name.startswith("_") and node.get("kind") == "absence":
                                refused[f"{proc.name}/{name}"] = (node.get("refusal") or {}).get("error", "refused")
                        for fact in (out.get("_facts") or []):
                            node_name = (fact.get("params") or {}).get("node") or ""
                            if node_name.startswith("_"):
                                continue
                            for label, value in _figures(fact):
                                figures[f"{proc.name}.{node_name}:{label}"] = value
                gold[tk] = {"figures": figures, "refused": refused,
                            "domains": [p.name for p in domains]}
                print(f"{tk:6s} {len(figures):4d} figures, {len(refused)} node(s)/program(s) refused", flush=True)
    finally:
        await engine.dispose()

    OUT.write_text(json.dumps(gold, indent=1, default=str))
    tot = sum(len(v["figures"]) for v in gold.values())
    print(f"\nwritten {OUT.relative_to(ROOT)} — {len(gold)} issuer(s), {tot} figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
