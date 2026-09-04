#!/usr/bin/env python3
"""Drive the real meta-agent through multi-TURN conversations and capture them.

`agent_battery.py` asks one question in one session: a good instrument for
"can it answer this", and blind to everything a conversation does — a
follow-up that says "and the other two?", a pronoun pointing at the previous
answer, a second question that only makes sense if the first was understood.
A desk is used in conversations, so it has to be measured in conversations.

One session per conversation; a turn claimed and released around every
message, exactly as the route does, so each turn gets its own 15-call budget
and the session accumulates history the way a real chat does. Conversations
run concurrently (each is its own session, and the turn lock is per session);
turns inside one conversation are strictly ordered.

Input: JSON [{"tag": "...", "turns": ["...", "..."]}, ...]
Output: JSON [{"tag", "session_id", "turns": [{"q", "answer", "blocks",
        "citations", "meta", "elapsed_s", "steps"}]}]

    python scripts/conversation_battery.py convos.json out.json --owner user_… [--concurrency 3]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.agents.meta_agent import handle_message   # noqa: E402
from exposure_workbench.auth.context import current_user_ctx      # noqa: E402
from exposure_workbench.services import agent_session_service as sess   # noqa: E402

URL = os.getenv("DATABASE_URL_RLS",
                "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")

_STEPS = text(
    "SELECT seq, step_type, tool_name, status, left(result_summary, 200) AS result, "
    "       left(args::text, 300) AS args, prompt_tokens, completion_tokens "
    "FROM agent_steps WHERE session_id = :s AND message_id = :m ORDER BY seq")

_RELEASE = text("UPDATE agent_sessions SET turn_started_at = NULL WHERE id = :s")


async def _run_conversation(mk, owner: str, tag: str, turns: list[str]) -> dict:
    current_user_ctx.set(owner)
    async with mk() as db:
        session = await sess.create_session(db, kind="meta", owner_id=owner)
        sid = session.id
        await db.commit()

    out: list[dict] = []
    for i, q in enumerate(turns, 1):
        async with mk() as db:
            claimed = await sess.claim_turn(db, sid)
            await db.commit()
        if claimed is None:
            out.append({"q": q, "error": "turn already in flight", "steps": []})
            break
        started = time.time()
        try:
            res = await handle_message(lambda: mk(), sid, q)
            error = None
        except Exception as exc:                    # noqa: BLE001 — recorded, not raised
            res, error = {}, f"{type(exc).__name__}: {exc}"
        elapsed = round(time.time() - started, 1)
        async with mk() as db:
            await db.execute(_RELEASE, {"s": sid})
            await db.commit()
        mid = res.get("message_id")
        steps = []
        if mid:
            async with mk() as db:
                steps = [dict(r) for r in (await db.execute(_STEPS, {"s": sid, "m": mid})).mappings().all()]
        meta = res.get("meta", {})
        out.append({"turn": i, "q": q, "error": error, "answer": res.get("text"),
                    "citations": res.get("citations", []), "blocks": meta.get("blocks"),
                    "meta": {k: v for k, v in meta.items() if k != "blocks"},
                    "elapsed_s": elapsed, "steps": steps})
        calls = [s for s in steps if s["step_type"] in ("tool_call", "delegation")]
        held = [s for s in calls if "not attempted" in (s["result"] or "")]
        refused = [s for s in steps if s["step_type"] == "respond" and "error" in (s["result"] or "")]
        print(f"[{tag} t{i}] {elapsed}s calls={len(calls)}"
              f"{f' held={len(held)}' if held else ''}"
              f"{f' gate_refusals={len(refused)}' if refused else ''}  "
              f"{(error or (res.get('text') or ''))[:90]}", flush=True)
    return {"tag": tag, "session_id": sid, "turns": out}


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("conversations")
    ap.add_argument("out")
    ap.add_argument("--owner", default=os.getenv("BATTERY_OWNER_ID", ""))
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--only", action="append", default=[], help="run only these tags")
    args = ap.parse_args(argv)
    if not args.owner:
        print("no owner: pass --owner or set BATTERY_OWNER_ID", file=sys.stderr)
        return 2

    convos = json.load(open(args.conversations))
    if args.only:
        convos = [c for c in convos if c["tag"] in args.only]
    print(f"{len(convos)} conversation(s), {sum(len(c['turns']) for c in convos)} turn(s), "
          f"concurrency {args.concurrency}")

    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    gate = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []

    async def _one(c):
        async with gate:
            r = await _run_conversation(mk, args.owner, c["tag"], c["turns"])
        results.append(r)
        json.dump(results, open(args.out, "w"), indent=1, default=str)

    try:
        await asyncio.gather(*(_one(c) for c in convos))
    finally:
        await engine.dispose()
    order = {c["tag"]: i for i, c in enumerate(convos)}
    results.sort(key=lambda r: order.get(r["tag"], 999))
    json.dump(results, open(args.out, "w"), indent=1, default=str)
    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
