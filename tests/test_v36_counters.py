"""V36 — the battery counter reads a turn with more than one agent in it.

The plan's Phase 0 left three columns for later: how often the lead delegated,
how much of what it asked came back settled, and how the reports were marked.
They are read from what the round already records — `delegate` / `brief` /
`report` / `boundary` steps, the `actor` on each completion, and the lead's
`meta.delegations` / `meta.reports` — so a round from before V36 reads as zeros
and its lead completions equal its round trips, which keeps every earlier series
comparable.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _counters():
    spec = importlib.util.spec_from_file_location("battery_counters", ROOT / "scripts" / "battery_counters.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tally(tmp_path, turns: list[dict]) -> dict:
    p = tmp_path / "round.json"
    p.write_text(json.dumps([{"tag": "T", "session_id": "s", "turns": turns}]))
    return _counters().tally([str(p)])


def _llm(actor, prompt=1000):
    return {"step_type": "llm_call", "status": "completed", "actor": actor, "prompt_tokens": prompt}


V36_TURN = {
    "turn": 1, "answer": "MSFT is nearest at 16.0% [f_1].",
    "steps": [
        _llm(None, 6000),
        {"step_type": "delegate", "tool_name": "delegate", "actor": None, "status": "completed",
         "result": "book_limits_and_triggers [port_001] 4 line(s)"},
        _llm("sub:book_limits_and_triggers", 9000),
        {"step_type": "tool_call", "tool_name": "compile", "actor": "sub:book_limits_and_triggers",
         "status": "completed", "result": "keys: program, skipped"},
        {"step_type": "tool_call", "tool_name": "run", "actor": None, "status": "completed",
         "result": "keys: nodes, settled | nodes: w=vector, r=ranking"},
        {"step_type": "boundary", "tool_name": "run", "actor": "sub:book_limits_and_triggers",
         "status": "completed", "result": "held_back"},
        _llm("sub:book_limits_and_triggers", 12000),
        {"step_type": "brief", "tool_name": "submit", "actor": "sub:book_limits_and_triggers",
         "status": "rejected", "result": "refused: 2 problem(s); uncovered_want"},
        _llm("sub:book_limits_and_triggers", 13000),
        {"step_type": "brief", "tool_name": "submit", "actor": "sub:book_limits_and_triggers",
         "status": "completed", "result": "accepted"},
        {"step_type": "report", "tool_name": "report", "actor": "sub:book_limits_and_triggers",
         "status": "completed", "result": "verified: Issuer-concentration room"},
        _llm(None, 8200),
        {"step_type": "answer", "tool_name": "answer", "actor": None, "status": "completed",
         "result": "accepted", "args": json.dumps({"text": "MSFT is nearest at 16.0% [f_1]."})},
    ],
    "meta": {"prompt_tokens": 8200, "completions": 2,
             "delegations": [{"domain": "book_limits_and_triggers", "task_id": "tsk_1", "status": "partial",
                              "coverage": {"asked": 4, "done": 3, "not_done": 1, "refused": 0},
                              "cost": {"completions": 3, "evidence_calls": 1}}],
             "reports": [{"domain": "book_limits_and_triggers", "report_id": "rep_1", "status": "verified"}]},
}


def test_a_v36_turn_is_read_by_who_did_what(tmp_path):
    c = _tally(tmp_path, [V36_TURN])
    assert c["delegate_calls_mean"] == 1
    assert c["analysts"] == 1 and c["analysts_by_status"] == {"partial": 1}
    assert c["coverage"] == {"asked": 4, "done": 3, "not_done": 1, "refused": 0}
    assert c["coverage_done_share"] == 0.75
    assert c["submits"] == 2 and c["submits_rejected"] == 1 and c["submits_per_analyst"] == 2
    assert c["handoff_refusals"] == {"uncovered_want": 1}
    assert c["reports_by_status"] == {"verified": 1}
    assert c["boundaries_minted"] == 1
    # completions split by actor: the lead's two, the analyst's three
    assert c["lead_completions_median"] == 2 and c["sub_completions_median"] == 3
    assert c["sub_completions_total"] == 3
    # the lead's own peak, not the sum of every completion in the turn
    assert c["lead_prompt_peak_median"] == 8200
    assert c["prompt_tokens_median"] == 6000 + 9000 + 12000 + 13000 + 8200
    # the earlier series still read the same steps: five completions, two tool calls
    assert c["round_trips_median"] == 5 and c["tool_calls_median"] == 2


def test_a_round_before_v36_reads_as_zeros_and_keeps_its_series(tmp_path):
    turn = {"turn": 1, "answer": "AMZN 14.2%.", "meta": {"prompt_tokens": 20000},
            "steps": [_llm(None, 5000), {"step_type": "request", "tool_name": "request", "status": "completed"},
                      {"step_type": "tool_call", "tool_name": "run", "status": "completed", "result": "keys: nodes"},
                      _llm(None, 15000)]}
    c = _tally(tmp_path, [turn])
    assert c["delegate_calls_mean"] == 0 and c["analysts"] == 0 and c["submits"] == 0
    assert c["analysts_by_status"] == {} and c["handoff_refusals"] == {} and c["reports_by_status"] == {}
    assert c["coverage"] == {"asked": 0, "done": 0, "not_done": 0, "refused": 0} and c["coverage_done_share"] == 0
    assert c["lead_completions_median"] == c["round_trips_median"] == 2 and c["sub_completions_total"] == 0
    assert c["lead_prompt_peak_median"] == 20000


def test_a_refusal_the_summary_does_not_name_is_counted_as_unstated(tmp_path):
    turn = {"turn": 1, "answer": "", "meta": {},
            "steps": [{"step_type": "brief", "tool_name": "submit", "actor": "sub:x", "status": "rejected",
                       "result": "refused"}]}
    assert _tally(tmp_path, [turn])["handoff_refusals"] == {"unstated": 1}
