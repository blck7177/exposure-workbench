"""Run ONE question of the battery through the real agent loop and record the wire.

Nothing in the repo is changed and no behaviour is altered: this wraps the two functions every loop
already goes through — the provider call (llm/client.chat_with_tools) and the tool call
(agents/tool_session.ToolSession.call) — and writes what went in and what came out to wire.jsonl
beside this file, in order. The battery itself (scripts/conversation_battery.py) is called unchanged.

    cd /home/ubuntu/exposure-workbench
    BATTERY_OWNER_ID=<owner> .venv/bin/python <this file> <questions.json> <tag>
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = Path("/home/ubuntu/exposure-workbench")
os.chdir(REPO)
sys.path.insert(0, str(REPO / "scripts"))

import conversation_battery as cb                               # noqa: E402  (loads .env, puts src on the path)
from exposure_workbench.agents import tool_session as ts_mod     # noqa: E402
from exposure_workbench.llm import client as llm_client          # noqa: E402

WIRE = open(HERE / "wire.jsonl", "w")
_seq = 0
_t0 = time.time()


def _write(kind: str, **fields) -> None:
    global _seq
    _seq += 1
    WIRE.write(json.dumps({"seq": _seq, "kind": kind, "t": round(time.time() - _t0, 3), **fields},
                          ensure_ascii=False, default=str) + "\n")
    WIRE.flush()


_chat = llm_client.chat_with_tools


async def chat_with_tools(messages, tools, **kw):
    sent = copy.deepcopy(messages)            # the loop replaces its STATE block in place afterwards
    started = time.time()
    try:
        content, tool_calls, usage = await _chat(messages=messages, tools=tools, **kw)
    except Exception as exc:                  # recorded and re-raised untouched
        _write("completion_error", error=f"{type(exc).__name__}: {exc}", messages=sent,
               tools=[t["function"]["name"] for t in tools or []], kwargs={k: v for k, v in kw.items()})
        raise
    _write("completion", elapsed=round(time.time() - started, 3), kwargs={k: v for k, v in kw.items()},
           messages=sent, tools=[t["function"]["name"] for t in tools or []],
           tools_chars=len(json.dumps(tools or [], ensure_ascii=False)),
           content=content, tool_calls=tool_calls, usage=usage)
    return content, tool_calls, usage


llm_client.chat_with_tools = chat_with_tools

_call = ts_mod.ToolSession.call


async def call(self, name, args, *, actor=None, task_id=None):
    started = time.time()
    result = await _call(self, name, args, actor=actor, task_id=task_id)
    _write("tool", elapsed=round(time.time() - started, 3), actor=actor, task_id=task_id, name=name, args=args,
           result=result)
    return result


ts_mod.ToolSession.call = call

_open = ts_mod.tool_session


if __name__ == "__main__":
    questions, tag = sys.argv[1], sys.argv[2]
    out = str(HERE / "battery_out.json")
    _write("run", questions=questions, tag=tag, model=os.getenv("OPENAI_MODEL"), lead_model=os.getenv("LEAD_MODEL"),
           analyst_model=os.getenv("ANALYST_MODEL"))
    rc = asyncio.run(cb.main([questions, out, "--only", tag, "--fixture", "--concurrency", "1",
                              "--deny", "submit_brief", "--deny", "start"]))
    _write("done", rc=rc)
    WIRE.close()
    raise SystemExit(rc)
