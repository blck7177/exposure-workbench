#!/usr/bin/env python3
"""Run one program through program_service on a database and print the table.

    python scripts/program_run.py program.json [--db URL]      (default: exposure_gold)
    echo '{"let": [...]}' | python scripts/program_run.py -

Writes ledger rows (every node is one) and commits them: on exposure_gold that
is the point — the rows ARE the gold's derivation — and on the fixture the
battery restores before it runs.
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

from exposure_workbench.auth.context import current_user_ctx     # noqa: E402
from exposure_workbench.services import program_service as ps     # noqa: E402


def _default_db() -> str:
    u = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
    return u.replace("/exposure_workbench", "/exposure_gold")


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("program")
    ap.add_argument("--db", default=_default_db())
    ap.add_argument("--owner", default=os.getenv("BATTERY_OWNER_ID", "user_3IDBMeAxLTbecvGorzwV7FCeroR"))
    ap.add_argument("--facts", action="store_true", help="print the facts block too")
    args = ap.parse_args(argv)
    src = sys.stdin.read() if args.program == "-" else Path(args.program).read_text()
    program = json.loads(src)
    engine = create_async_engine(args.db)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(args.owner)
    try:
        async with mk() as db:
            out = await ps.run(db, program, invoked_by="program_run")
            await db.commit()
    finally:
        await engine.dispose()
    facts = out.pop("_facts", [])
    print(json.dumps(out, indent=1, default=str))
    if args.facts:
        for f in facts:
            print(f"  {f['id']} {f['kind']:7s} {str(f['subject']):14s} {f['measure']:45s} {f['unit'] or '':8s} {f['value'] if f['value'] is not None else ('%d pts' % len(f['points']) if f.get('points') else f.get('text','')[:60])}  as_of={f['as_of']} node={f['params'].get('node')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
