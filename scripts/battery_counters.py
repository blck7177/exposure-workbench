#!/usr/bin/env python3
"""V30 Phase 0 — the two counters the instrument keeps apart, plus the mechanics.

The rubric is a judged distribution. THIS is countable and reproducible, and it
splits every refusal by whose work it was:

  spelling   the call was written wrongly for the protocol (a name at the wrong
             door, an id the desk never showed, two shapes in one call, an
             address the schema refused). V30 removes the protocol; this class
             is what should go to zero.
  gate       the answer's pointers or prose were refused (unsourced figure,
             not on ledger, malformed, quote not verbatim).
  algebra    the typed calculator or a floor refused a combination — the
             desk being right about the world. These stay.
  data       the desk does not hold it (not filed, not prepared, no prices).
  system     an adapter or transport failure, budget, quota.

    python scripts/battery_counters.py docs/spikes/v30/V26_R1.json [more.json] [--json out]
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import sys
from pathlib import Path

SPELLING = {
    "expand_needs_a_subject", "unknown_expand", "domain_not_for_subject", "invalid_arguments",
    "invalid_params", "unknown_method", "unknown_name", "unknown_operand", "unknown_portfolio",
    "unknown_run", "unknown_row", "unknown_series", "unknown_formula", "unknown_metric",
    "unknown_kind", "unknown_window", "unknown_span", "unknown_unit", "op_or_method",
    "query_or_item", "operands", "params", "subject_required", "not_a_series", "series_only",
    "not_a_book", "not_a_quantity", "not_a_scenario", "unsupported_op", "unsupported_direction",
    "untyped_operand", "untyped_series", "undated_operand", "not_on_this_face", "too_few_operands",
    "unrankable_operand", "invalid_as_of_date", "invalid_date", "invalid_window", "unknown_job",
    "unknown_company", "unknown_tool",
}
GATE = {
    "unsourced_figure", "malformed_answer", "unverified_quote", "not_on_ledger", "id_in_prose",
    "name_in_prose", "pointer_written_as_text", "pointer_not_separated", "kind_does_not_fit",
    "unknown_point", "not_standalone", "missing_citations", "unverified_numbers", "not_on_table",
    "unresolved_slots", "invalid_citations", "unsupported_assertion",
}
ALGEBRA = {
    "different_instants", "overlapping_intervals", "mismatched_windows", "overlapping_quantities",
    "incompatible_units", "incompatible_bases", "inconsistent_units", "incomparable_units",
    "mixed_basis_operand", "undefined_product", "undefined_quotient", "different_books",
    "mixed_worlds", "incomparable_quantities", "unnamed_quantity", "division_by_zero",
    "misaligned_series", "not_alone", "duplicate_operand", "indistinguishable_operands",
    "insufficient_history", "degenerate_regressor", "self_regression", "series_in_set",
    "not_combinable", "undeclarable_unit", "bad_sale", "bad_buy", "bad_fraction", "bad_weight",
    "duplicate_sale", "duplicate_buy", "already_held", "empty_book", "unpriced_holding",
    "run_not_reconcilable", "limits_incomplete",
}
DATA = {
    "metric_not_filed", "not_reported", "not_reported_at_this_date", "no_price_data",
    "no_price_history", "not_prepared", "company_not_found", "section_not_found", "not_indexed",
    "no_brief", "no_completed_run", "run_not_completed", "input_unavailable",
    "series_not_derivable", "not_applicable", "empty_series", "no_positions", "no_limits",
    "no_sector", "no_balance_sheet_data", "not_held", "not_listed", "not_investigable",
    "not_an_sec_filer", "active_run_exists", "not_your_portfolio",
}
SYSTEM = {"tool_error", "fact_adapter_error", "tool_transport_error", "budget_exceeded",
          "quota_exceeded", "provider_unavailable", "sign_in_required", "no_research_run"}

_ERR = re.compile(r"^error: ([a-z_]+)")
_ARTIFACT = re.compile(r"(?:%|\d)=-?\d[\d.,]*|\b\d[\d.,]*%?, \d[\d.,]*%?\b")   # "16.1%=0.161", "16.1%, 16.1%"
_MARK = re.compile(r"\[10-[KQ][^\]]*\]")


def classify(summary: str, status: str) -> str | None:
    s = summary or ""
    if s.startswith("not attempted"):
        return "held"
    if s.startswith("invalid arguments"):
        return "spelling"
    m = _ERR.match(s)
    if not m:
        return "error" if status == "error" else None
    code = m.group(1)
    for name, members in (("spelling", SPELLING), ("gate", GATE), ("algebra", ALGEBRA),
                          ("data", DATA), ("system", SYSTEM)):
        if code in members:
            return name
    return f"other:{code}"


def tally(paths: list[str]) -> dict:
    c: collections.Counter = collections.Counter()
    turns_with: dict[str, set] = collections.defaultdict(set)
    rt, calls, resp, elapsed, ptok, figs = [], [], [], [], [], []
    artifacts = marks = zero = exhausted = 0
    n = 0
    for p in paths:
        for conv in json.loads(Path(p).read_text()):
            for t in conv.get("turns", []):
                n += 1
                tid = f"{conv.get('tag')}#{t.get('turn')}#{p}"
                steps = t.get("steps", [])
                llm = [s for s in steps if s.get("step_type") == "llm_call"]
                rt.append(len(llm)); ptok.append(sum((s.get("prompt_tokens") or 0) for s in llm))
                calls.append(sum(1 for s in steps if s.get("step_type") in ("tool_call", "delegation")))
                resp.append(sum(1 for s in steps if s.get("tool_name") == "respond"))
                elapsed.append(t.get("elapsed_s") or 0)
                meta = t.get("meta") or {}
                figs.append((meta.get("verified") or {}).get("figures") or 0)
                if meta.get("gate") == "exhausted":
                    exhausted += 1
                a = str(t.get("answer") or "")
                if not a:
                    zero += 1
                if _ARTIFACT.search(a):
                    artifacts += 1
                if _MARK.search(a):
                    marks += 1
                for s in steps:
                    if s.get("step_type") not in ("tool_call", "delegation", "respond"):
                        continue
                    k = classify(s.get("result") or "", s.get("status") or "")
                    if k:
                        c[k] += 1
                        turns_with[k].add(tid)
    med = lambda xs: statistics.median(xs) if xs else 0
    q = lambda xs, pp: sorted(xs)[int(pp * (len(xs) - 1))] if xs else 0
    out = {
        "turns": n, "no_answer": zero, "gate_exhausted": exhausted,
        "round_trips_median": med(rt), "round_trips_p90": q(rt, .9),
        "tool_calls_median": med(calls), "tool_calls_p90": q(calls, .9),
        "respond_attempts_mean": round(statistics.mean(resp), 2) if resp else 0,
        "prompt_tokens_median": med(ptok), "prompt_tokens_p90": q(ptok, .9),
        "elapsed_s_median": med(elapsed), "elapsed_s_p90": q(elapsed, .9),
        "figures_median": med(figs),
        "answers_with_double_figure_artifact": artifacts,
        "answers_with_passage_mark_as_figure": marks,
        "refusals": {k: {"count": v, "turns": len(turns_with[k]),
                         "per_turn": round(v / n, 2) if n else 0} for k, v in sorted(c.items())},
    }
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="+")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    out = tally(args.traces)
    for k, v in out.items():
        if k != "refusals":
            print(f"{k:40s} {v}")
    print("refusals by class (count / turns / per turn):")
    for k, v in out["refusals"].items():
        print(f"  {k:28s} {v['count']:5d} {v['turns']:5d} {v['per_turn']:6.2f}")
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
