#!/usr/bin/env python3
"""Do the program executor's runtime refusals do the work V29's schema enum did?

V29 closed a class by construction: `compute`'s `method` was a schema enum, so a
wrong method name became unrepresentable and `unknown_method` went from 32
occurrences (2026-09-07, names free strings, every name printed in the catalogue)
to 0 in both 2026-09-08 replicates. V30 moved method names back inside the program
JSON, where no schema binds them, and C3 has seen zero — but zero occurrences is
"unverified", not "safe" (this project has been bitten by exactly that reading).

This replays the names the 09-07 battery actually got wrong through V30's node,
and reports whether the refusal names the right one. Recovery in one call is the
claim the runtime refusal has to earn.

    scripts/v30_replay_method_names.py            # gold fixture
"""
from __future__ import annotations
import asyncio, json, os, re, sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

load_dotenv(".env", override=True)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from exposure_workbench.analytics import skill                        # noqa: E402
from exposure_workbench.auth.context import current_user_ctx          # noqa: E402
from exposure_workbench.services import program_service as ps         # noqa: E402
from exposure_workbench.tools import registries                       # noqa: E402


def wrong_names_from(paths: list[Path]) -> Counter:
    """Every `method` / `name` a 09-07 trace sent that is not a method today."""
    out: Counter = Counter()
    known = set(skill.METHODS)
    for p in paths:
        try:
            convs = json.loads(p.read_text())
        except Exception:
            continue
        for conv in convs if isinstance(convs, list) else []:
            if not isinstance(conv, dict):
                continue
            for t in conv.get("turns", []):
                if not isinstance(t, dict):
                    continue                     # a question spec, not a trace
                for s in t.get("steps", []) or []:
                    if not isinstance(s, dict):
                        continue
                    if s.get("tool_name") not in ("compute", "run"):
                        continue
                    for m in re.finditer(r'"(?:method|name)":\s*"([A-Za-z0-9_.]+)"', s.get("args") or ""):
                        if m.group(1) not in known:
                            out[m.group(1)] += 1
    return out


async def main() -> int:
    url = os.getenv("DATABASE_URL_LOCAL",
                    "postgresql+asyncpg://exposure:exposure@localhost:5433/exposure_workbench").replace(
        "/exposure_workbench", "/exposure_gold")
    src = sorted((ROOT / "docs/spikes/v26").glob("*.json")) + sorted((ROOT / "docs/spikes/v29").glob("*.json"))
    names = wrong_names_from(src)
    if not names:
        print("no wrong method names found in the 09-07 traces"); return 1

    # 1. does the tool's own schema refuse them? (V29's enum did)
    reg = registries.build_meta_registry()
    run_tool = reg.tools["run"]
    schema_refused = 0
    for n in names:
        prog = {"program": {"let": [["x", {"fn": "method", "name": n, "subject": "MSFT"}]]}}
        try:
            ok = run_tool.validate_args(prog) if hasattr(run_tool, "validate_args") else None
            schema_refused += 0 if ok in (None, True) else 1
        except Exception:
            schema_refused += 1

    # 2. what does the executor say, and does it name the right one?
    engine = create_async_engine(url)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    current_user_ctx.set(os.getenv("BATTERY_OWNER_ID", "user_3IDBMeAxLTbecvGorzwV7FCeroR"))
    rows, codes = [], Counter()
    try:
        async with mk() as db:
            for n, hits in names.most_common():
                out = await ps.run(db, {"let": [["x", {"fn": "method", "name": n, "subject": "MSFT"}]]}, invoked_by="replay")
                await db.rollback()
                ref = (out["nodes"]["x"].get("refusal") or {})
                nearest = ref.get("nearest") or []
                codes[ref.get("error") or "settled"] += 1
                rows.append({"name": n, "sent": hits, "error": ref.get("error"),
                             "nearest": nearest[:3], "names_a_method": bool(nearest),
                             "routed": ref.get("error") == "wrong_door",
                             "detail": (ref.get("detail") or "")[:150]})
    finally:
        await engine.dispose()

    named = sum(1 for r in rows if r["names_a_method"])
    routed = sum(1 for r in rows if r.get("routed"))
    routed_sends = sum(r["sent"] for r in rows if r.get("routed"))
    print(f"wrong method names in the 2026-09-07 traces: {len(names)} distinct, {sum(names.values())} sends")
    print(f"refused by run's json_schema (V29's enum did this): {schema_refused}/{len(names)}")
    print(f"refused by the executor at node level:            {sum(v for k, v in codes.items() if k != 'settled')}/{len(names)}  {dict(codes)}")
    print(f"refusal names a real method to try instead:       {named}/{len(names)}")
    print(f"refusal routes the name to its OWN door:          {routed}/{len(names)}  ({routed_sends}/{sum(names.values())} sends)")
    print()
    for r in rows[:24]:
        print(f"  {r['name'][:30]:30s} x{r['sent']:<3} {str(r['error']):13s} {r['detail'][:96] if r.get('routed') else 'nearest=' + (', '.join(r['nearest']) or '—')}")
    Path(ROOT / "docs/spikes/v30/METHOD_NAME_REPLAY.json").write_text(json.dumps(
        {"distinct": len(names), "sends": sum(names.values()), "schema_refused": schema_refused,
         "executor_refused": sum(v for k, v in codes.items() if k != "settled"),
         "names_an_alternative": named, "routed_to_own_door": routed, "routed_sends": routed_sends,
         "rows": rows}, indent=1))
    print("\nwrote docs/spikes/v30/METHOD_NAME_REPLAY.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
