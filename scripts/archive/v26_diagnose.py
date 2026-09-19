#!/usr/bin/env python3
"""V26 diagnostics over a conversation-battery trace — the layer report.

The rubric scores the ANSWER. This scores the TURN's mechanics, per layer, so a
regression can be attributed rather than argued about:

  agent/LLM   round trips per turn (llm_call count) and tool calls
  tool        which tools, which methods, which describe levels
  skill       did the turn ever OPEN a domain (expand=procedures)? did it call
              the methods its domain names as evidence? ("knowing-doing gap")
  service     every compute refusal, by error code, with the args that caused it
  validation  respond refusals, by reason
  user report absence sentences in the answer that the desk could have answered

Read-only: it reads a trace JSON and prints. It changes nothing.

    python scripts/v26_diagnose.py docs/spikes/v26/REGRESSION_V21.json
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exposure_workbench.analytics import skill  # noqa: E402

# The methods each domain's evidence sentences point at. Written here, not in
# the registry: this is the TEST's reading of the domain, and the whole question
# is whether the model reads it the same way.
DOMAIN_METHODS: dict[str, set[str]] = {
    "issuer_earnings_quality": {"accruals_ratio", "accruals", "days_sales_outstanding", "days_inventory",
                                "days_payable", "cash_conversion_cycle", "free_cash_flow"},
    "issuer_profitability": {"gross_margin", "operating_margin", "net_margin", "roe", "roa", "roic",
                             "asset_turnover", "equity_multiplier", "issuer.panel"},
    "issuer_credit_and_balance_sheet": {"total_debt", "net_debt", "debt_to_ebitda", "net_debt_to_ebitda",
                                        "debt_to_operating_cash_flow", "fcf_to_debt", "ebit_interest_coverage",
                                        "current_ratio", "quick_ratio"},
    "issuer_capital_allocation": {"free_cash_flow", "fcf_margin", "capex_intensity"},
    "issuer_business_risk_from_filings": set(),          # read_filings, not a method
    "issuer_price_context": {"price.distance_from_52w_high", "price.momentum_12_1", "price.volatility",
                             "price.window_return", "price.drawdown"},
    "issuer_outlook_boundary": set(),
    "book_composition": set(),                            # read_book + rank/add
    "book_limits_and_triggers": {"book.analysis"},
    "book_hypothetical_trades": {"book.sell", "book.buy"},
    "book_market_risk": {"book.analysis", "price.beta", "price.volatility"},
    "book_drawdown_and_attribution": {"book.drawdown_episodes", "book.explain_episode", "book.reconcile"},
    "book_liquidity": {"price.adv"},
    "book_events": {"price.window_return"},
}

# Sentences that CLAIM the desk lacks something. If the thing is in the registry,
# the claim is false and that is the most expensive error the desk can make.
_ABSENCE = re.compile(
    r"(does not hold|do not hold|not held|cannot|can't|is absent|no .{0,20}figure|"
    r"not available|does not have|doesn't have|no method)", re.I)

# What the desk DOES have, as words a false-absence sentence would use.
_HAS = {
    "adv": "price.adv", "daily volume": "price.adv", "average daily volume": "price.adv",
    "momentum": "price.momentum_12_1", "52-week": "price.distance_from_52w_high",
    "52 week": "price.distance_from_52w_high", "beta": "price.beta",
    "volatility": "price.volatility", "drawdown": "price.drawdown",
    "accruals": "accruals_ratio", "days inventory": "days_inventory",
    "days sales": "days_sales_outstanding", "cash conversion cycle": "cash_conversion_cycle",
    "interest coverage": "ebit_interest_coverage", "free cash flow": "free_cash_flow",
    "net debt": "net_debt", "roic": "roic", "gross margin": "gross_margin",
}


def _args(step: dict) -> dict:
    a = step.get("args")
    if isinstance(a, dict):
        return a
    try:
        return json.loads(a) if a else {}
    except Exception:
        return {}


def _turn_report(tag: str, t: dict) -> dict:
    steps = t.get("steps") or []
    llm = [s for s in steps if s["step_type"] == "llm_call"]
    calls = [s for s in steps if s["step_type"] == "tool_call"]
    responds = [s for s in steps if s["step_type"] == "respond"]
    gate_refusals = [s for s in responds if "error" in str(s.get("result") or "")]

    methods, ops, describes, tools = [], [], [], collections.Counter()
    compute_errors, tool_errors = [], []
    for s in calls:
        tools[s["tool_name"]] += 1
        a = _args(s)
        res = str(s.get("result") or "")
        if s["tool_name"] == "compute":
            m = a.get("method")
            for mm in ([m] if isinstance(m, str) else list(m or [])):
                methods.append(mm)
            if a.get("op"):
                ops.append(a["op"])
            if res.startswith("error:"):
                compute_errors.append({"error": res.split("error:")[1].strip()[:40],
                                       "args": json.dumps(a)[:180]})
        elif s["tool_name"] == "describe":
            describes.append(a.get("expand") or "level1")
        if res.startswith("error:") and s["tool_name"] != "compute":
            tool_errors.append({"tool": s["tool_name"], "error": res.split("error:")[1].strip()[:40],
                                "args": json.dumps(a)[:160]})

    answer = t.get("answer") or ""
    false_absence = []
    for sentence in re.split(r"(?<=[.;])\s+", answer):
        if not _ABSENCE.search(sentence):
            continue
        for word, method in _HAS.items():
            if word in sentence.lower():
                false_absence.append({"claims_absent": method, "sentence": sentence.strip()[:220]})
                break

    return {
        "tag": tag, "elapsed_s": t.get("elapsed_s"), "error": t.get("error"),
        "llm_calls": len(llm), "tool_calls": len(calls),
        "respond_attempts": len(responds), "gate_refusals": len(gate_refusals),
        "gate_reasons": [str(s.get("result"))[:60] for s in gate_refusals],
        "tools": dict(tools), "methods": methods, "ops": ops,
        "describe_levels": describes,
        "opened_a_domain": any(d == "procedures" for d in describes),
        "compute_errors": compute_errors, "tool_errors": tool_errors,
        "false_absence": false_absence,
        "prompt_tokens_max": max([s.get("prompt_tokens") or 0 for s in llm], default=0),
        "prompt_tokens_sum": sum(s.get("prompt_tokens") or 0 for s in llm),
        "answered": bool(answer) and not t.get("error"),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="+")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    reports = []
    for path in args.traces:
        for c in json.load(open(path)):
            for t in c.get("turns", []):
                reports.append(_turn_report(f"{c['tag']}#t{t.get('turn')}", t))

    n = len(reports)
    answered = sum(1 for r in reports if r["answered"])
    print(f"=== {n} turns, {answered} answered, {n - answered} failed outright\n")

    def med(key):
        xs = sorted(r[key] for r in reports)
        return xs[len(xs) // 2] if xs else 0

    print("--- agent/LLM layer: round trips")
    print(f"  llm calls per turn   median {med('llm_calls')}  max {max(r['llm_calls'] for r in reports)}")
    print(f"  tool calls per turn  median {med('tool_calls')}  max {max(r['tool_calls'] for r in reports)}")
    print(f"  prompt tokens (max in a turn) median {med('prompt_tokens_max')}")
    print(f"  summed prompt tokens/turn     median {med('prompt_tokens_sum')}")

    print("\n--- tool layer: what was called")
    tools = collections.Counter()
    for r in reports:
        tools.update(r["tools"])
    print("  " + ", ".join(f"{k}={v}" for k, v in tools.most_common()))
    lvl = collections.Counter(d for r in reports for d in r["describe_levels"])
    print(f"  describe levels: {dict(lvl)}")

    print("\n--- skill layer: did the knowledge reach the decision?")
    opened = sum(1 for r in reports if r["opened_a_domain"])
    print(f"  turns that OPENED a domain (expand=procedures): {opened}/{n}")
    ms = collections.Counter(m for r in reports for m in r["methods"])
    print(f"  methods actually called ({len(ms)} distinct): {dict(ms.most_common(14))}")
    never = sorted(set(skill.METHODS) - set(ms))
    print(f"  registry methods NEVER called this run: {len(never)}/{len(skill.METHODS)}")
    print(f"    {', '.join(never)}")
    fa = [f for r in reports for f in r["false_absence"]]
    print(f"\n  FALSE ABSENCE claims (the desk holds it and the answer said it does not): {len(fa)}")
    for f in fa:
        print(f"    [{f['claims_absent']}] {f['sentence']}")

    print("\n--- service layer: compute refusals")
    ce = collections.Counter(e["error"] for r in reports for e in r["compute_errors"])
    print(f"  {sum(ce.values())} refusals: {dict(ce)}")
    for r in reports:
        for e in r["compute_errors"]:
            print(f"    {r['tag']:34} {e['error']:26} {e['args']}")

    print("\n--- other tool refusals")
    te = collections.Counter(f"{e['tool']}:{e['error']}" for r in reports for e in r["tool_errors"])
    print(f"  {sum(te.values())}: {dict(te)}")
    for r in reports:
        for e in r["tool_errors"]:
            print(f"    {r['tag']:34} {e['tool']:18} {e['error']:26} {e['args'][:100]}")

    print("\n--- validation layer: gate")
    tot_resp = sum(r["respond_attempts"] for r in reports)
    tot_ref = sum(r["gate_refusals"] for r in reports)
    print(f"  {tot_resp} respond attempts, {tot_ref} refused ({tot_ref / max(tot_resp, 1):.0%})")
    reasons = collections.Counter()
    for r in reports:
        for g in r["gate_reasons"]:
            m = re.search(r"error:?\s*'?([a-z_]+)", g)
            reasons[m.group(1) if m else g[:30]] += 1
    print(f"  by reason: {dict(reasons.most_common())}")

    print("\n--- worst turns by round trips")
    for r in sorted(reports, key=lambda x: -x["llm_calls"])[:8]:
        print(f"  {r['tag']:34} llm={r['llm_calls']:2} tools={r['tool_calls']:2} "
              f"gate_refusals={r['gate_refusals']} {r['elapsed_s']}s")

    if args.out:
        json.dump(reports, open(args.out, "w"), indent=1)
        print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
