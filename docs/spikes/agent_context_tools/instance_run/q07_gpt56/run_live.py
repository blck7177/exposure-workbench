"""Run ONE question of the battery through the real agent loop ON A NAMED MODEL and record, verbatim, every
request the loops send to the model provider and every call they make to the tool face.

The same instrument as ../q07_live/run_live.py (the gpt-5.4-mini run), with two additions:

  - the model is the third argument, handed to the battery as `--model` (every agent of the turn);
  - gpt-5.6-* on /v1/chat/completions refuses function tools unless reasoning_effort is 'none'
    (param_probe.txt beside this file: no parameter -> 400, 'low' -> 400, 'none' -> OK). The repo's client
    does not send the parameter, so it is added HERE, at the SDK hook, only for gpt-5.6-* and only when
    absent — the approach of docs/spikes/v37/tools/battery_with_model.py. The request written to
    wire.jsonl is the request as sent, with the added parameter in it and named under "injected".
    gpt-5.4-mini ran with zero reasoning tokens on this path, so 'none' is the like-for-like setting.

Nothing in the repo is changed. Two hooks wrap the two doors every loop goes through, call the original,
and write what went in and what came out to wire.jsonl beside this file, in order:

  1. openai AsyncCompletions.create: the exact keyword arguments sent to the provider and the full
     response object. Tool schemas are written once per distinct set (record "tools", keyed by a hash).
     Which agent sent the request is read off the stack (the LlmSession.chat frame: actor, note).
  2. ToolSession.call: the MCP call (name, args, actor, task_id) and the dict it returned.

    cd /home/ubuntu/exposure-workbench
    BATTERY_OWNER_ID=<owner> .venv/bin/python <this file> <questions.json> <tag> <model>
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path("/home/ubuntu/exposure-workbench")
os.chdir(REPO)
sys.path.insert(0, str(REPO / "scripts"))

import conversation_battery as cb                                   # noqa: E402  (loads .env, puts src on the path)
from openai.resources.chat.completions import AsyncCompletions      # noqa: E402
from exposure_workbench.agents import tool_session as ts_mod         # noqa: E402
from exposure_workbench.agents.llm_session import LlmSession         # noqa: E402

WIRE = open(HERE / "wire.jsonl", "w")
_seq = 0
_t0 = time.time()
_tool_sets: dict[str, list[str]] = {}


def _write(kind: str, **fields) -> None:
    global _seq
    _seq += 1
    WIRE.write(json.dumps({"seq": _seq, "kind": kind, "t": round(time.time() - _t0, 3), **fields},
                          ensure_ascii=False, default=str) + "\n")
    WIRE.flush()


def _caller() -> dict:
    """Who is spending (the LlmSession.chat frame), for which task, and where in the loop."""
    who = {"actor": "?", "task_id": None, "note": None, "frames": []}
    for fi in inspect.stack(0):
        f = fi.frame
        if "exposure_workbench" in fi.filename and "/llm/" not in fi.filename:
            who["frames"].append(f"{Path(fi.filename).stem}.{fi.function}:{fi.lineno}")
            task = f.f_locals.get("task")
            if who["task_id"] is None and getattr(task, "task_id", None):
                who["task_id"] = task.task_id
        s = f.f_locals.get("self")
        if fi.function == "chat" and isinstance(s, LlmSession):
            who["actor"] = s._actor or "lead"
            who["note"] = copy.deepcopy(f.f_locals.get("note"))
    return who


_create = AsyncCompletions.create


async def create(self, *args, **kwargs):
    who = _caller()                                 # before the first await, while the loop's frames are on the stack
    injected = {}
    if str(kwargs.get("model", "")).startswith("gpt-5.6") and "reasoning_effort" not in kwargs:
        kwargs["reasoning_effort"] = "none"
        injected = {"reasoning_effort": "none"}
    tools = kwargs.get("tools") or []
    key = hashlib.sha256(json.dumps(tools, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    if key not in _tool_sets:
        _tool_sets[key] = [t.get("function", {}).get("name") for t in tools]
        _write("tools", set=key, names=_tool_sets[key], chars=len(json.dumps(tools, ensure_ascii=False)),
               tools=tools)
    request = copy.deepcopy({k: v for k, v in kwargs.items() if k != "tools"})
    started = time.time()
    try:
        response = await _create(self, *args, **kwargs)
    except Exception as exc:                        # recorded and re-raised untouched
        _write("completion_error", **who, request=request, injected=injected, tools_set=key,
               error=f"{type(exc).__name__}: {exc}")
        raise
    _write("completion", **who, elapsed=round(time.time() - started, 3), request=request, injected=injected,
           tools_set=key, tools_names=_tool_sets[key], response=response.model_dump(mode="json"))
    return response


AsyncCompletions.create = create

_call = ts_mod.ToolSession.call


async def call(self, name, args, *, actor=None, task_id=None):
    sent = copy.deepcopy(args)
    started = time.time()
    result = await _call(self, name, args, actor=actor, task_id=task_id)
    _write("tool", elapsed=round(time.time() - started, 3), actor=actor, task_id=task_id, name=name, args=sent,
           result=result)
    return result


ts_mod.ToolSession.call = call


if __name__ == "__main__":
    questions, tag, model = sys.argv[1], sys.argv[2], sys.argv[3]
    out = str(HERE / "battery_out.json")
    _write("run", questions=questions, tag=tag, owner=os.getenv("BATTERY_OWNER_ID"), model=model,
           lead_model=os.getenv("LEAD_MODEL"), analyst_model=os.getenv("ANALYST_MODEL"),
           injected_for="gpt-5.6-*: reasoning_effort=none when absent")
    rc = asyncio.run(cb.main([questions, out, "--only", tag, "--fixture", "--concurrency", "1",
                              "--deny", "submit_brief", "--deny", "start", "--model", model]))
    _write("done", rc=rc)
    WIRE.close()
    raise SystemExit(rc)
