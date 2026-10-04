"""Regenerate the instructions and tool lists the Q05 run sent, and prove they are the ones it sent.

An llm_call step records the instructions by sha and the tools by name only. This script rebuilds both
from the same tree (fingerprint in freeze_before.txt / freeze_after.txt) against the same database, through
the same path the loops use (scope.catalogue -> lead.instructions_for; specialist.instructions_for;
tool_session over the fixture face with deny=('start',)), then checks every recorded sha and tool list.
Writes instructions_lead.txt, instructions_issuer.txt, tools_lead.json, tools_issuer.json.

    BATTERY_DB=exposure_dev BATTERY_MCP_PORT=8211 scripts/battery_fixture.sh serve
    .venv/bin/python <this dir>/export_prompts.py
    BATTERY_DB=exposure_dev BATTERY_MCP_PORT=8211 scripts/battery_fixture.sh stop
"""
import asyncio, json, os, sys
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
os.chdir(ROOT)
load_dotenv(".env", override=True)
os.environ["MCP_URL"] = "http://127.0.0.1:8211"
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine   # noqa: E402
from exposure_workbench.agents import lead, specialist, tasks as T             # noqa: E402
from exposure_workbench.agents.llm_session import _sha                        # noqa: E402
from exposure_workbench.agents.tool_session import tool_session               # noqa: E402
from exposure_workbench.auth.context import current_user_ctx                  # noqa: E402
from exposure_workbench.services import scope as scope_svc                    # noqa: E402
from exposure_workbench.tools import faces                                    # noqa: E402

OWNER = "user_3IDBMeAxLTbecvGorzwV7FCeroR"
URL = os.getenv("DATABASE_URL_RLS", "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_workbench").replace(
    "/exposure_workbench", "/exposure_dev")


async def main() -> int:
    run = json.load(open(HERE / "battery_out.json"))[0]
    sid, turn = run["session_id"], run["turns"][0]
    recorded = [(s["actor"], json.loads(s["args"])["request"]) for s in turn["steps"] if s["step_type"] == "llm_call"]
    current_user_ctx.set(OWNER)
    engine = create_async_engine(URL)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        catalogue = await scope_svc.catalogue(db)
    await engine.dispose()
    texts = {"lead": lead.instructions_for(catalogue), "issuer": specialist.instructions_for("issuer")}
    tools = {}
    async with tool_session(faces.FACE_NAME_LEAD, session_id=sid, user_id=OWNER, message_id=turn["message_id"],
                            deny=("start",)) as s:
        tools["lead"] = list(s.tools) + [T.ASK_TOOL, T.OPEN_TOOL]
    async with tool_session("issuer", session_id=sid, user_id=OWNER, message_id=turn["message_id"],
                            deny=("start",)) as s:
        tools["issuer"] = list(s.tools) + [T.OPEN_TOOL]
    ok = True
    for actor, req in recorded:
        who = "issuer" if actor == "sub:issuer" else "lead"
        sha_ok = _sha(texts[who]) == req["instructions_sha"] and len(texts[who]) == req["instructions_chars"]
        names = [t["name"] for t in tools[who]]
        tools_ok = req["tools"] == names or req["tools"] == ["open"]      # the budget-exhausted request sends open alone
        ok &= sha_ok and tools_ok
        print(f"{actor or 'lead':10} instructions sha {req['instructions_sha']} {'matches' if sha_ok else 'DIFFERS'}; "
              f"tools {req['tools']} {'match' if tools_ok else 'DIFFER from ' + str(names)}")
    for who in ("lead", "issuer"):
        (HERE / f"instructions_{who}.txt").write_text(texts[who])
        (HERE / f"tools_{who}.json").write_text(json.dumps(tools[who], ensure_ascii=False, indent=1))
    print("all recorded requests reproduced" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
