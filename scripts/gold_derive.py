#!/usr/bin/env python3
"""Derive a battery set's gold figures on the fixture database (see scripts/gold/__init__.py).

    python scripts/gold_derive.py v24 [--only TAG] [--db URL]

Runs as the desk's owner role on exposure_gold — the same snapshot as the
battery's fixture, in a database of its own so a derivation never holds the
fixture open across a restore (bypasses RLS: gold is the desk's own answer). Writes tests/battery/gold_<set>.json.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from exposure_workbench.auth.context import current_user_ctx   # noqa: E402

OWNER = os.getenv("BATTERY_OWNER_ID", "user_3IDBMeAxLTbecvGorzwV7FCeroR")


def _fixture_url() -> str:
    u = os.getenv("DATABASE_URL_LOCAL", "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench")
    return u.replace("/exposure_workbench", "/exposure_gold")


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("set", help="v21 | v24 | v26")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--db", default=_fixture_url())
    args = ap.parse_args(argv)
    mod = importlib.import_module(f"scripts.gold.{args.set}")
    derivations = mod.DERIVATIONS
    tags = [t for t in derivations if not args.only or t in args.only]
    out_path = ROOT / "tests" / "battery" / f"gold_{args.set}.json"
    existing = json.loads(out_path.read_text()) if out_path.exists() else {}
    engine = create_async_engine(args.db)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(OWNER)
    try:
        for tag in tags:
            async with mk() as db:
                try:
                    gold = await derivations[tag](db)
                    await db.rollback()          # derivations never persist on the fixture
                except Exception as exc:         # noqa: BLE001 — recorded, the set continues
                    print(f"[{tag}] FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
                    continue
            d = gold.as_dict()
            d["derived_by"] = d.get("derived_by") or f"gold.{args.set}:{derivations[tag].__name__}"
            existing[tag] = d
            figs = ", ".join(f"{f['key']}={f['value']:.6g}" for f in d["figures"]) if d["figures"] else f"skip: {d['skip']}"
            print(f"[{tag}] {figs}")
    finally:
        await engine.dispose()
    out_path.write_text(json.dumps(existing, indent=1, ensure_ascii=False))
    print(f"written {out_path} ({len(existing)} turns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
