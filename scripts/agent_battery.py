#!/usr/bin/env python3
"""Drive the real meta-agent loop against real questions and capture the traces.

Not a test. The suite asserts invariants; this measures behaviour, which is a
different thing and needs a different tool. Every defect in V11 came from here:
running the shipped loop against questions a user would actually ask, then
checking each answer against the ledger by hand.

The finding that shaped everything else was only visible by REPEATING a
question. "What is AAPL's total debt?" was answered correctly once and wrongly
seven times out of eight — the wrong ones reading a component off the balance
sheet and calling it the total — and a single pass would have recorded either
verdict as the truth. So `--repeat` exists, and the rule that came with it: a
change to the prompt layer is not verified by one run.

    python scripts/agent_battery.py tests/battery/questions_round1.json out.json
    python scripts/agent_battery.py -                  out.json --ask "What is AAPL's total debt?" --repeat 8

Requires the app's .env (OPENAI_API_KEY, MCP_URL reachable from the host) and a
database that has been seeded.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv(".env", override=True)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from exposure_workbench.agents.meta_agent import handle_message
from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.services import agent_session_service as sess

URL = os.getenv("DATABASE_URL_RLS",
                "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")

_STEPS = text(
    "SELECT seq, step_type, tool_name, status, left(result_summary, 120) AS result, "
    "       left(args::text, 200) AS args, prompt_tokens, completion_tokens "
    "FROM agent_steps WHERE session_id = :s ORDER BY seq")


async def run_one(mk, owner: str, question: str, tag: str) -> dict:
    current_user_ctx.set(owner)
    async with mk() as db:
        session = await sess.create_session(db, kind="meta", owner_id=owner)
        sid = session.id
        await db.commit()
    async with mk() as db:
        await sess.claim_turn(db, sid)
        await db.commit()

    started = time.time()
    try:
        out = await handle_message(lambda: mk(), sid, question)
        error = None
    except Exception as exc:                                  # noqa: BLE001 — recorded, not raised
        out, error = {}, f"{type(exc).__name__}: {exc}"
    elapsed = round(time.time() - started, 1)

    async with mk() as db:
        steps = [dict(r) for r in (await db.execute(_STEPS, {"s": sid})).mappings().all()]
    return {"tag": tag, "question": question, "session_id": sid, "elapsed_s": elapsed,
            "error": error, "answer": out.get("text"), "citations": out.get("citations", []),
            "meta": out.get("meta", {}), "steps": steps}


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", help='a JSON file of [{"tag","q"}], or "-" with --ask')
    ap.add_argument("out")
    ap.add_argument("--ask", action="append", default=[], help="a question, instead of a file")
    ap.add_argument("--repeat", type=int, default=1,
                    help="run every question N times; behaviour here is a distribution")
    ap.add_argument("--owner", default=os.getenv("BATTERY_OWNER_ID", ""),
                    help="the user id to run as (defaults to $BATTERY_OWNER_ID)")
    args = ap.parse_args(argv)

    if not args.owner:
        print("no owner: pass --owner or set BATTERY_OWNER_ID", file=sys.stderr)
        return 2
    if args.questions == "-":
        asked = [{"tag": f"ask-{i + 1}", "q": q} for i, q in enumerate(args.ask)]
    else:
        asked = json.load(open(args.questions))
    if not asked:
        print("no questions", file=sys.stderr)
        return 2

    plan = [(f"{q['tag']}-{r + 1}" if args.repeat > 1 else q["tag"], q["q"])
            for q in asked for r in range(args.repeat)]

    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    results: list[dict] = []
    try:
        for tag, question in plan:
            r = await run_one(mk, args.owner, question, tag)
            results.append(r)
            calls = [s["tool_name"] for s in r["steps"]
                     if s["tool_name"] and s["tool_name"] != "respond"]
            refused = sum(1 for s in r["steps"]
                          if s["step_type"] == "respond" and "error" in (s["result"] or ""))
            head = r["error"] or (r["answer"] or "")[:88].replace("\n", " ")
            print(f"[{tag}] {r['elapsed_s']}s calls={len(calls)} gate_refusals={refused}  {head}",
                  flush=True)
            json.dump(results, open(args.out, "w"), indent=1, default=str)
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
