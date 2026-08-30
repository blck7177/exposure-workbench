#!/usr/bin/env python3
"""Battery runner with a per-question FACE ABLATION arm.

scripts/agent_battery.py drives the real loop on the full 29-tool meta face. This
one adds the control the experiment needs: the same question, the same model, the
same gate — on a NARROWED face containing only the tools that question's chain
actually needs.

The narrowing rides the existing skip-flag channel (`deny`, a claim on the
internal bearer that the mount subtracts from its face per request), so nothing
is deployed, patched or restarted: the tool container serves its 29-tool mount
exactly as it does in production and the model is simply shown fewer of them.

Why this is the right control. "The agent failed on a task nobody designed for"
has two competing explanations — it could not COMPOSE the chain, or it could not
FIND the chain among 29 tools. Removing only tools the chain does not need holds
capability fixed and varies selection load alone. If the narrow arm solves what
the wide arm misses, tool-list length is a real cost. If both arms fail the same
way, length was never the binding constraint and the missing thing is knowledge.

    MCP_URL=http://127.0.0.1:8104 BATTERY_OWNER_ID=user_... \
      python scripts/ablation_battery.py tests/battery/questions_round4.json out.json --arm wide --repeat 3
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

from exposure_workbench.agents import meta_agent
from exposure_workbench.agents.meta_agent import handle_message
from exposure_workbench.auth.context import current_user_ctx
from exposure_workbench.services import agent_session_service as sess
from exposure_workbench.tools import faces

URL = os.getenv("DATABASE_URL_RLS",
                "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")

_STEPS = text(
    "SELECT seq, step_type, tool_name, status, left(result_summary, 200) AS result, "
    "       left(args::text, 300) AS args, prompt_tokens, completion_tokens "
    "FROM agent_steps WHERE session_id = :s ORDER BY seq")

_ORIG_TOOL_SESSION = meta_agent.tool_session

# think and respond are never denied: one is free reflection, the other is the
# session's ONLY exit. Denying respond would not narrow a face, it would remove
# the turn's ability to end — which is a different experiment (V7-Q2 ran it by
# accident and the finding was a loop that could not terminate).
_NEVER_DENY = {"think", "respond"}


def _install_deny(keep: list[str] | None) -> list[str]:
    """Patch the meta-agent's tool_session so this turn's token carries a deny list.

    Returns the deny list actually applied, so the record says what the model saw
    rather than what the question file asked for.
    """
    if keep is None:
        meta_agent.tool_session = _ORIG_TOOL_SESSION
        return []
    kept = set(keep) | _NEVER_DENY
    deny = sorted(t for t in faces.FACE_META_AGENT if t not in kept)

    def patched(face_name, **kw):
        return _ORIG_TOOL_SESSION(face_name, deny=tuple(deny), **kw)

    meta_agent.tool_session = patched
    return deny


async def run_one(mk, owner: str, q: dict, tag: str, arm: str,
                  trimmed_keep: list[str] | None = None) -> dict:
    # Three arms, and the third one exists because the second is confounded.
    #
    #   wide    — the production face, 29 tools.
    #   narrow  — only the tools this question's chain needs. This is an UPPER
    #             BOUND on what removing distraction can buy, not a clean
    #             measurement of it: handing the model exactly the right six
    #             tools also tells it which six are right. Read a narrow-arm win
    #             as ambiguous; read a narrow-arm FAILURE as decisive, because a
    #             chain the model cannot find with every irrelevant tool removed
    #             was never a search problem.
    #   trimmed — a fixed face computed from historical usage and the union of
    #             every question's needs, IDENTICAL for all questions. It leaks
    #             nothing about any individual question, so a trimmed-arm gain is
    #             attributable to list length alone.
    keep = {"narrow": q.get("minimal_tools"), "trimmed": trimmed_keep}.get(arm)
    deny = _install_deny(keep)

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
        out = await handle_message(lambda: mk(), sid, q["q"])
        error = None
    except Exception as exc:                              # noqa: BLE001 — recorded, not raised
        out, error = {}, f"{type(exc).__name__}: {exc}"
    elapsed = round(time.time() - started, 1)

    async with mk() as db:
        steps = [dict(r) for r in (await db.execute(_STEPS, {"s": sid})).mappings().all()]

    calls = [s["tool_name"] for s in steps
             if s["step_type"] in ("tool_call", "delegation") and s["tool_name"]]
    return {
        "tag": tag, "arm": arm, "tools_offered": len(faces.FACE_META_AGENT) - len(deny),
        "denied": deny, "question": q["q"], "session_id": sid, "elapsed_s": elapsed,
        "error": error, "answer": out.get("text"), "citations": out.get("citations", []),
        "meta": out.get("meta", {}),
        "n_calls": len(calls), "call_sequence": calls,
        "n_rejected": sum(1 for s in steps if s["status"] == "rejected"),
        "n_gate_refusals": sum(1 for s in steps
                               if s["step_type"] == "respond" and "error" in (s["result"] or "")),
        "prompt_tokens": sum(s["prompt_tokens"] or 0 for s in steps),
        "steps": steps,
    }


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions")
    ap.add_argument("out")
    ap.add_argument("--arm", choices=["wide", "narrow", "trimmed"], default="wide")
    ap.add_argument("--keep", default="",
                    help="trimmed arm: comma-separated tools to KEEP, identical for every question")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated tags to run")
    ap.add_argument("--owner", default=os.getenv("BATTERY_OWNER_ID", ""))
    args = ap.parse_args(argv)

    if not args.owner:
        print("no owner: pass --owner or set BATTERY_OWNER_ID", file=sys.stderr)
        return 2

    asked = json.load(open(args.questions))
    if args.only:
        want = {t.strip() for t in args.only.split(",")}
        asked = [q for q in asked if q["tag"] in want]
    if not asked:
        print("no questions", file=sys.stderr)
        return 2
    trimmed_keep = [t.strip() for t in args.keep.split(",") if t.strip()] or None
    if args.arm == "trimmed" and not trimmed_keep:
        print("trimmed arm needs --keep", file=sys.stderr)
        return 2
    if args.arm == "narrow":
        missing = [q["tag"] for q in asked if not q.get("minimal_tools")]
        if missing:
            print(f"narrow arm needs minimal_tools on every question; missing: {missing}",
                  file=sys.stderr)
            return 2

    plan = [(f"{q['tag']}-{r + 1}" if args.repeat > 1 else q["tag"], q)
            for q in asked for r in range(args.repeat)]

    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    results: list[dict] = []
    try:
        for tag, q in plan:
            r = await run_one(mk, args.owner, q, tag, args.arm, trimmed_keep)
            results.append(r)
            head = r["error"] or (r["answer"] or "")[:80].replace("\n", " ")
            print(f"[{args.arm}:{tag}] {r['elapsed_s']}s offered={r['tools_offered']} "
                  f"calls={r['n_calls']} rej={r['n_rejected']} gate={r['n_gate_refusals']}  {head}",
                  flush=True)
            json.dump(results, open(args.out, "w"), indent=1, default=str)
    finally:
        meta_agent.tool_session = _ORIG_TOOL_SESSION
        await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
