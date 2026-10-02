"""wire.jsonl + battery_out.json -> transcript.md (verbatim) and timeline.txt (one line per event).

Each provider request is printed against the previous request of the same agent (actor + task): a message
identical to the one at the same position last time is one line ("unchanged"); every other message is
printed whole. The first request of each agent is therefore printed whole. Responses, tool calls and tool
results are printed whole. Nothing is summarised away; sizes are characters of the JSON the SDK was given.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IN_PROCESS = {"ask", "open", "repair_answer", "submit", "think", "submit_brief"}


def text_of(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", json.dumps(p, ensure_ascii=False)) for p in content)


def msg_chars(m: dict) -> int:
    return len(json.dumps(m, ensure_ascii=False))


def fence(s: str) -> str:
    return "````text\n" + s.rstrip("\n") + "\n````"


def show_message(i: int, m: dict) -> str:
    head = f"**[{i}] {m.get('role')}**"
    if m.get("tool_call_id"):
        head += f" (tool_call_id `{m['tool_call_id']}`)"
    head += f" — {len(text_of(m.get('content')))} chars of content"
    out = [head]
    if text_of(m.get("content")):
        out.append(fence(text_of(m.get("content"))))
    for tc in m.get("tool_calls") or []:
        out.append(f"tool_call `{tc['id']}` **{tc['function']['name']}**")
        out.append(fence(tc["function"]["arguments"]))
    return "\n\n".join(out)


def main() -> None:
    wire = [json.loads(line) for line in (HERE / "wire.jsonl").read_text().splitlines() if line.strip()]
    steps = []
    bo = HERE / "battery_out.json"
    if bo.exists():
        for convo in json.loads(bo.read_text()):
            for turn in convo["turns"]:
                steps = turn.get("steps") or []
                final = turn
    tool_sets = {w["set"]: w for w in wire if w["kind"] == "tools"}
    prev: dict[tuple, list] = {}
    md, tl = [], []
    c_no = t_no = 0
    run = next((w for w in wire if w["kind"] == "run"), {})
    md.append(f"# Live run {run.get('tag')}\n\nmodel {run.get('model')} (lead {run.get('lead_model') or '='}, "
              f"analysts {run.get('analyst_model') or '='}); questions {run.get('questions')}\n")
    for w in wire:
        if w["kind"] == "tools":
            md.append(f"## Tool set `{w['set']}` — {len(w['names'])} tools, {w['chars']} chars\n\n"
                      f"{', '.join(w['names'])}\n\n<details><summary>schemas verbatim</summary>\n\n"
                      + "````json\n" + json.dumps(w["tools"], ensure_ascii=False, indent=1) + "\n````\n\n</details>\n")
            tl.append(f"{w['t']:>7.1f}s  tools  set {w['set']}: {', '.join(w['names'])} ({w['chars']} chars)")
        elif w["kind"] in ("completion", "completion_error"):
            c_no += 1
            req = w["request"]
            msgs = req.get("messages") or []
            # the lead's frames can hold a `task` local of the delegation they ran; a lead request is the lead's
            task = w.get("task_id") if w.get("actor") != "lead" else None
            key = (w.get("actor"), task)
            before = prev.get(key, [])
            label = f"C{c_no} · {w.get('actor')}" + (f" · {task}" if task else "")
            kw = {k: v for k, v in req.items() if k != "messages"}
            md.append(f"## {label} — t={w['t']}s\n\nrequest: {json.dumps(kw, ensure_ascii=False)}; tools set "
                      f"`{w['tools_set']}` ({len(tool_sets.get(w['tools_set'], {}).get('names', []))} tools, "
                      f"{tool_sets.get(w['tools_set'], {}).get('chars', 0)} chars); {len(msgs)} messages, "
                      f"{sum(msg_chars(m) for m in msgs)} chars; called from {' ← '.join(w.get('frames', [])[:4])}\n")
            if w.get("note"):
                md.append(f"loop's note (what this completion read since the last one, not sent): "
                          f"`{json.dumps(w['note'], ensure_ascii=False)}`\n")
            md.append("### Request messages\n")
            for i, m in enumerate(msgs):
                if i < len(before) and before[i] == m:
                    md.append(f"[{i}] {m.get('role')} — unchanged ({msg_chars(m)} chars)\n")
                else:
                    tag = "changed" if i < len(before) else "new"
                    md.append(f"*({tag})* " + show_message(i, m) + "\n")
            prev[key] = msgs
            if w["kind"] == "completion_error":
                md.append(f"### Provider error\n\n{fence(w['error'])}\n")
                tl.append(f"{w['t']:>7.1f}s  {label:<34} ERROR {w['error'][:120]}")
                continue
            r = w["response"]
            ch = r["choices"][0]
            msg = ch["message"]
            u = r.get("usage") or {}
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
            reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
            md.append(f"### Response — {r.get('model')}, finish `{ch.get('finish_reason')}`, "
                      f"{u.get('prompt_tokens')} prompt ({cached} cached) / {u.get('completion_tokens')} completion "
                      f"({reasoning} reasoning) tokens, {w['elapsed']}s\n")
            if msg.get("content"):
                md.append(fence(msg["content"]) + "\n")
            if msg.get("refusal"):
                md.append(f"refusal: {msg['refusal']}\n")
            for tc in msg.get("tool_calls") or []:
                where = "in-process" if tc["function"]["name"] in IN_PROCESS else "MCP"
                md.append(f"tool_call `{tc['id']}` **{tc['function']['name']}** ({where})\n\n"
                          + fence(tc["function"]["arguments"]) + "\n")
            calls = [tc["function"]["name"] for tc in msg.get("tool_calls") or []]
            tl.append(f"{w['t']:>7.1f}s  {label:<34} {u.get('prompt_tokens'):>6}p {u.get('completion_tokens'):>5}c "
                      f"({reasoning}r) {len(msgs):>3} msgs {sum(msg_chars(m) for m in msgs):>7} ch  -> "
                      + (", ".join(calls) if calls else f"TEXT {len(msg.get('content') or '')} chars"))
        elif w["kind"] == "tool":
            t_no += 1
            res = w["result"]
            body = json.dumps(res, ensure_ascii=False, indent=1)
            md.append(f"## T{t_no} · {w.get('actor')}" + (f" · {w['task_id']}" if w.get("task_id") else "")
                      + f" — MCP `{w['name']}` — t={w['t']}s, {w['elapsed']}s\n\nargs:\n\n"
                      + "````json\n" + json.dumps(w["args"], ensure_ascii=False, indent=1) + "\n````\n\n"
                      + f"result ({len(body)} chars):\n\n````json\n{body}\n````\n")
            rows = res.get("rows") if isinstance(res, dict) else None
            tl.append(f"{w['t']:>7.1f}s  T{t_no} {w.get('actor')}/{w.get('task_id') or '-'}  {w['name']} "
                      f"{json.dumps(w['args'], ensure_ascii=False)[:150]}  -> "
                      + (f"{len(rows)} rows, {len(body)} ch" if rows is not None else body[:120].replace("\n", " ")))
        else:
            tl.append(f"{w['t']:>7.1f}s  {w['kind']} {json.dumps({k: v for k, v in w.items() if k not in ('seq', 'kind', 't')}, ensure_ascii=False)[:200]}")
    if steps:
        md.append("## Stored steps (agent_steps, as the battery exported them)\n")
        for s in steps:
            md.append(f"- seq {s['seq']} `{s['step_type']}` {s.get('tool_name') or ''} actor={s.get('actor')} "
                      f"task={s.get('task_id')} status={s.get('status')} tokens={s.get('prompt_tokens')}/"
                      f"{s.get('completion_tokens')}\n\n  result: {fence(str(s.get('result') or ''))}\n\n"
                      f"  args: {fence(str(s.get('args') or ''))}\n")
        md.append("## Stored answer\n\n" + fence(final.get("answer") or "") + "\n\nmeta:\n\n````json\n"
                  + json.dumps(final.get("meta"), ensure_ascii=False, indent=1) + "\n````\n")
    (HERE / "transcript.md").write_text("\n".join(md))
    (HERE / "timeline.txt").write_text("\n".join(tl) + "\n")
    print("\n".join(tl))


if __name__ == "__main__":
    main()
