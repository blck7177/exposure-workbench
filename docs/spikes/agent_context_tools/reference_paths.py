"""One reference path per question through the eleven verbs, checked offline against the desk's own
schemas and shape rules (validate_plans.check_call). Row ids that only exist after a call are written
as placeholders (f_…): the schema asks for strings, which is all that can be checked without data.
`n` on a step means "this call is made n times, once per name" (the verb has no vector form)."""
from __future__ import annotations

import json
from pathlib import Path

from validate_plans import check_call

W = "reference path"
TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "JPM", "XOM", "LLY", "TLT", "HYG"]
ids = lambda tag, names=TICKERS: [f"f_{tag}_{n.lower()}" for n in names]   # noqa: E731

PATHS: dict[str, list[dict]] = {
    "Q01": [
        {"tool": "book_read", "args": {"book": "port_001", "table": "issuer_exposures", "column": "weight", "why": W}},
        {"tool": "calc", "args": {"op": "top", "inputs": ids("w"), "direction": "highest", "n": 1, "why": W}},
        {"tool": "book_read", "args": {"book": "port_001", "table": "sector_exposures", "column": "weight", "why": W}},
    ],
    "Q02": [
        {"tool": "metric", "args": {"name": "book.reconcile", "subject": "port_001", "why": W}},
        {"tool": "book_read", "args": {"book": "port_001", "table": "exposure_metrics", "column": "daily_return", "why": W}},
        {"tool": "book_read", "args": {"book": "port_001", "table": "issuer_exposures", "column": "contribution", "why": W}},
        {"tool": "book_read", "args": {"book": "port_001", "table": "factor_attributions", "column": "contribution", "why": W}},
        {"tool": "calc", "args": {"op": "rank", "inputs": ids("contrib"), "direction": "lowest", "why": W}},
    ],
    "Q03": [
        {"tool": "metric", "args": {"name": "book.analysis", "subject": "port_001", "why": W}},
        {"tool": "calc", "args": {"op": "rank", "inputs": ["f_room_breach_a", "f_room_breach_b", "f_room_breach_c"],
                                  "direction": "lowest", "why": W}},
    ],
    "Q04": [
        {"tool": "filings_read", "args": {"ticker": ["MSFT", "AAPL", "GOOGL"], "line": "net_income",
                                          "period": {"fy": 2025}, "why": W}},
    ],
    "Q05": [
        {"tool": "filings_read", "args": {"ticker": "AAPL", "why": W}},                       # every balance at the latest date
        {"tool": "calc", "args": {"op": "add", "inputs": ["f_ltd_noncurrent", "f_current_portion", "f_commercial_paper"], "why": W}},
        {"tool": "calc", "args": {"op": "subtract", "inputs": ["f_debt_sum", "f_cash"], "why": W}},
        {"tool": "metric", "args": {"name": "net_debt", "subject": "AAPL", "why": W}},        # the desk's own composition, to set beside it
    ],
    "Q06": [
        {"tool": "filings_read", "args": {"ticker": "NVDA", "line": "total_revenues", "period": {"quarter": "latest"},
                                          "last_n": 5, "why": W}},
        {"tool": "calc", "args": {"op": "qoq", "inputs": ["f_nvda_rev_series"], "why": W}},
    ],
    "Q07": [
        {"tool": "web_search", "args": {"ticker": "LLY", "query": "latest news this week", "days": 7, "why": W}},
    ],
    "Q08": [
        {"tool": "book_read", "args": {"book": "port_001", "table": "issuer_exposures", "column": "weight", "why": W}},
        {"tool": "calc", "args": {"op": "top", "inputs": ids("w"), "direction": "highest", "n": 1, "why": W}},
        {"tool": "scenario", "args": {"book": "port_001", "trades": [{"sell": "JPM", "fraction": 0.5}], "why": W}},
        {"tool": "book_read", "args": {"book": "calc_after000001", "table": "limit_checks", "why": W}},
        {"tool": "book_read", "args": {"book": "port_001", "table": "limit_checks", "why": W}},
        {"tool": "book_read", "args": {"book": "calc_after000001", "table": "issuer_exposures", "column": "weight", "why": W}},
    ],
    "Q09": [
        {"tool": "book_read", "args": {"book": "port_001", "table": "issuer_exposures", "column": "market_value", "why": W}},
        {"tool": "metric", "args": {"name": "price.adv", "subject": TICKERS, "params": {"window_days": 20}, "why": W}},
        {"tool": "calc", "n": 10, "args": {"op": "scale", "inputs": ["f_adv_dollars_x"], "factor": 0.2,
                                          "source": "user_assumption", "why": W}},
        {"tool": "calc", "n": 10, "args": {"op": "divide", "inputs": ["f_mv_x", "f_adv_scaled_x"], "why": W}},
        {"tool": "calc", "args": {"op": "rank", "inputs": ids("days"), "direction": "highest", "why": W}},
    ],
    "Q10": [
        {"tool": "metric", "args": {"name": "price.volatility", "subject": ["MSFT", "SPY"], "params": {"window_days": 30}, "why": W}},
        {"tool": "metric", "args": {"name": "price.volatility", "subject": ["MSFT", "SPY"], "params": {"window_days": 252}, "why": W}},
        {"tool": "calc", "args": {"op": "divide", "inputs": ["f_msft_vol30", "f_msft_vol252"], "why": W}},
        {"tool": "calc", "args": {"op": "divide", "inputs": ["f_spy_vol30", "f_spy_vol252"], "why": W}},
    ],
    "Q11": [
        {"tool": "metric", "args": {"name": "equity_multiplier", "subject": "JPM", "period": {"quarter": "latest"},
                                    "last_n": 5, "why": W}},
        {"tool": "calc", "args": {"op": "yoy", "inputs": ["f_jpm_em_series"], "why": W}},
    ],
    "Q12": [
        {"tool": "metric", "args": {"name": "book.drawdown_episodes", "subject": "port_001", "params": {"span": "1y"}, "why": W}},
        {"tool": "book_read", "args": {"book": "port_001", "table": "exposure_metrics", "column": "rolling_vol_30d", "why": W}},
    ],
    "Q13": [
        {"tool": "metric", "args": {"name": "net_margin", "subject": ["TSLA", "AAPL"], "period": {"fy": "latest"}, "why": W}},
        {"tool": "start", "args": {"kind": "readiness", "subject": "TSLA", "why": W}},
    ],
    "Q14": [
        {"tool": "metric", "args": {"name": "price.momentum_12_1", "subject": TICKERS, "why": W}},
        {"tool": "calc", "args": {"op": "top", "inputs": ids("mom"), "direction": "lowest", "n": 1, "why": W}},
        {"tool": "book_read", "args": {"book": "port_001", "table": "issuer_exposures", "row": "XOM", "why": W}},
    ],
}

if __name__ == "__main__":
    questions = {q["qid"]: q["question"] for q in json.loads((Path(__file__).parent / "questions.json").read_text())}
    total_calls = 0
    for qid, steps in PATHS.items():
        calls = sum(s.get("n", 1) for s in steps)
        total_calls += calls
        bad = [(s["tool"], check_call(s["tool"], s["args"])) for s in steps if check_call(s["tool"], s["args"])]
        verbs = " → ".join(s["tool"] + (f"×{s['n']}" if s.get("n") else "") for s in steps)
        print(f"{qid}  {calls:>2} call(s)  {'ok' if not bad else 'REFUSED: ' + json.dumps(bad)}  | {verbs}")
        print(f"      {questions[qid]}")
    print(f"total {total_calls} calls over {len(PATHS)} questions")
