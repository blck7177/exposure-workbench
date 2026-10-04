"""Render the Q05 run's record into three views of the same thing.

  wire.jsonl      one line per provider request: the full input exactly as sent (conversation items + the
                  mutable tail), the instructions and tools by file and sha, every output item, the usage.
                  The record keeps only what each request appended; the full input is rebuilt here and its
                  length is checked against the item count the record wrote at request time.
  timeline.txt    one line per step, with the time since the turn started.
  transcript.txt  every text the models read or wrote, in order, unabridged (reasoning stays encrypted).

    .venv/bin/python <this dir>/render_wire.py
"""
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
run = json.load(open(HERE / "battery_out.json"))[0]
turn = run["turns"][0]
at = {s["id"]: s["created_at"] for s in json.load(open(HERE / "db_records.json"))["agent_steps"]}
t0 = datetime.fromisoformat(min(at.values()))
FILES = {"lead": ("instructions_lead.txt", "tools_lead.json"), "sub:issuer": ("instructions_issuer.txt", "tools_issuer.json")}


def secs(step):
    return (datetime.fromisoformat(at[step["id"]]) - t0).total_seconds()


def text_of(item):
    if item.get("type") == "function_call_output":
        try:
            return json.dumps(json.loads(item["output"]), ensure_ascii=False, indent=1)
        except (ValueError, TypeError):
            return item["output"]
    if item.get("type") == "function_call":
        return f"{item['name']}({json.dumps(json.loads(item['arguments']), ensure_ascii=False, indent=1)})"
    if item.get("type") == "reasoning":
        return f"[reasoning, encrypted: {len(item.get('encrypted_content') or '')} chars]"
    return "".join(c.get("text", "") for c in item.get("content", []))


def label(item):
    return item.get("type") if item.get("type") not in (None, "message") else f"{item.get('role')} message"


convs, wire, timeline, transcript = {}, [], [], []
calls = 0
for step in turn["steps"]:
    args = json.loads(step["args"]) if step["args"] else {}
    who = step["actor"] or "lead"
    t = secs(step)
    if step["step_type"] == "llm_call":
        calls += 1
        req, res, use = args["request"], args["response"], args["usage"]
        items = convs.setdefault((who, step["task_id"]), [])
        items.extend(req["items_appended"])
        assert len(items) == req["conversation_items"], (step["seq"], len(items), req["conversation_items"])
        sent = items + req["tail"]
        instr, tools = FILES[who]
        wire.append({"seq": step["seq"], "at": at[step["id"]], "actor": who, "task_id": step["task_id"],
                     "request": {"model": req["model"], "reasoning": {"effort": req["reasoning_effort"]},
                                 "max_output_tokens": req["max_output_tokens"], "store": False,
                                 "include": ["reasoning.encrypted_content"],
                                 "instructions": {"file": instr, "sha": req["instructions_sha"], "chars": req["instructions_chars"]},
                                 "tools": {"file": tools, "names": req["tools"]}, "input": sent},
                     "response": res, "usage": use})
        items.extend(res["output"])
        outs = [o for o in res["output"] if o.get("type") != "reasoning"]
        said = ", ".join(o["name"] for o in outs if o.get("type") == "function_call") or \
               f"message {sum(len(text_of(o)) for o in outs)} ch"
        timeline.append(f"{t:6.1f}s  #{step['seq']:<2} C{calls} · {who:10} · {req['model']} {req['reasoning_effort']:6} "
                        f"in {use['input_tokens']:>5} (cached {use['cached_input_tokens'] or 0:>5}) out {use['output_tokens']:>4} "
                        f"(reasoning {use['reasoning_tokens'] or 0:>3}) · +{len(req['items_appended'])} items, input {len(sent)} items, "
                        f"tail {sum(len(text_of(i)) for i in req['tail'])} ch -> {said}")
        transcript.append(f"\n{'=' * 100}\n#{step['seq']} REQUEST C{calls} · {who}{' · ' + step['task_id'] if step['task_id'] else ''} · "
                          f"{req['model']} effort={req['reasoning_effort']} · instructions {instr} (sha {req['instructions_sha']}) · "
                          f"tools {req['tools']}\n{'=' * 100}")
        for item in req["items_appended"]:
            transcript.append(f"\n--- appended: {label(item)} ---\n{text_of(item)}")
        for item in req["tail"]:
            transcript.append(f"\n--- tail (sent with this request only): {label(item)} ---\n{text_of(item)}")
        transcript.append(f"\n{'-' * 40} RESPONSE · status {res['status']} · usage {json.dumps(use)}")
        for item in res["output"]:
            transcript.append(f"\n--- output: {label(item)} ---\n{text_of(item)}")
    elif step["step_type"] == "tool_call":
        shown = {k: v for k, v in args.items() if k != "why"}
        timeline.append(f"{t:6.1f}s  #{step['seq']:<2}    · {who:10} · {step['tool_name']}({json.dumps(shown, ensure_ascii=False)[:150]}) "
                        f"-> {step['result']}")
        transcript.append(f"\n--- #{step['seq']} TOOL {step['tool_name']} · {who} · status {step['status']} ---\n"
                          f"args: {json.dumps(args, ensure_ascii=False)}\nresult: {step['result']}")
    else:
        timeline.append(f"{t:6.1f}s  #{step['seq']:<2}    · {who:10} · {step['step_type']}: {step['result']}")
        transcript.append(f"\n{'=' * 100}\n#{step['seq']} {step['step_type'].upper()} · {step['status']} · {step['result']}\n"
                          f"{json.dumps({k: v for k, v in args.items() if k != 'text'}, ensure_ascii=False, indent=1)}")

head = (f"Q05-aapl-risk-and-concentration · session {run['session_id']} · message {turn['message_id']} · "
        f"elapsed {turn['elapsed_s']}s · delivery {turn['meta']['delivery']}\nQ: {turn['q']}\n"
        "Times are when each step was recorded, from the first record; a model call is recorded when its response "
        "is back, and the turn had been running for the difference between the elapsed time and the last record.\n")
(HERE / "wire.jsonl").write_text("".join(json.dumps(w, ensure_ascii=False) + "\n" for w in wire))
(HERE / "timeline.txt").write_text(head + "\n" + "\n".join(timeline) + "\n")
(HERE / "transcript.txt").write_text(head + "\n".join(transcript) + f"\n\n{'=' * 100}\nFINAL ANSWER (as delivered)\n{'=' * 100}\n{turn['answer']}\n")
print(f"{len(wire)} requests, {len(timeline)} steps")
