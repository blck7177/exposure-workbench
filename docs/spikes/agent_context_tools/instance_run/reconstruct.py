"""Rebuild, from the record of ONE real turn, what each completion was sent and what came back.

Input: the turn's rows exported from the fixture database (q01_*.json beside this file).
Everything rebuilt here goes through the repo's own functions: the briefing is read again from the same
fixture database (read-only, rolled back), prompts are assembled the way agents/meta_agent and
agents/sub_analyst assemble them, tool rows are rendered from the recorded fact records by
services/facts.line, and the answer check is re-run on the recorded drafts. Where the record holds a
number for the same thing (prompt_chars on each llm_call step), the rebuilt value is printed beside it.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = Path("/home/ubuntu/exposure-workbench")
os.chdir(REPO)
sys.path.insert(0, str(REPO / "src"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env", override=True)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from exposure_workbench.agents import delegation as dl, handoff, meta_agent, sub_analyst  # noqa: E402
from exposure_workbench.analytics import handbook  # noqa: E402
from exposure_workbench.auth.context import current_user_ctx  # noqa: E402
from exposure_workbench.services import analysis_state as AS, answer_check, briefing as briefing_svc  # noqa: E402
from exposure_workbench.services import context_budget as cb, fact_boundary, facts as F  # noqa: E402
from exposure_workbench.services.ledger import Ledger, facts_in  # noqa: E402
from exposure_workbench.tools import faces  # noqa: E402
from exposure_workbench.tools.registries import build_analyst_registry, build_meta_registry  # noqa: E402

OWNER = "user_3IDBMeAxLTbecvGorzwV7FCeroR"
URL = "postgresql+asyncpg://app_rls:app_rls_pw@localhost:5433/exposure_battery"
DENY = ("submit_brief", "start")          # what the round ran with

steps = json.loads((HERE / "q01_steps.json").read_text())
messages_rows = json.loads((HERE / "q01_messages.json").read_text())
state_row = json.loads((HERE / "q01_state.json").read_text())[0]
report = json.loads((HERE / "q01_reports.json").read_text())[0]
QUESTION = next(m["content"] for m in messages_rows if m["role"] == "user")
FINAL = next(m for m in messages_rows if m["role"] == "assistant")
out: dict = {"question": QUESTION}


def tok(x) -> int:
    return cb.count_tokens(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False, default=str))


def chars(messages) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


async def briefing() -> dict:
    current_user_ctx.set(OWNER)
    engine = create_async_engine(URL)
    mk = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with mk() as db:
            brief = await briefing_svc.for_question(db, QUESTION)
            await db.rollback()
    finally:
        await engine.dispose()
    return brief


def lead_tools() -> list[dict]:
    reg = build_meta_registry()
    lead_deny = tuple(dict.fromkeys([*DENY, *(n for n in faces.FACE_META_AGENT if n not in faces.FACE_LEAD_READ)]))
    direct = [t for t in reg.schemas(faces.FACE_META_AGENT) if t["function"]["name"] in faces.FACE_LEAD_READ
              and t["function"]["name"] not in lead_deny]
    return direct + [dl.ASK_TOOL, dl.OPEN_TOOL]


def ledger_upto(seq: int) -> Ledger:
    """The session ledger as it stood after step `seq`: every fact of every completed step so far."""
    recs = []
    for s in steps:
        if s["seq"] <= seq and s["status"] == "completed":
            recs += facts_in(s["evidence_refs"])
    return Ledger.of(recs)


def presented(step: dict) -> dict:
    """One primitive's result as the model read it: the head and the rows (services/fact_adapters.present)."""
    facts = facts_in(step["evidence_refs"])
    said = step["result_summary"] or ""
    return {"pull": said.split(" ", 1)[0], "head": said.split(" | refused:", 1)[0], "rows": [F.line(f) for f in facts]}


async def main() -> None:
    brief = await briefing()
    out["briefing_for_lead"] = briefing_svc.for_lead(brief)
    llm = [s for s in steps if s["step_type"] == "llm_call"]

    # ── lead, completion 1 ───────────────────────────────────────────────────────────────────────
    state0 = AS.new_turn(state_row["session_id"], state_row["message_id"], QUESTION, brief, None, ledger=Ledger())
    state0.id, state0.version = state_row["id"], 1
    state0.budget = {"lead_completions_used": 0, "lead_completions_limit": 16, "lead_evidence_calls": 0,
                     "lead_evidence_calls_limit": meta_agent.LEAD_EVIDENCE_CALLS}
    snap = copy.deepcopy(state0)
    snap.id = f"{state0.id}_view0"
    desk_block = meta_agent.BRIEFING_TAG + "\n" + json.dumps(briefing_svc.for_lead(brief), ensure_ascii=False, default=str) + "\n</desk>"
    roster_block = meta_agent.ROSTER_TAG + "\n" + json.dumps(handbook.roster(), ensure_ascii=False) + "\n</roster>"
    readings_block = meta_agent.READINGS_TAG + "\n" + handbook.meaning_layer() + "\n</readings>"
    state_block = meta_agent.STATE_TAG + "\n" + json.dumps(AS.view(snap, Ledger()), ensure_ascii=False, default=str) + "\n</state>"
    lead_msgs = [{"role": "system", "content": meta_agent._SYSTEM}, {"role": "system", "content": desk_block},
                 {"role": "system", "content": roster_block}, {"role": "system", "content": readings_block},
                 {"role": "system", "content": state_block}, {"role": "user", "content": QUESTION}]
    tools = lead_tools()
    rec1 = llm[0]
    out["lead_c1"] = {
        "blocks": {"role+style guide": [len(meta_agent._SYSTEM), tok(meta_agent._SYSTEM)], "desk": [len(desk_block), tok(desk_block)],
                   "roster": [len(roster_block), tok(roster_block)], "readings": [len(readings_block), tok(readings_block)],
                   "state": [len(state_block), tok(state_block)], "user question": [len(QUESTION), tok(QUESTION)],
                   "tool schemas": [len(json.dumps(tools)), tok(json.dumps(tools))]},
        "tools": [t["function"]["name"] for t in tools],
        "rebuilt_prompt_chars": chars(lead_msgs), "recorded_prompt_chars": rec1["args"]["delivered"]["prompt_chars"],
        "rebuilt_prompt_tokens(tiktoken)": cb.count_prompt(lead_msgs, tools), "recorded_prompt_tokens(provider)": rec1["prompt_tokens"],
        "completion_tokens": rec1["completion_tokens"],
        "desk_block": desk_block, "state_block": state_block,
    }

    # ── the ask ──────────────────────────────────────────────────────────────────────────────────
    ask = next(s for s in steps if s["step_type"] == "delegate")
    out["ask"] = ask["args"]
    t = ask["args"]["tasks"][0]
    task = dl.Task(task_id=t["task_id"], analyst=t["analyst"], subjects=tuple(t["subjects"]),
                   lines=tuple(x.split(". ", 1)[1] if ". " in x[:4] else x for x in t["lines"]),
                   context=t.get("context"), follow_up_of=t.get("follow_up_of"), input_refs=tuple(t.get("input_refs") or ()))

    # ── analyst, completion 1 ────────────────────────────────────────────────────────────────────
    sys_text = sub_analyst.system_text(task.analyst)
    user_text = (sub_analyst.TASK_TAG + "\n" + json.dumps(task.as_dict(), ensure_ascii=False, default=str) + "\n</task>\n"
                 + sub_analyst.COVERAGE_TAG + "\n" + json.dumps(sub_analyst._coverage_of(task, brief), ensure_ascii=False, default=str)
                 + "\n</coverage>\n<question source=\"the user\">\n" + QUESTION + "\n</question>")
    areg = build_analyst_registry(task.analyst)
    atools = [x for x in areg.schemas(list(faces.ANALYST_FACES[task.analyst])) if x["function"]["name"] not in DENY] + [handoff.SUBMIT_TOOL]
    amsgs = [{"role": "system", "content": sys_text}, {"role": "user", "content": user_text}]
    rec_a1 = llm[1]
    out["analyst_c1"] = {
        "blocks": {"system (role + style guide + issuer chapter)": [len(sys_text), tok(sys_text)],
                   "user (task + coverage + question)": [len(user_text), tok(user_text)],
                   "tool schemas": [len(json.dumps(atools)), tok(json.dumps(atools))]},
        "tools": [x["function"]["name"] for x in atools],
        "rebuilt_prompt_chars": chars(amsgs), "recorded_prompt_chars": rec_a1["args"]["delivered"]["prompt_chars"],
        "rebuilt_prompt_tokens(tiktoken)": cb.count_prompt(amsgs, atools), "recorded_prompt_tokens(provider)": rec_a1["prompt_tokens"],
        "user_text": user_text,
    }

    # ── every tool call, as the caller read it ───────────────────────────────────────────────────
    out["tool_calls"] = [{"seq": s["seq"], "actor": s["actor"], "tool": s["tool_name"], "status": s["status"],
                          "args": s["args"], "duration_ms": s["duration_ms"], "read": presented(s),
                          "facts": len(facts_in(s["evidence_refs"]))}
                         for s in steps if s["step_type"] in ("tool_call", "delegation", "boundary")]

    # ── the submit ───────────────────────────────────────────────────────────────────────────────
    brief_step = next(s for s in steps if s["step_type"] == "brief")
    out["submit"] = brief_step["args"]

    # ── what the lead read next: the receipt and the refreshed STATE ─────────────────────────────
    led = ledger_upto(brief_step["seq"] + 1)
    state = AS._from_row(type("Row", (), state_row)())
    receipt = {"returns": [{"task_id": task.task_id, "analyst": task.analyst, "protocol": handoff.PROTOCOL,
                            "execution": report["status"], "stop_reason": report["brief"].get("stop_reason"),
                            "evidence": [e["id"] for e in report["brief"]["evidence"] if e.get("selected")],
                            "available_evidence": len([e for e in report["brief"]["evidence"]]),
                            "notes": [n["id"] for n in report["brief"]["notes"]], "report_id": report["id"], "made": []}]}
    view_state = copy.deepcopy(state)
    view_state.budget = {"lead_completions_used": 1, "lead_completions_limit": 16, "lead_evidence_calls": 0, "lead_evidence_calls_limit": 16}
    view_state.id = f"{state.id}_view1"
    view = AS.view(view_state, led)
    state_block2 = meta_agent.STATE_TAG + "\n" + json.dumps(view, ensure_ascii=False, default=str) + "\n</state>"
    out["lead_c2"] = {"receipt": receipt, "receipt_chars": len(json.dumps(receipt, ensure_ascii=False)),
                      "recorded_read_chars": llm[4]["args"]["read"]["chars"],
                      "state_block_chars": len(state_block2), "state_block_tokens": tok(state_block2),
                      "state_view": view, "recorded_prompt_chars": llm[4]["args"]["delivered"]["prompt_chars"],
                      "recorded_prompt_tokens(provider)": llm[4]["prompt_tokens"]}

    # ── the answer: both drafts through the same check, and the refusal the lead was sent ────────
    answers = [s for s in steps if s["step_type"] == "answer"]
    full = ledger_upto(10**9)
    drafts = []
    for a in answers:
        text = a["args"]["text"]
        verdict = fact_boundary.check_text("answer", text, full, question=QUESTION)
        drafts.append({"seq": a["seq"], "status": a["status"], "text": text, "recorded_problems": a["args"].get("problems"),
                       "recheck_ok": verdict.ok, "recheck_problems": [{k: p.get(k) for k in ("reason", "rule", "sentence", "figure", "id")} for p in verdict.problems],
                       "refusal_message": None if verdict.ok else meta_agent._refusal_message(verdict),
                       "sentences": [{"tag": x["tag"], "checked": x["checked"], "text": x["text"]} for x in verdict.sentences]})
    out["answers"] = drafts
    out["final"] = {"text": FINAL["content"], "citations": FINAL["citations"],
                    "meta": {k: v for k, v in FINAL["meta"].items() if k != "blocks"},
                    "blocks_sample": FINAL["meta"]["blocks"][:2]}
    out["llm_calls"] = [{"seq": s["seq"], "actor": s["actor"] or "lead", "prompt_tokens": s["prompt_tokens"],
                         "completion_tokens": s["completion_tokens"], "said": s["result_summary"],
                         "read": s["args"].get("read"), "prompt_chars": s["args"]["delivered"]["prompt_chars"],
                         "facts_in_prompt": len(s["args"]["delivered"]["facts"]), "created_at": s["created_at"]} for s in llm]
    (HERE / "q01_reconstructed.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))

    c1, a1 = out["lead_c1"], out["analyst_c1"]
    print("LEAD completion 1  prompt chars: rebuilt", c1["rebuilt_prompt_chars"], "| recorded", c1["recorded_prompt_chars"],
          "  tokens: tiktoken", c1["rebuilt_prompt_tokens(tiktoken)"], "| provider", c1["recorded_prompt_tokens(provider)"])
    for k, v in c1["blocks"].items():
        print(f"   {k:<22} {v[0]:>6} chars {v[1]:>6} tok")
    print("ANALYST completion 1 prompt chars: rebuilt", a1["rebuilt_prompt_chars"], "| recorded", a1["recorded_prompt_chars"],
          "  tokens: tiktoken", a1["rebuilt_prompt_tokens(tiktoken)"], "| provider", a1["recorded_prompt_tokens(provider)"])
    for k, v in a1["blocks"].items():
        print(f"   {k:<44} {v[0]:>6} chars {v[1]:>6} tok")
    print("LEAD completion 2  receipt chars: rebuilt", out["lead_c2"]["receipt_chars"], "| recorded read", out["lead_c2"]["recorded_read_chars"],
          "| STATE block", out["lead_c2"]["state_block_chars"], "chars", out["lead_c2"]["state_block_tokens"], "tok")
    for d in drafts:
        print("ANSWER step", d["seq"], d["status"], "| recheck ok:", d["recheck_ok"], "| recorded problems:",
              [(p.get("reason"), p.get("sentence")) for p in d["recorded_problems"] or []], "| recheck:", [(p["reason"], p["sentence"]) for p in d["recheck_problems"]])


asyncio.run(main())
