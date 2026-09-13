"""The analyst's one tool (V33): a decision-level evidence request.

Not a program and not a spelling: subjects, the desk's names for what is
wanted (from the briefing), a window, a comparison, and words for the rest.
Values are names the analyst has just read; the evidence broker does the
routing, the typing and the executing.
"""

from __future__ import annotations

import json

TOOL_NAME = "request_evidence"

REQUEST_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Ask the desk for evidence. Each item names subjects (tickers, port_… or run_… ids from the briefing) "
            "and what you want about them, in the desk's names: methods (net_margin, roic, price.beta, book.reconcile), "
            "filed lines (revenue, operating_cash_flow), run tables (issuer_exposures.weight, limit_checks.current_value, "
            "sector_exposures.weight), 'book' for the standard book read, 'filings:<query>' or 'filings:item 7' for filing text, "
            "'news:<query>' for the web, 'prepare' to put an issuer on the desk, 'scenario:sell <T> <fraction>' / "
            "'scenario:buy <T> <weight>' for a hypothetical book. A window says over what: 12m, last 8 quarters, "
            "last 5 years, at 2025-06-30, 1y, 30d, vs prev run, vs SPY. A comparison says how: rank, change, versus, "
            "share_of:<name>, filter:>0.08. `derive` asks the desk to work a figure out from the ones you named — "
            "'limit_checks.warning_level - limit_checks.current_value' is the room to warning, "
            "'issuer_exposures.market_value / price.adv' is days to liquidate — one line each, + - * / over the "
            "names in `want` or a number. Put anything the fields cannot say in `ask`. The desk returns every figure "
            "with its id and identity, passages to quote, and what it could not do."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array", "minItems": 1, "maxItems": 12,
                    "items": {
                        "type": "object",
                        "properties": {
                            "subjects": {"type": "array", "minItems": 1, "items": {"type": "string"},
                                         "description": "tickers, port_… or run_… ids"},
                            "want": {"type": "array", "minItems": 1, "items": {"type": "string"},
                                     "description": "names from the briefing, or filings:/news:/prepare/book/scenario:"},
                            "window": {"type": ["string", "null"], "description": "12m | last 8 quarters | last 5 years | at YYYY-MM-DD | 1y | 30d | vs prev run | vs SPY"},
                            "compare": {"type": ["string", "null"], "description": "rank | rank lowest | change | versus | share_of:<name> | filter:<op><level>"},
                            "derive": {"type": ["array", "null"], "items": {"type": "string"},
                                       "description": "figures to work out from the ones named, one line each: '<name> <+-*/> <name|number>'"},
                            "ask": {"type": ["string", "null"], "description": "what the fields cannot say, in words"},
                        },
                        "required": ["subjects", "want"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
}


def parse(args: dict) -> list[dict]:
    """The items of a request, each normalised; raises ValueError on a shape the
    schema would not have let through (a provider that ignores schemas)."""
    if not isinstance(args, dict) or not isinstance(args.get("items"), list) or not args["items"]:
        raise ValueError("request_evidence takes {items: [{subjects, want, window?, compare?, derive?, ask?}]}")
    out = []
    for i, it in enumerate(args["items"]):
        if not isinstance(it, dict):
            raise ValueError(f"items[{i}] is not an object")
        subjects = it.get("subjects")
        want = it.get("want")
        if isinstance(subjects, str):
            subjects = [subjects]
        if isinstance(want, str):
            want = [want]
        if not isinstance(subjects, list) or not subjects or not all(isinstance(s, str) for s in subjects):
            raise ValueError(f"items[{i}].subjects is a non-empty list of names")
        if not isinstance(want, list) or not want or not all(isinstance(w, str) for w in want):
            raise ValueError(f"items[{i}].want is a non-empty list of names")
        derive = it.get("derive")
        if isinstance(derive, str):
            derive = [derive]
        if derive is not None and (not isinstance(derive, list) or not all(isinstance(d, str) for d in derive)):
            raise ValueError(f"items[{i}].derive is a list of '<name> <+-*/> <name|number>' lines")
        out.append({"subjects": [s.strip() for s in subjects if s.strip()], "want": [w.strip() for w in want if w.strip()],
                    "window": (it.get("window") or None), "compare": (it.get("compare") or None),
                    "derive": [d.strip() for d in (derive or []) if d.strip()] or None,
                    "ask": (it.get("ask") or None)})
    return out


def dumps(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False)
