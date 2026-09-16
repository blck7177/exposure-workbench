#!/usr/bin/env python3
"""The V37 §4 acceptance lines that a script can read, for one round, from the
round file and the fixture database the round ran on. The false-statement line
is a reading, not a count, and is not here.

    python v37c_lines.py docs/spikes/v37/V37C.json --db exposure_battery
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import re
import statistics
import subprocess
import sys

FID = re.compile(r"\bf_[0-9a-f]{12}\b")
FALLBACK = ("the domain analyst did not file a brief", "the domain analyst stopped without filing a brief")


def _j(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:  # noqa: BLE001
            return {}
    return x if isinstance(x, (dict, list)) else {}


def q(db: str, sql: str) -> list[list[str]]:
    r = subprocess.run(["docker", "exec", "exposure-postgres", "psql", "-U", "exposure", "-d", db,
                        "-AtF", "\x1f", "-c", sql], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr)
    return [l.split("\x1f") for l in r.stdout.split("\x1e") and r.stdout.splitlines() if l]


def steps_of(db: str, sid: str) -> list[dict]:
    sql = ("select json_agg(t order by t.seq) from (select seq, step_type, tool_name, actor, status, args, "
           "result_summary, evidence_refs, prompt_tokens, completion_tokens from agent_steps "
           f"where session_id='{sid}') t")
    out = subprocess.run(["docker", "exec", "exposure-postgres", "psql", "-U", "exposure", "-d", db, "-Atc", sql],
                         capture_output=True, text=True).stdout.strip()
    return json.loads(out) if out and out != "" else []


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("round_json")
    ap.add_argument("--db", required=True)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    data = json.load(open(a.round_json))

    spec = importlib.util.spec_from_file_location("bc", "scripts/battery_counters.py")
    bc = importlib.util.module_from_spec(spec); spec.loader.exec_module(bc)
    tally = bc.tally([a.round_json])

    per_q, L = [], collections.OrderedDict()
    answered = all_lines_done = 0
    asked = done = 0
    fallback_gate = 0
    empty_after_big_read = empty_replies = 0
    inferred = tool_rows = 0
    answer_repeats = answer_repeat_turns = 0
    unrecorded_sub_calls = 0
    portfolio_type = 0
    date_expected_all = 0
    sub_peaks, lead_peaks = [], []
    gate_refusal_reasons = collections.Counter()

    for c in data:
        t = c["turns"][0]
        meta = _j(t.get("meta"))
        dels = meta.get("delegations") or []
        ok = bool(t.get("answer")) and "gate" not in meta and not t.get("error")
        answered += ok
        a_ = sum((d.get("coverage") or {}).get("asked", 0) for d in dels)
        d_ = sum((d.get("coverage") or {}).get("done", 0) for d in dels)
        asked += a_; done += d_
        every = bool(dels) and all((d.get("coverage") or {}).get("done") == (d.get("coverage") or {}).get("asked") for d in dels)
        all_lines_done += ok and every
        for r in meta.get("gate_refusals") or []:
            gate_refusal_reasons[r] += 1

        steps = steps_of(a.db, c["session_id"])
        # ledger membership before a step: facts of completed steps before it
        seen_ids: set[str] = set()
        answers_sent: dict[str, int] = {}
        speaking = None
        sub_peak: dict[str, int] = collections.defaultdict(int)
        lead_peak = 0
        window_announced = None      # (actor, n) of the last sub completion
        window_recorded = 0

        def close_window():
            nonlocal unrecorded_sub_calls
            if window_announced is not None:
                unrecorded_sub_calls += max(0, window_announced[1] - window_recorded)

        for st in steps:
            kind, actor, args = st["step_type"], st["actor"], _j(st["args"])
            if kind == "llm_call":
                if actor and actor.startswith("sub:"):
                    sub_peak[actor] = max(sub_peak[actor], st["prompt_tokens"] or 0)
                    close_window()
                    m = re.search(r"(\d+) tool call", st["result_summary"] or "")
                    window_announced = (actor, int(m.group(1)) if m else 0)
                    window_recorded = 0
                    if "0 tool calls" in (st["result_summary"] or ""):
                        empty_replies += (st["completion_tokens"] or 0) <= 3
                        rd = (args or {}).get("read") or {}
                        empty_after_big_read += (st["completion_tokens"] or 0) <= 3 and (rd.get("chars") or 0) > 9000
                else:
                    lead_peak = max(lead_peak, st["prompt_tokens"] or 0)
                    close_window(); window_announced = None
            elif kind in ("tool_call", "delegation", "brief") and window_announced is not None:
                if not (kind == "brief" and set(args or {}) == {"task_id"}):   # the fallback row is not a call
                    window_recorded += 1
            elif kind in ("delegate", "answer", "read_report"):
                close_window(); window_announced = None

            if actor:
                speaking = actor
            elif kind in ("delegate", "answer", "respond"):
                speaking = None
            if kind in ("tool_call", "delegation"):
                tool_rows += 1
                inferred += actor is None and speaking is not None

            if kind == "answer":
                text = (args or {}).get("text") or ""
                h = hashlib.sha256(text.encode()).hexdigest()
                if h in answers_sent:
                    answer_repeats += 1
                answers_sent[h] = answers_sent.get(h, 0) + 1
                if st["status"] != "completed":
                    for fid in set(FID.findall(text)) - seen_ids:
                        row = q(a.db, f"select left(text,80) from facts where id='{fid}'")
                        if row and row[0][0].startswith(FALLBACK):
                            fallback_gate += 1
            if st["status"] == "completed":
                for e in (_j(st["evidence_refs"]) or []):
                    for r in (e.get("facts") or []) if isinstance(e, dict) else []:
                        if isinstance(r, dict) and r.get("id"):
                            seen_ids.add(r["id"])
            if kind == "brief":
                for p in (args or {}).get("problems") or []:
                    date_expected_all += isinstance(p, dict) and p.get("reason") == "date_expected"
        close_window()
        answer_repeat_turns += any(v > 1 for v in answers_sent.values())
        sub_peaks += list(sub_peak.values())
        if lead_peak:
            lead_peaks.append(lead_peak)
        per_q.append((c["tag"][:3], "✓" if ok else "✗", f"{d_}/{a_}", len(dels),
                      ",".join(sorted({d.get("status") for d in dels})), meta.get("gate_refusals") or []))

    ids = ",".join(f"'{c['session_id']}'" for c in data)
    portfolio_type = int(q(a.db, f"select count(*) from facts where session_id in ({ids}) and kind='absence' "
                                 "and text like 'run(): the program did not run%' and text ~ '— portfolio: '")[0][0])
    type_facts = int(q(a.db, f"select count(*) from facts where session_id in ({ids}) and kind='absence' "
                               "and text like 'run(): the program did not run%'")[0][0])
    bd = tally["by_domain"].get("book_market_risk", {})

    L["answered"] = f"{answered}/{len(data)}"
    L["answered_and_every_delegated_line_done"] = f"{all_lines_done}/{answered}"
    L["coverage_done_over_asked"] = f"{done}/{asked} = {done / asked:.2f}" if asked else "-"
    L["book_market_risk_runs_clean"] = f"{bd.get('clean', 0)}/{bd.get('runs', 0)}"
    L["run_type_errors_over_runs"] = f"{tally['type_errors']}/{sum(v.get('runs', 0) for v in tally['by_domain'].values())}"
    L["run_type_error_facts / portfolio class"] = f"{type_facts} / {portfolio_type}"
    L["gate_not_on_ledger_on_fallback_facts"] = fallback_gate
    L["handoff_first_cause_date_expected"] = tally["handoff_refusals"].get("date_expected", 0)
    L["handoff_problems_date_expected_all"] = date_expected_all
    L["sub_3tok_empty_replies (after >9k read)"] = f"{empty_replies} ({empty_after_big_read})"
    L["lead_answer_repeats (turns)"] = f"{answer_repeats} ({answer_repeat_turns})"
    L["gate_refusals_repeated_answer"] = gate_refusal_reasons.get("repeated_answer", 0)
    L["sub_calls_announced_not_recorded"] = unrecorded_sub_calls
    L["inferred_edges / tool rows"] = f"{inferred}/{tool_rows}"
    L["lead_prompt_peak_median (provider tokens)"] = statistics.median(lead_peaks) if lead_peaks else None
    L["sub_prompt_peak_median / p90"] = (f"{statistics.median(sub_peaks):.0f} / {sorted(sub_peaks)[int(.9 * (len(sub_peaks) - 1))]}"
                                         if sub_peaks else "-")
    L["gate_refusals_by_reason"] = dict(gate_refusal_reasons.most_common())
    for k, v in L.items():
        print(f"{k:44s} {v}")
    print("per question: tag ok done/asked delegations statuses gate_refusals")
    for row in per_q:
        print("  ", *row)
    if a.json:
        json.dump({"lines": L, "per_question": per_q, "tally": tally}, open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main(sys.argv[1:])
