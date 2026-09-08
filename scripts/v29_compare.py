"""V29 — the mechanical counters, 2026-09-07 against 2026-09-08, side by side.

Read-only. The rubric is a distribution and is reported separately (X7); THIS
is the part of the instrument that is countable and reproducible: which door a
name went to, which refusal fired, which method produced a figure. Every counter
here names the finding it measures, so a number that does not move says which
fix did not land.

    python scripts/v29_compare.py --before docs/spikes/v26/NEW_V26.json … \
                                  --after  docs/spikes/v29/V26_R1.json …
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from exposure_workbench.analytics import skill                      # noqa: E402
from exposure_workbench.services import compute_service as cs       # noqa: E402
from exposure_workbench.services import concept_mapping as cm       # noqa: E402

METHODS, DOMAINS = set(skill.METHODS), set(skill.PROCEDURES)
METRICS, OPS = set(cm.SUPPORTED_METRICS), set(cs.OPS)
WATCHED = ("price.beta", "gross_margin", "book.drawdown_episodes", "accruals_ratio",
           "book.explain_episode", "price.adv", "book.analysis", "issuer.panel")


def _turns(paths: list[str]):
    for p in paths:
        for conv in json.loads(Path(p).read_text()):
            for t in conv.get("turns", []):
                yield conv.get("tag", "?"), t


def _calls(turn):
    for st in turn.get("steps", []):
        if st.get("step_type") != "tool_call":
            continue
        try:
            args = json.loads(st.get("args") or "{}")
        except Exception:
            args = {}
        yield st.get("tool_name"), args, (st.get("result") or ""), st.get("status")


def tally(paths: list[str]) -> dict:
    c = collections.Counter()
    turns_with = collections.defaultdict(set)
    method_ok, method_fail = collections.Counter(), collections.Counter()
    key = 0
    for tag, t in _turns(paths):
        key += 1
        tid = f"{tag}#{t.get('turn')}#{key}"
        c["turns"] += 1
        if t.get("answer"):
            c["answered"] += 1
        for name, args, res, status in _calls(t):
            c["tool_calls"] += 1
            err = None
            for code in ("unknown_series", "op_or_method", "unknown_method", "metric_not_filed",
                         "fact_adapter_error", "run_not_completed", "invalid_params", "unknown_expand",
                         "expand_needs_a_subject", "domain_not_for_subject", "incomparable_quantities",
                         "unnamed_quantity", "invalid_arguments", "query_or_item", "unknown_portfolio"):
                if code in res:
                    err = code
                    c[f"refusal:{code}"] += 1
                    turns_with[f"refusal:{code}"].add(tid)
                    break
            if name == "describe":
                subj, exp = args.get("subject"), args.get("expand")
                if not subj:
                    c["describe:root"] += 1
                    if exp:
                        c["describe:root_with_expand"] += 1        # 9/7: 114 no-ops
                        turns_with["describe:root_with_expand"].add(tid)
                elif exp in DOMAINS:
                    c["describe:one_domain"] += 1                  # V27 capability
                    turns_with["describe:one_domain"].add(tid)
                elif exp == "procedures":
                    c["describe:all_domains"] += 1
                    turns_with["describe:all_domains"].add(tid)
                elif exp == "filings":
                    c["describe:filings"] += 1
                    if "fact_adapter_error" in res:
                        c["describe:filings_crash"] += 1           # X3
            elif name == "read_book":
                for n in [str(x) for x in (args.get("names") or [])]:
                    if n in METHODS:
                        c["wrong_door:method_to_read_book"] += 1   # Y1: 110 in 38 turns
                        turns_with["wrong_door:method_to_read_book"].add(tid)
                    elif n in DOMAINS:
                        c["wrong_door:domain_to_read_book"] += 1
                        turns_with["wrong_door:domain_to_read_book"].add(tid)
                if '"route"' in res or "'route'" in res:
                    c["routed_refusal"] += 1
            elif name == "read_fundamentals":
                m = args.get("metric")
                if m in METHODS:
                    c["wrong_door:method_to_read_fundamentals"] += 1
                    turns_with["wrong_door:method_to_read_fundamentals"].add(tid)
            elif name == "compute":
                ms = args.get("method")
                ms = [ms] if isinstance(ms, str) else list(ms or [])
                for m in ms:
                    if m in METHODS:
                        (method_fail if err else method_ok)[m] += 1
                    elif m in METRICS:
                        c["wrong_door:metric_to_compute"] += 1
                        turns_with["wrong_door:metric_to_compute"].add(tid)
                    elif m in DOMAINS:
                        c["wrong_door:domain_to_compute"] += 1
                        turns_with["wrong_door:domain_to_compute"].add(tid)
                    elif m in OPS:
                        c["wrong_door:op_to_compute"] += 1
                if args.get("op") and ms:
                    c["shape:op_and_method_written"] += 1
                    turns_with["shape:op_and_method_written"].add(tid)
    c["distinct_methods_succeeded"] = len(method_ok)
    return {"c": c, "turns_with": {k: len(v) for k, v in turns_with.items()},
            "method_ok": method_ok, "method_fail": method_fail}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", nargs="+", required=True)
    ap.add_argument("--after", nargs="+", required=True)
    a = ap.parse_args(argv)
    B, A = tally(a.before), tally(a.after)

    def row(label, k, finding=""):
        b, x = B["c"][k], A["c"][k]
        bt, at = B["turns_with"].get(k, ""), A["turns_with"].get(k, "")
        arrow = "same" if b == x else ("DOWN" if x < b else "UP")
        print(f"  {label:44} {b:>5} ({bt or '-':>3} turns) -> {x:>5} ({at or '-':>3} turns)  {arrow:5} {finding}")

    print(f"=== turns: {B['c']['turns']} -> {A['c']['turns']};  "
          f"answered {B['c']['answered']} -> {A['c']['answered']};  "
          f"tool calls {B['c']['tool_calls']} -> {A['c']['tool_calls']}\n")
    print("--- V27: did the name reach the right door?")
    row("method name -> read_book", "wrong_door:method_to_read_book", "Y1")
    row("domain name -> read_book", "wrong_door:domain_to_read_book", "P2")
    row("method name -> read_fundamentals", "wrong_door:method_to_read_fundamentals", "X13")
    row("filed line -> compute(method=)", "wrong_door:metric_to_compute", "P6")
    row("domain name -> compute(method=)", "wrong_door:domain_to_compute", "P6")
    row("op name -> compute(method=)", "wrong_door:op_to_compute", "")
    row("refusal: unknown_method", "refusal:unknown_method", "")
    row("refusal: metric_not_filed", "refusal:metric_not_filed", "")
    row("refusals that carried a route", "routed_refusal", "V27 new")
    print("\n--- V27: the tree's shape")
    row("describe at the root", "describe:root", "")
    row("  ... with an expand (a no-op before)", "describe:root_with_expand", "114 in 9/7")
    row("refusal: expand_needs_a_subject", "refusal:expand_needs_a_subject", "V27 new")
    row("describe of ONE domain", "describe:one_domain", "V27 new")
    row("describe of ALL domains (procedures)", "describe:all_domains", "3/140 in 9/7")
    row("refusal: domain_not_for_subject", "refusal:domain_not_for_subject", "V27 new")
    print("\n--- V28: the tool's boundaries")
    row("op + method written together", "shape:op_and_method_written", "A2")
    row("refusal: op_or_method (service)", "refusal:op_or_method", "15 in 9/7")
    row("refusal: invalid_arguments (schema)", "refusal:invalid_arguments", "A2 pre-spend")
    row("refusal: unknown_series", "refusal:unknown_series", "A1, 41 in 9/7")
    row("describe(expand='filings')", "describe:filings", "")
    row("  ... that crashed the adapter", "describe:filings_crash", "C2/X3")
    row("refusal: fact_adapter_error", "refusal:fact_adapter_error", "X3")
    row("refusal: run_not_completed", "refusal:run_not_completed", "C1")
    row("refusal: incomparable_quantities", "refusal:incomparable_quantities", "B1")
    print("\n--- the methods that never produced a figure on 2026-09-07")
    print(f"  {'method':30} {'ok before':>9} {'fail before':>11} {'ok after':>9} {'fail after':>11}")
    for m in WATCHED:
        print(f"  {m:30} {B['method_ok'][m]:>9} {B['method_fail'][m]:>11} "
              f"{A['method_ok'][m]:>9} {A['method_fail'][m]:>11}")
    print(f"\n  distinct methods that produced a figure: "
          f"{B['c']['distinct_methods_succeeded']} -> {A['c']['distinct_methods_succeeded']} of {len(METHODS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
