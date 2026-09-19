"""V1 step 7, before the round is run: the instrument reads a V1 turn, and the model is a variable.

`scripts/battery_counters.py` counted `run` and `compute` — the surface V1 retired — so a V1 round
read as a desk that called nothing and refused nothing; and `OPENAI_MODEL=… conversation_battery`
ran on the model in `.env` (plan §5, item 5). What plan step 7 measures is read off what a V1 turn
records: the step that says what a call GOT, the `why` on every call, the problems on a refused
answer or brief by the style guide's rule, the model on every completion.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tally(tmp_path, turns: list[dict]) -> dict:
    p = tmp_path / "round.json"
    p.write_text(json.dumps([{"tag": "T", "session_id": "s", "turns": turns}]))
    return _script("battery_counters").tally([str(p)])


def _llm(actor, prompt, model):
    return {"step_type": "llm_call", "status": "completed", "actor": actor, "prompt_tokens": prompt,
            "result": f"{model}: 1 tool call"}


def _call(verb, args: dict, result: str, status="completed", actor="sub:risk", step_type="tool_call"):
    return {"step_type": step_type, "tool_name": verb, "actor": actor, "status": status, "result": result,
            "args": json.dumps(args)}


RISK = "sub:risk"
V1_TURN = {
    "turn": 1, "answer": "MSFT is in warning at 16.0%.", "elapsed_s": 41.0,
    "steps": [
        _llm(None, 6100, "gpt-5.6-sol"),
        {"step_type": "delegate", "tool_name": "ask", "actor": None, "status": "completed", "result": "risk [port_001] 2 line(s)"},
        _llm(RISK, 7200, "gpt-5.4-mini"),
        _call("list", {"what": "book", "subject": "port_001", "why": "line 1: which runs the book has"},
              'r_a1 list(what="book", subject="port_001") → 14 names'),
        _call("book_read", {"book": "port_001", "table": "limit_checks", "why": "line 1 asks which checks are nearest their tiers"},
              'r_a2 book_read(book="port_001", table="limit_checks") → 60 rows'),
        _llm(RISK, 11800, "gpt-5.4-mini"),
        _call("book_read", {"book": "port_001", "table": "holdings", "why": "the same table by another name"},
              "invalid arguments: 1 problem(s)", status="rejected"),
        {"step_type": "boundary", "tool_name": "book_read", "actor": RISK, "status": "completed",
         "result": 'r_a3 book_read(book="port_001", table="holdings") → 1 row | refused: invalid_arguments'},
        _call("calc", {"op": "add", "inputs": ["f_1", "f_2"], "why": ""},
              'r_a4 calc(op="add", inputs=["f_1", "f_2"]) → 1 row | refused: incompatible_units'),
        _call("metric", {"name": "price.volatility", "subject": ["MSFT", "ZZZZ"], "why": "line 2: whose volatility rose"},
              'r_a5 metric(name="price.volatility", subject=["MSFT", "ZZZZ"]) → 2 rows | refused: no_price_data'),
        _call("start", {"kind": "exposure_run", "subject": "port_001", "why": "line 2 needs today's run"},
              'r_a6 start(kind="exposure_run", subject="port_001") → started run_9; it runs after this turn and returns nothing to it',
              step_type="delegation"),
        _llm(RISK, 12400, "gpt-5.4-mini"),
        {"step_type": "brief", "tool_name": "submit", "actor": RISK, "status": "rejected",
         "result": "refused: 2 problem(s); status_conflict",
         "args": json.dumps({"task_id": "tsk_1", "problems": [{"reason": "status_conflict", "rule": 6, "where": "line 1"},
                                                              {"reason": "uncovered_line", "where": "coverage"}]})},
        _llm(RISK, 12900, "gpt-5.4-mini"),
        {"step_type": "brief", "tool_name": "submit", "actor": RISK, "status": "completed", "result": "accepted"},
        {"step_type": "report", "tool_name": "report", "actor": RISK, "status": "completed", "result": "verified: 5 call(s), 2 line(s) settled"},
        _llm(None, 7400, "gpt-5.6-sol"),
        {"step_type": "answer", "tool_name": "answer", "actor": None, "status": "rejected",
         "result": "refused: unpointed_figure; 2 problem(s), all listed; the first: …",
         "args": json.dumps({"text": "x" * 3990}),                      # the list is past the cap inside args
         "problems": json.dumps([{"reason": "unpointed_figure", "rule": 1, "sentence": "S1"},
                                 {"reason": "sense_conflict", "rule": 6, "sentence": "S2"}])},
        _llm(None, 7900, "gpt-5.6-sol"),
        {"step_type": "answer", "tool_name": "answer", "actor": None, "status": "completed", "result": "accepted"},
    ],
    "meta": {"prompt_tokens": 7900, "completions": 3,
             "delegations": [{"domain": "risk", "task_id": "tsk_1", "status": "settled",
                              "coverage": {"asked": 2, "settled": 2, "unsettled": 0, "refused": 0},
                              "cost": {"completions": 4, "evidence_calls": 4, "starts": 1}}],
             "reports": [{"domain": "risk", "report_id": "rep_1", "status": "verified"}]},
}


def test_a_v1_turn_is_read_for_what_step_seven_measures(tmp_path):
    out = _tally(tmp_path, [V1_TURN])
    # asks a turn, tasks an ask, calls a task — and V1's `settled` is the series V36 called `done`
    assert out["delegate_calls_mean"] == 1 and out["tasks_per_turn_mean"] == 1 and out["evidence_calls_per_task_median"] == 4
    assert out["coverage"] == {"asked": 2, "done": 2, "not_done": 0, "refused": 0} and out["coverage_done_share"] == 1.0
    # every call, and how it came back: two read, two refused among their rows, one never ran
    risk = out["by_analyst"]["risk"]
    assert (risk["calls"], risk["read"], risk["refused"], risk["not_run"]) == (6, 3, 2, 1)
    assert risk["verb.book_read"] == 2 and risk["verb.calc"] == 1 and risk["verb.start"] == 1
    assert out["analyst_calls_refused_share"] == 0.5
    # the why: one call said none; the rest are read for length and for naming the line they serve
    assert out["why_missing"] == 1 and out["why_words_median"] == 6 and out["why_names_a_line_share"] == 0.8
    # prompt peaks, apart: the lead's own, and the analysts'
    assert out["lead_prompt_peak_median"] == 7900 and out["analyst_prompt_peak_median"] == 12900
    # what the checks refused, by the style guide's rule — every problem, not the first of each refusal
    assert out["check_problems_by_rule"] == {"1": 1, "6": 2, "shape": 1}
    assert (out["sense_conflicts"], out["status_conflicts"]) == (1, 1)
    # what the desk refused, and how much of it was arithmetic
    assert out["absences_by_code"] == {"incompatible_units": 1, "no_price_data": 1}
    assert out["absences_arithmetic_share"] == 0.5 and out["absences_from_calc"] == 1
    assert out["refusals"]["algebra"]["count"] == 1 and out["refusals"]["data"]["count"] == 1
    assert out["refusals"]["spelling"]["count"] == 1                     # the call that never ran, counted once
    # who ran on what
    assert out["completions_by_model"] == {"lead": {"gpt-5.6-sol": 3}, "analysts": {"gpt-5.4-mini": 4}}


def test_a_round_from_before_v1_reads_as_zeros_here_and_keeps_its_own_series(tmp_path):
    old = {"turn": 1, "answer": "x", "steps": [
        {"step_type": "llm_call", "status": "completed", "actor": None, "prompt_tokens": 5000},
        {"step_type": "tool_call", "tool_name": "run", "actor": "sub:book_market_risk", "status": "completed",
         "result": "keys: nodes, settled | nodes: w=vector", "args": "{}"}], "meta": {}}
    out = _tally(tmp_path, [old])
    assert out["analyst_calls"] == 0 and out["by_analyst"] == {} and out["absences"] == 0
    assert out["by_domain"]["book_market_risk"]["runs"] == 1             # the V37 series still reads its `run`
    assert out["completions_by_model"] == {"lead": {}, "analysts": {}}


def test_a_why_survives_arguments_cut_at_the_batterys_cap():
    counters = _script("battery_counters")
    cut = json.dumps({"why": "line 3 asks for the trend", "inputs": ["f_" + "a" * 12] * 400})[:4000]
    with pytest.raises(ValueError):
        json.loads(cut)
    assert counters.why_of(cut) == "line 3 asks for the trend"
    assert counters.why_of(json.dumps({"book": "port_001"})) is None


# ── the model is a variable ──────────────────────────────────────────────────

def test_an_analyst_and_the_lead_can_run_on_different_models(monkeypatch):
    from exposure_workbench.agents import llm_session
    from exposure_workbench.app_state import settings as settings_mod
    for var in ("LEAD_MODEL", "ANALYST_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings_mod, "_settings", None)
    assert llm_session.model_for(None) is None and llm_session.model_for("sub:risk") is None     # as deployed: one setting
    monkeypatch.setenv("LEAD_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("ANALYST_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(settings_mod, "_settings", None)
    assert llm_session.model_for(None) == "gpt-5.6-sol" and llm_session.model_for("sub:issuer") == "gpt-5.4-mini"
    monkeypatch.setattr(settings_mod, "_settings", None)


async def test_the_completion_is_made_on_the_actors_model(monkeypatch):
    from exposure_workbench.agents import llm_session
    seen = {}

    async def _chat(messages, tools=None, **kw):
        seen.update(kw)
        return "ok", None, {"model": kw.get("model") or "default", "prompt_tokens": 1, "completion_tokens": 1}

    class _Db:
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
        async def commit(self): pass

    async def _record(db, session_id, **kw):
        return "step"
    monkeypatch.setattr(llm_session.llm_client, "chat_with_tools", _chat)
    monkeypatch.setattr(llm_session.trace_service, "record_step", _record)
    monkeypatch.setattr(llm_session, "model_for", lambda actor: "weak" if str(actor or "").startswith("sub:") else "strong")
    lead = llm_session.LlmSession(lambda: _Db(), "sess", "msg")
    await lead.chat(messages=[])
    assert seen["model"] == "strong"
    await lead.for_actor("sub:market").chat(messages=[])
    assert seen["model"] == "weak"
    await lead.chat(messages=[], model="asked-for")                      # a caller that names one keeps it
    assert seen["model"] == "asked-for"


def test_the_operators_model_survives_the_batterys_dotenv(monkeypatch, tmp_path):
    """`.env` overrides the shell for keys and databases, on purpose. The model is the variable of a
    measured round: what the operator set for it is kept."""
    (tmp_path / ".env").write_text("OPENAI_MODEL=from-dotenv\nLEAD_MODEL=from-dotenv\nOPENAI_API_KEY=k\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_MODEL", "asked-for-on-the-command-line")
    monkeypatch.delenv("LEAD_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "stale-shell-key")
    _script("conversation_battery")
    assert os.environ["OPENAI_MODEL"] == "asked-for-on-the-command-line"    # the operator's
    assert os.environ["LEAD_MODEL"] == "from-dotenv"                         # not set by the operator: .env's
    assert os.environ["OPENAI_API_KEY"] == "k"                               # everything else is still .env's
