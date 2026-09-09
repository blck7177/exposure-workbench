#!/usr/bin/env python3
"""Replay every refused respond of a battery through the claims gate against
its session's ledger, and tally the reasons (the step summary carries only the
code). Read-only on the database the battery ran against.

    python scripts/v30_replay_refusals.py docs/spikes/v30/V21_B1.json [--db URL]
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.db.models import AgentStep          # noqa: E402
from exposure_workbench.services import claims, ledger      # noqa: E402


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("battery")
    ap.add_argument("--db", default=os.getenv("DATABASE_URL_LOCAL").replace("/exposure_workbench", "/" + os.getenv("BATTERY_DB", "exposure_gold")))
    ap.add_argument("--examples", type=int, default=3)
    args = ap.parse_args(argv)
    convos = json.loads(Path(args.battery).read_text())
    engine = create_async_engine(args.db)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    reasons: collections.Counter = collections.Counter()
    by_relation: collections.Counter = collections.Counter()
    examples: dict[str, list] = collections.defaultdict(list)
    n = 0
    try:
        async with mk() as db:
            for c in convos:
                sid = c.get("session_id")
                if not sid:
                    continue
                led = await ledger.load(db, sid)
                rows = (await db.execute(select(AgentStep).where(AgentStep.session_id == sid, AgentStep.tool_name == "respond")
                                         .order_by(AgentStep.seq))).scalars().all()
                for st in rows:
                    if not (st.result_summary or "").startswith("error"):
                        continue
                    a = st.args if isinstance(st.args, dict) else json.loads(st.args or "{}")
                    if "claims" not in a:
                        continue
                    v = claims.check({"claims": a.get("claims") or [], "prose": a.get("prose") or []}, led)
                    n += 1
                    if v.ok:
                        reasons["(passes now)"] += 1
                        continue
                    for p in v.problems:
                        key = f"{v.error}:{p.get('reason')}"
                        reasons[key] += 1
                        if p.get("relation"):
                            by_relation[f"{p['relation']}:{p.get('reason')}"] += 1
                        if len(examples[key]) < args.examples:
                            examples[key].append((c["tag"], str(p.get("detail") or p.get("figure") or p.get("id"))[:160]))
    finally:
        await engine.dispose()
    print(f"{n} refused responds replayed")
    for k, v in reasons.most_common():
        print(f"  {v:4d}  {k}")
        for tag, d in examples.get(k, []):
            print(f"          {tag}: {d}")
    if by_relation:
        print("by relation:")
        for k, v in by_relation.most_common():
            print(f"  {v:4d}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
