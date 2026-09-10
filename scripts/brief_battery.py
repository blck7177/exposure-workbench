#!/usr/bin/env python3
"""The research face's first instrument: N issuers, one brief each, measured.

    BATTERY_DB=exposure_gold BATTERY_MCP_PORT=8106 \
      python scripts/brief_battery.py out.json --owner user_… [--tickers NVDA,MSFT] [--replicate 1]

Until now the research face has never been measured. Every number the desk has
about its own behaviour — round trips, refusals, figures against gold — comes
from the chat face; a brief was only ever looked at by a person. V31 moves the
brief onto the same claims gate as a reply, which is exactly the change that
needs a before and after, so this is the before.

What it records per brief, beyond the chat battery's counters:

  gate attempts and WHICH SECTION each refusal named. `_submit_brief` checks the
  six sections in order and returns on the FIRST refusal, so a brief whose sixth
  section is wrong is refused six times while the model fixes one section at a
  time. Counting attempts alone would read as model incompetence when it is the
  order of the check.

  the figures the brief rendered, against gold, per section — so "which section
  loses figures" is answerable, not just "how many".

Runs against the frozen fixture and its own face, like the chat battery: nothing
here touches the production book.
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
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.agents.research_session import run_research_session   # noqa: E402
from exposure_workbench.auth.context import current_user_ctx                 # noqa: E402
from exposure_workbench.db.models import Company, IssuerBrief                # noqa: E402
from exposure_workbench.services import agent_session_service as sess        # noqa: E402
from exposure_workbench.services import research_run_service                 # noqa: E402
from exposure_workbench.tools.faces import FACE_RESEARCH                     # noqa: E402

URL = os.getenv("DATABASE_URL_RLS",
                "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench")
FIXTURE_URL = URL.replace("/exposure_workbench", "/" + os.getenv("BATTERY_DB", "exposure_gold"))
FIXTURE_MCP = f"http://127.0.0.1:{os.getenv('BATTERY_MCP_PORT', '8106')}"

_STEPS = text(
    "SELECT seq, step_type, tool_name, status, left(result_summary, 400) AS result, "
    "       left(args::text, 300) AS args, prompt_tokens, completion_tokens "
    "FROM agent_steps WHERE session_id = :s ORDER BY seq")


def _section_of(result: str) -> str | None:
    """Which section a refusal named. The gate returns `section` beside the
    reason, and the step summary is the serialized result."""
    for key in ('"section": "', "'section': '"):
        if key in (result or ""):
            rest = result.split(key, 1)[1]
            return rest.split('"', 1)[0].split("'", 1)[0]
    return None


async def _one_brief(mk, owner: str, ticker: str, deny: tuple[str, ...]) -> dict:
    current_user_ctx.set(owner)
    async with mk() as db:
        company = (await db.execute(select(Company).where(Company.ticker == ticker.upper()))).scalar_one_or_none()
        if company is None:
            return {"ticker": ticker, "error": "unknown_company", "steps": []}
        session = await sess.create_session(db, kind="research", owner_id=owner)
        sid = session.id
        try:
            run = await research_run_service.create_run(
                db, company_id=company.id, portfolio_id=None, triggered_by="brief_battery",
                task_id=None, owner_id=owner)
        except Exception as exc:                     # noqa: BLE001 — an active run is a fixture state, recorded
            return {"ticker": ticker, "error": f"{type(exc).__name__}: {exc}", "steps": []}
        await research_run_service.update_status(db, run.id, "running", agent_session_id=sid)
        await db.commit()

    started = time.time()
    try:
        res = await run_research_session(lambda: mk(), sid, ticker, deny=deny)
        error = None
    except Exception as exc:                          # noqa: BLE001 — recorded, not raised
        res, error = {"submitted": False, "turns_used": 0, "brief_id": None}, f"{type(exc).__name__}: {exc}"
    elapsed = round(time.time() - started, 1)

    async with mk() as db:
        steps = [dict(r) for r in (await db.execute(_STEPS, {"s": sid})).mappings().all()]
        brief = None
        if res.get("brief_id"):
            row = (await db.execute(select(IssuerBrief).where(IssuerBrief.id == res["brief_id"]))).scalar_one_or_none()
            if row is not None:
                brief = {"id": row.id, "citations": list(row.citations or []),
                         "blocks": row.blocks, "claims_by_section": getattr(row, "claims_by_section", None)}

    attempts = [s for s in steps if s["tool_name"] == "submit_brief"]
    refusals = [(s["seq"], _section_of(s["result"]), (s["result"] or "")[:120])
                for s in attempts if "error" in (s["result"] or "")]
    calls = [s for s in steps if s["step_type"] in ("tool_call", "delegation")]
    llm = [s for s in steps if s["step_type"] == "llm_call"]
    out = {
        "ticker": ticker.upper(), "session_id": sid, "error": error,
        "submitted": bool(res.get("brief_id")), "turns_used": res.get("turns_used"),
        "elapsed_s": elapsed, "brief": brief,
        "counts": {
            "tool_calls": len(calls),
            "llm_calls": len(llm),
            "prompt_tokens": sum(s["prompt_tokens"] or 0 for s in llm),
            "completion_tokens": sum(s["completion_tokens"] or 0 for s in llm),
            "submit_attempts": len(attempts),
            "gate_refusals": len(refusals),
            # the ordering effect: a brief wrong in section six is refused six
            # times as the model walks forward through the sections
            "sections_refused": sorted({s for _q, s, _d in refusals if s}),
            "refusals": [{"seq": q, "section": s, "detail": d} for q, s, d in refusals],
        },
        "steps": steps,
    }
    print(f"[{ticker.upper()}] {elapsed}s calls={len(calls)} submits={len(attempts)} "
          f"refused={len(refusals)}{' sections=' + ','.join(out['counts']['sections_refused']) if refusals else ''} "
          f"{'OK ' + (brief or {}).get('id', '') if out['submitted'] else 'NOT SUBMITTED'}"
          f"{' ' + error if error else ''}", flush=True)
    return out


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--owner", default=os.getenv("BATTERY_OWNER_ID", "user_3IDBMeAxLTbecvGorzwV7FCeroR"))
    ap.add_argument("--tickers", default=None, help="comma separated; default every investigable issuer")
    ap.add_argument("--fixture", action="store_true", default=True)
    ap.add_argument("--deny", action="append", default=[], help="tool names removed from the face")
    ap.add_argument("--replicate", type=int, default=1)
    ap.add_argument("--no-preflight", action="store_true",
                    help="skip asking the provider whether it accepts the face (it costs one call)")
    args = ap.parse_args(argv)

    url = FIXTURE_URL if args.fixture else URL
    if args.fixture:
        os.environ["MCP_URL"] = FIXTURE_MCP
    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(args.owner)

    # V28-R, the lesson this battery cannot afford to relearn: a top-level `not`
    # that jsonschema accepted and the provider rejected with a 400 on the whole
    # function shipped green through 2,191 offline tests, and the battery then
    # ran 140 turns at zero calls before anyone saw it. The brief schema is now
    # 7,863 characters and ten levels deep, six copies of ANSWER_SCHEMA under one
    # object. One call, sixteen output tokens, before any brief is attempted.
    if not args.no_preflight:
        from openai import AsyncOpenAI
        from exposure_workbench.tools.registries import build_research_registry
        reg = build_research_registry()
        face = [t for t in FACE_RESEARCH if t not in args.deny]
        try:
            await AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]).chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"), max_completion_tokens=16,
                messages=[{"role": "user", "content": "say ok"}], tools=reg.schemas(face))
            print(f"preflight: the provider accepts the research face as written ({len(face)} tools)", flush=True)
        except Exception as exc:                      # noqa: BLE001 — this is the whole point of the check
            # An account problem is not a schema problem, and reading one as the
            # other is how a green schema gets "fixed" for a week.
            text_ = str(exc)
            account = any(k in text_ for k in ("insufficient_quota", "credit_balance", "rate_limit",
                                               "invalid_api_key", "billing"))
            # Built outside the f-string: an implicit concatenation inside a
            # replacement field is PEP 701, and this project declares 3.11.
            why = ("the account cannot call the provider at all, so this says NOTHING "
                   "about the schema; add credit and run again" if account else
                   "the provider REJECTED this face as written, so no brief could have run")
            print(f"PREFLIGHT FAILED — {why}:"
                  f"\n  {type(exc).__name__}: {text_[:400]}", flush=True)
            await engine.dispose()
            return 2 if account else 3

    try:
        if args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        else:
            async with mk() as db:
                tickers = [t for (t,) in (await db.execute(
                    select(Company.ticker).where(Company.is_investigable.is_(True)).order_by(Company.ticker))).all()]
        print(f"{len(tickers)} issuer(s), replicate {args.replicate}, db {url.rsplit('/', 1)[-1]}, "
              f"mcp {os.environ.get('MCP_URL') or 'settings default'}, deny {args.deny or '-'}", flush=True)
        briefs = []
        for t in tickers:
            briefs.append(await _one_brief(mk, args.owner, t, tuple(args.deny)))
    finally:
        await engine.dispose()

    Path(args.out).write_text(json.dumps(briefs, indent=1, default=str))
    ok = sum(1 for b in briefs if b["submitted"])
    print(f"\nwritten {args.out} — {ok}/{len(briefs)} submitted, "
          f"{sum(b['counts']['gate_refusals'] for b in briefs if 'counts' in b)} gate refusals, "
          f"{sum(b['counts']['prompt_tokens'] for b in briefs if 'counts' in b):,} prompt tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
