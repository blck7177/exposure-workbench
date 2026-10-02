"""Would the desk accept this call? — answered offline, from the repo's own schemas and rules.

`check_call(tool, args)` returns the problems the tool layer would raise BEFORE any data is read:
  1. the tool's JSON schema (tools/arg_validation.validate_args — the same function registry.invoke runs)
  2. the exclusive-shape rule (registry.Shapes)
  3. the shape rules each verb applies in code before it touches the database
     (tools/primitives._filings_read / _metric_for / _formula_params / _calc / _constant_source,
      services/compute_service._op, compute's per-method params schema)
Rules that need data (does the issuer file this line? is the name on the desk?) are NOT checked here.

Whether a filed line is a flow or a balance is decided at run time from the facts; the set below is an
accounting classification of the 49 lines, used only to apply the "a flow is not read `at` a date" and
"last_n" rules offline.
"""
from __future__ import annotations

import json

from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import registry as desk
from exposure_workbench.analytics import resources
from exposure_workbench.tools import faces, primitives
from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.registries import build_meta_registry

REGISTRY = build_meta_registry()
SERVED = set(faces.FACE_META_AGENT)

BALANCE_LINES = {
    "cash_and_equivalents", "cash_and_restricted_cash", "long_term_debt_total", "long_term_debt_noncurrent",
    "current_portion_long_term_debt", "debt_current_total", "short_term_borrowings",
    "long_term_debt_and_leases_noncurrent", "current_portion_long_term_debt_and_leases", "total_assets",
    "total_liabilities", "stockholders_equity", "stockholders_equity_including_noncontrolling",
    "noncontrolling_interest", "accounts_receivable", "inventory", "accounts_payable", "commercial_paper",
    "operating_lease_liability_total", "operating_lease_liability_current", "operating_lease_liability_noncurrent",
    "current_assets", "current_liabilities", "shares_outstanding",
}
COLUMNS = {r.table: {c.name for c in r.columns} for r in resources.RUN_CHILDREN}
BOOK_PREFIX = ("port_", "run_", "calc_")


def _period_kind(period) -> tuple[str, bool]:
    """(kind, latest?) of a typed period as tools/periods.resolve reads it."""
    if period is None:
        return "latest", True
    key = next((k for k in period if k != "end"), None)
    value = period.get("end") if key == "months" else period.get(key)
    return str(key), value == "latest"


def _calc(args: dict) -> list[str]:
    op, inputs = args.get("op"), args.get("inputs") or []
    by, factor, level, source = args.get("by"), args.get("factor"), args.get("level"), args.get("source")
    out: list[str] = []
    typed = (op == "scale" and factor is not None) or (
        op == "filter" and level is not None and not (isinstance(level, str) and level.startswith("f_")))
    if typed and source not in primitives.CONSTANT_SOURCES:
        out.append("a typed-in factor/level needs source = user_assumption | method_constant")
    if op == "filter":
        if args.get("cmp") is None or level is None:
            out.append("filter takes cmp and level")
        return out
    if op == "scale":
        if len(inputs) != 1 or not isinstance(factor, (int, float)):
            out.append("scale takes ONE input and `factor`")
    elif op in ("add", "subtract", "multiply", "divide"):
        if by is not None:
            if not inputs:
                out.append(f"{op} with `by` takes one or more inputs")
        elif op in ("add", "multiply"):
            if len(inputs) < 2:
                out.append(f"{op} takes two or more inputs")
        elif len(inputs) != 2:
            out.append(f"{op} takes exactly two inputs (or a list with `by`)")
    elif op in ("rank", "top"):
        if len(inputs) < 2:
            out.append("rank takes two or more inputs")
        if op == "top" and not isinstance(args.get("n"), int):
            out.append("top takes n")
    elif op in ("yoy", "qoq", "pct", "cagr", "latest"):
        if len(inputs) != 1:
            out.append(f"{op} is over ONE series")
    elif op in ("sum", "avg", "min", "max", "std", "abs"):
        if not inputs:
            out.append(f"{op} takes one series, or two or more figures")
    return out


def _filings_read(args: dict) -> list[str]:
    out: list[str] = []
    ticker, line, last_n = args.get("ticker"), args.get("line"), args.get("last_n")
    kind, latest = _period_kind(args.get("period"))
    if isinstance(ticker, list) and line is None and len(ticker) > 1:
        out.append("several issuers are read on ONE line: name the `line`")
    if line is None:
        return out
    if line in BALANCE_LINES:
        if last_n is not None and not (kind in ("at", "latest") and latest):
            out.append("a balance's series is its last N filed dates: {\"at\": \"latest\"} or no period")
    else:
        if kind == "at":
            out.append(f"{line} is a flow: it is read over a window, not at a date")
        if last_n is not None and not (kind in ("fy", "quarter") and latest):
            out.append("a series runs on fiscal years or quarters ending at the latest: "
                       "{\"fy\": \"latest\"} or {\"quarter\": \"latest\"}")
    return out


def _metric(args: dict) -> list[str]:
    out: list[str] = []
    name, subject = args.get("name"), args.get("subject")
    params, period, last_n = args.get("params"), args.get("period"), args.get("last_n")
    spec = desk.METHODS.get(name)
    if spec is None:
        return out                                   # the enum already said so
    subjects = [subject] if isinstance(subject, str) else list(subject or [])
    if spec.executor in desk.PERIOD_EXECUTORS:
        if params:
            out.append(f"{name} takes `period` and `last_n`, and no params")
        kind, latest = _period_kind(period)
        basis = fm.FORMULAS[name].basis if name in fm.FORMULAS else "mixed"
        if kind == "at" and basis != "instant":
            out.append(f"{name} is measured over a window, not at a date")
        if last_n is not None and not (kind in ("fy", "quarter") and latest):
            out.append("a measure's series runs on fiscal years or quarters ending at the latest")
        if any(isinstance(s, str) and s.startswith(BOOK_PREFIX) for s in subjects):
            out.append(f"{name} is an issuer measure: its subject is a ticker")
        return out
    if period is not None or last_n is not None:
        out.append(f"{name} is measured over its own window and takes no period (it takes params)")
    out += [f"params.{p['field']}: {p['problem']}" for p in validate_args(spec.params_schema, params or {})]
    books = [s for s in subjects if isinstance(s, str) and s.startswith(BOOK_PREFIX)]
    if spec.subject_kind == "price" and books:
        out.append(f"{name} is measured on one name's prices, and {books[0]} is a book")
    if spec.subject_kind in ("run", "portfolio") and any(not (isinstance(s, str) and s.startswith(BOOK_PREFIX)) for s in subjects):
        out.append(f"{name} is a book measure: its subject is a port_/run_ id")
    return out


def check_call(tool: str, args) -> list[str]:
    if tool not in REGISTRY.tools or tool not in SERVED:
        return [f"unknown tool {tool!r}"]
    spec = REGISTRY.tools[tool]
    if not isinstance(args, dict):
        return ["arguments are not an object"]
    out = [f"{p['field'] or 'args'}: {p['problem']}" for p in validate_args(spec.json_schema, args)]
    if spec.shapes is not None and len([f for f in spec.shapes.fields if args.get(f) is not None]) > 1:
        out.append(spec.shapes.detail)
    if out:
        return out                                  # refused at the schema: the verb's own rules never ran
    if tool == "list":
        what, subject = args.get("what"), args.get("subject")
        if what in ("fundamentals", "filings", "prices") and not subject:
            out.append(f"list(what='{what}') is about one name: give its ticker as `subject`")
        if what == "checks" and not str(subject or "").startswith("port_"):
            out.append("checks are a portfolio's: give its port_… id")
    elif tool == "filings_read":
        out += _filings_read(args)
    elif tool == "metric":
        out += _metric(args)
    elif tool == "calc":
        out += _calc(args)
    elif tool == "book_read":
        table, column = args.get("table"), args.get("column")
        if column is not None and table in COLUMNS and column not in COLUMNS[table]:
            out.append(f"{table} has no column {column!r}: {sorted(COLUMNS[table])}")
        if not str(args.get("book") or "").startswith(BOOK_PREFIX):
            out.append("a book is a port_/run_/calc_ id")
    elif tool == "scenario":
        if not str(args.get("book") or "").startswith(BOOK_PREFIX):
            out.append("a book is a port_/run_/calc_ id")
    return out


def check_plan(steps: list[dict]) -> list[dict]:
    """[{tool, args, problems}] for a plan whose steps are {tool, args | args_json}."""
    out = []
    for s in steps:
        args = s.get("args")
        if args is None:
            try:
                args = json.loads(s.get("args_json") or "{}")
            except json.JSONDecodeError as exc:
                out.append({"tool": s.get("tool"), "args": s.get("args_json"), "problems": [f"args are not JSON: {exc}"]})
                continue
        out.append({"tool": s.get("tool"), "args": args, "problems": check_call(s.get("tool"), args)})
    return out
