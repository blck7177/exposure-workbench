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

# `.env` is the truth for everything a battery must not get wrong by accident — the keys, the
# database — so it overrides whatever the shell happens to hold. THE MODEL IS NOT ONE OF THOSE:
# it is the variable of a measured round (plan V1 §3 步骤 7), and `OPENAI_MODEL=… battery …` was
# silently run on the model in `.env` (plan §5, item 5). What the operator set for a model on the
# command line survives the load; `--model`, `--lead-model` and `--analyst-model` say it outright.
_MODEL_VARS = ("OPENAI_MODEL", "LEAD_MODEL", "ANALYST_MODEL")
_asked = {k: os.environ[k] for k in _MODEL_VARS if os.environ.get(k)}
load_dotenv(".env", override=True)
os.environ.update(_asked)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.agents.meta_agent import handle_message   # noqa: E402
from exposure_workbench.auth.context import current_user_ctx      # noqa: E402
from exposure_workbench.services import agent_session_service as sess   # noqa: E402

URL = os.getenv("DATABASE_URL_RLS",
                "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")
# V30 Phase 0: the frozen fixture (scripts/battery_fixture.sh). `--fixture` points
# the battery's own engine at exposure_battery and its tool calls at the fixture
# face on :8105; nothing then reads or writes the production book.
FIXTURE_URL = URL.replace("/exposure_workbench", "/" + os.getenv("BATTERY_DB", "exposure_battery"))
FIXTURE_MCP = f"http://127.0.0.1:{os.getenv('BATTERY_MCP_PORT', '8105')}"

# A BOUND AGAINST A RUNAWAY ROW, not a display convenience — and the previous
# caps were neither. `left(args, 300)` was sized when one question was many short
# addressed calls: `compute`'s longest argument list across both V26 rounds is
# 298 characters, so the per-call protocol never met the cut. V30 replaced it
# with ONE program per question, 179 of 202 `run` calls run past 300, and a rank
# node comes after the vector it orders — so the cut removed exactly what the
# counters read. It broke two of them silently:
#
#   superlative_without_rank   reported 37 of 52 on V26_C3 where the full
#                              arguments, still in `agent_steps` and never
#                              truncated at the write, say 14.
#   the answer-mark counter    json.loads of a truncated `respond` payload
#                              raised on 273 of 280 turns and fell back to the
#                              rendered text its own comment says not to read.
#
# Cost of the wider cap, measured over the 110 sessions of both rounds: 1119 kB
# of arguments against 361 kB, on spike files that are already 3.4 MB and 4.6 MB.
# The cap is not what makes the ordering question answerable — `run` now records
# the kinds it declared (tools/registry._declared_nodes), and battery_counters
# reads that instead of the program text. What the cap buys is every OTHER reading
# of a trace: the mark counter's payload, a replay, a forensic recount. Rounds
# already on disk keep the cut they were written with; a round before the
# declaration existed is reported as undeclared, never guessed.
_ARGS_CAP, _RESULT_CAP = 4000, 1000

# `problems` is read on its own: jsonb orders keys by length, so inside `args` the answer's text
# comes before the list of what the check refused in it, and a long answer pushed that list past
# the cap — the one thing a counter of refusals by rule has to read (V1 step 7).
_STEPS = text(
    f"SELECT seq, step_type, tool_name, actor, status, left(result_summary, {_RESULT_CAP}) AS result, "
    f"       left(args::text, {_ARGS_CAP}) AS args, left((args->'problems')::text, {_ARGS_CAP}) AS problems, "
    "       prompt_tokens, completion_tokens "
    "FROM agent_steps WHERE session_id = :s AND message_id = :m ORDER BY seq")

_RELEASE = text("UPDATE agent_sessions SET turn_started_at = NULL WHERE id = :s")


async def _run_conversation(mk, owner: str, tag: str, turns: list[str], deny: tuple[str, ...] = ()) -> dict:
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
            res = await handle_message(lambda: mk(), sid, q, deny=deny)
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
        # V33: the analyst's answer is a step of its own (`answer`, status
        # `rejected` when the check refused it); `respond` is the research
        # path's exit and every round before V33.
        refused = [s for s in steps if (s["step_type"] == "respond" and "error" in (s["result"] or ""))
                   or (s["step_type"] == "answer" and s["status"] == "rejected")]
        requests = [s for s in steps if s["step_type"] == "request"]
        type_errors = [s for s in calls if s["tool_name"] == "run" and (s["result"] or "").startswith("error: type_errors")]
        # V1: a primitive's step says what the call got, and a refusal among its rows by code
        rows_refused = [s for s in calls if "| refused: " in (s["result"] or "") or s["status"] == "rejected"]
        print(f"[{tag} t{i}] {elapsed}s calls={len(calls)}"
              f"{f' refused={len(rows_refused)}' if rows_refused else ''}"
              f"{f' requests={len(requests)}' if requests else ''}"
              f"{f' type_errors={len(type_errors)}' if type_errors else ''}"
              f"{f' held={len(held)}' if held else ''}"
              f"{f' refusals={len(refused)}' if refused else ''}  "
              f"{(error or (res.get('text') or ''))[:90]}", flush=True)
    return {"tag": tag, "session_id": sid, "turns": out}


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("conversations")
    ap.add_argument("out")
    ap.add_argument("--owner", default=os.getenv("BATTERY_OWNER_ID", ""))
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--only", action="append", default=[], help="run only these tags")
    ap.add_argument("--fixture", action="store_true",
                    help="run against exposure_battery and the fixture face (scripts/battery_fixture.sh)")
    ap.add_argument("--deny", action="append", default=[],
                    help="tool names taken off the face for every turn (Phase 0: start)")
    ap.add_argument("--model", help="every agent of the turn (OPENAI_MODEL)")
    ap.add_argument("--lead-model", help="the lead analyst only (LEAD_MODEL); the rest stay on --model")
    ap.add_argument("--analyst-model", help="the three analysts only (ANALYST_MODEL)")
    args = ap.parse_args(argv)
    for var, value in (("OPENAI_MODEL", args.model), ("LEAD_MODEL", args.lead_model), ("ANALYST_MODEL", args.analyst_model)):
        if value:
            os.environ[var] = value
    # settings is a lazily built module global: what it read before this line is dropped
    from exposure_workbench.app_state import settings as _settings_mod
    _settings_mod._settings = None
    url = URL
    if args.fixture:
        url = FIXTURE_URL
        os.environ["MCP_URL"] = FIXTURE_MCP
        # settings is a lazily built module global; anything that read it before
        # this line would keep the production face, so it is reset here.
        from exposure_workbench.app_state import settings as _settings_mod
        _settings_mod._settings = None
        if not args.deny:
            args.deny = ["start"]
    deny = tuple(args.deny)
    if not args.owner:
        print("no owner: pass --owner or set BATTERY_OWNER_ID", file=sys.stderr)
        return 2

    convos = json.load(open(args.conversations))
    if args.only:
        convos = [c for c in convos if c["tag"] in args.only]
    print(f"{len(convos)} conversation(s), {sum(len(c['turns']) for c in convos)} turn(s), "
          f"concurrency {args.concurrency}, model {os.getenv('OPENAI_MODEL') or 'settings default'}"
          f" (lead {os.getenv('LEAD_MODEL') or '='}, analysts {os.getenv('ANALYST_MODEL') or '='}), "
          f"db {url.rsplit('/', 1)[-1]}, mcp {os.environ.get('MCP_URL') or 'settings default'}, deny {list(deny) or '-'}")

    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    gate = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []

    async def _one(c):
        async with gate:
            r = await _run_conversation(mk, args.owner, c["tag"], c["turns"], deny)
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
