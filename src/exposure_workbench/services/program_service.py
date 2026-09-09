"""program_service (V30) — the analysis is a program; the desk executes it.

WHY THIS EXISTS. Until V30 the model computed one operation per round trip
and joined the steps by copying ids out of tool payloads (`f_…`, `run_…:name`,
`f_…@period`). The review of 2026-09-09 measured what that costs: a median of
seven round trips and 67k prompt tokens a turn, 111 refusal codes most of which
teach spelling, and the ordering / comparison mistakes (X8: the wrong five
summed; X16: one point written twice) that a composition written in one
place cannot make. Here the model writes ONE program — a list of bindings,
each a primitive applied to earlier bindings and literals — and this module
parses it, types every node, runs every node through the algebra the desk
already has, and returns a result table in which every value carries its
identity and rests on a ledger row.

WHAT DOES NOT MOVE. Every refusal of the typed calculator (R1–R3, the units,
the books), of the formula evaluator, of the price service's floors and of the
scenario builder fires here exactly as it did behind `compute`, on the node it
falls on. This module adds two refusals of its own — `unknown_primitive` and
`type_mismatch` — and one rule: **a binding name is a variable, never a
measure.** A derived node's measure is what the calculator derives from its
operation and operands; the model's `$name` is a handle. `as_quantity` is not
in the language (V29 §6.2: "620.9% days" was book value ÷ MSFT value under a
name asserting a division by daily volume that never happened).

THE PROGRAM.

    {"let": [["w",    {"fn": "column", "run": {"fn": "run", "portfolio": "port_001"},
                       "table": "issuer_exposures", "col": "weight"}],
             ["top5", {"fn": "sum", "of": {"fn": "top", "of": "$w", "n": 5}}]],
     "return": ["top5"]}

An argument is a literal (number, string, list, object), `"$name"` for an
earlier binding, or a nested `{"fn": …}` expression (bound under a generated
name). Bindings evaluate in order; a node that refuses becomes an ABSENCE node
and every node that depends on it refuses with the chain named. Nothing is
partial: the table holds every node, settled or refused.

NODE KINDS. scalar (one typed figure), series (one typed series), vector (one
figure per label — a run column, a broadcast, a top-N), ranking (an ordering),
table (a payload holding several named figures: a scenario, a balance sheet,
a book analysis), run (a handle), absence (a refusal).

Imports services and analytics only — never tools. `invoked_by` is a parameter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import series_ops as so
from exposure_workbench.analytics import skill
from exposure_workbench.db.models import ExposureRun, FinancialFact
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import drawdown_service, formula_service, fundamentals_service
from exposure_workbench.services import integration_service, reconcile_service, run_reads_service
from exposure_workbench.services import facts as F
from exposure_workbench.services import price_analytics_service as pas
from exposure_workbench.services import quantities as qn
from exposure_workbench.services import scenario_service, series_service
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.services import company_service

PROGRAM_OP = "program.run"        # the ledger operation one executed program is recorded under

SCALAR = "scalar"; SERIES = "series"; VECTOR = "vector"; RANKING = "ranking"
TABLE = "table"; RUN = "run"; ABSENCE = "absence"
KINDS = (SCALAR, SERIES, VECTOR, RANKING, TABLE, RUN, ABSENCE)

_ID_PREFIXES = ("fact_", "calc_", "run_", "f_")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


# ── nodes ────────────────────────────────────────────────────────────────────

@dataclass
class Node:
    name: str
    kind: str
    expr: Any
    deps: list[str] = field(default_factory=list)
    ref: str | None = None                                   # the ledger id the node rests on
    typed: Any = None                                        # tc.Typed | tc.TypedSeries | None
    entries: list[tuple[str, str, float | None, str | None]] = field(default_factory=list)
    # vector / ranking / table: (label, ref, value, unit_class)
    payload: dict = field(default_factory=dict)
    refusal: dict | None = None
    as_of: str | None = None
    unit: str | None = None
    measure: str | None = None
    facts: list[F.Fact] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.refusal is None


# ── the primitives: name -> (required args, optional args) ───────────────────
# Declared once so the schema handed to the model, the parser and the
# dispatcher cannot disagree about what a primitive takes (test_program pins).
PRIMITIVES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # reads
    "fundamentals": (("ticker",), ("metric", "months", "start", "end", "at", "last_n")),
    "prices":       (("ticker",), ("window",)),
    "price":        (("ticker",), ("as_of",)),
    "run":          (("portfolio",), ("which",)),
    "column":       (("run", "table", "col"), ()),
    "figure":       (("run", "name"), ()),
    "method":       (("name", "subject"), ("params",)),
    # arithmetic
    "add": (("a", "b"), ()), "sub": (("a", "b"), ()), "mul": (("a", "b"), ()), "div": (("a", "b"), ()),
    "scale": (("of", "factor"), ("unit",)),
    # sets
    "sum": (("of",), ()), "avg": (("of",), ()), "min": (("of",), ()), "max": (("of",), ()),
    "std": (("of",), ()), "abs": (("of",), ()),
    "rank": (("of",), ("direction",)), "top": (("of", "n"), ("direction",)),
    # series
    "yoy": (("of",), ()), "qoq": (("of",), ()), "pct": (("of",), ()), "cagr": (("of",), ()),
    "latest": (("of",), ()), "at": (("of", "period"), ()),
    # scenarios
    "sell": (("run", "sales"), ()), "buy": (("run", "buys"), ()),
}
_SET_OPS = ("avg", "min", "max", "std", "abs")
_SERIES_OPS = ("yoy", "qoq", "pct", "cagr", "latest")
_BINARY = {"add": "add", "sub": "subtract", "mul": "multiply", "div": "divide"}


def schema() -> dict:
    """The program's JSON schema, for the tool that takes one. Provider-legal:
    an object at the top level, no oneOf/anyOf/not (V28-R)."""
    return {"type": "object", "properties": {
        "let": {"type": "array", "minItems": 1, "maxItems": 60,
                "description": "bindings in order: [name, expression]; an expression is {fn, …args}, "
                               "'$name' for an earlier binding, or a literal",
                "items": {"type": "array", "minItems": 2, "maxItems": 2,
                          "items": {}}},
        "return": {"type": ["array", "null"], "items": {"type": "string"},
                   "description": "the bindings the answer will point at (default: all)"},
    }, "required": ["let"], "additionalProperties": False}


# ── parsing ──────────────────────────────────────────────────────────────────

@dataclass
class Program:
    bindings: list[tuple[str, Any]]
    returns: list[str]
    source: dict


def parse(program: dict) -> Program | dict:
    if not isinstance(program, dict) or not isinstance(program.get("let"), list) or not program["let"]:
        return _err("malformed_program", "a program is {let: [[name, expression], …], return?: [names]}")
    bindings: list[tuple[str, Any]] = []
    seen: set[str] = set()
    gen = 0

    def hoist(expr: Any, at: str) -> Any:
        """Nested {fn} expressions become their own bindings, so every node has
        a name and the table lists every intermediate."""
        nonlocal gen
        if isinstance(expr, dict) and "fn" in expr:
            args = {k: hoist(v, f"{at}.{k}") for k, v in expr.items() if k != "fn"}
            if expr.get("fn") not in PRIMITIVES:
                return {"fn": expr.get("fn"), **args}       # refused at evaluation, by name
            gen += 1
            name = f"_{at}_{gen}"
            bindings.append((name, {"fn": expr["fn"], **args}))
            seen.add(name)
            return f"${name}"
        if isinstance(expr, list):
            return [hoist(v, at) for v in expr]
        return expr

    for i, item in enumerate(program["let"]):
        if not (isinstance(item, list) and len(item) == 2 and isinstance(item[0], str)):
            return _err("malformed_program", f"let[{i}] is not [name, expression]")
        name, expr = item
        if not _NAME.match(name) or name.startswith("_"):
            return _err("malformed_program", f"let[{i}]: {name!r} is not a binding name (letters, digits, _; not leading _)")
        if name in seen:
            return _err("malformed_program", f"let[{i}]: {name!r} is bound twice")
        if isinstance(expr, dict) and "fn" in expr:
            args = {k: hoist(v, name) for k, v in expr.items() if k != "fn"}
            expr = {"fn": expr["fn"], **args}
        else:
            expr = hoist(expr, name)
        bindings.append((name, expr))
        seen.add(name)
    returns = program.get("return") or [n for n, _ in bindings if not n.startswith("_")]
    unknown = [r for r in returns if r not in seen]
    if unknown:
        return _err("malformed_program", f"return names bindings that do not exist: {unknown}")
    return Program(bindings, list(returns), program)


# ── evaluation ───────────────────────────────────────────────────────────────

class _Ctx:
    def __init__(self, db: AsyncSession, invoked_by: str):
        self.db = db
        self.invoked_by = invoked_by
        self.nodes: dict[str, Node] = {}


def _deref(ctx: _Ctx, v: Any) -> tuple[Any, list[str]]:
    """A literal, or the Node an '$name' points at; the names it depends on."""
    if isinstance(v, str) and v.startswith("$"):
        n = ctx.nodes.get(v[1:])
        if n is None:
            return _err("unknown_binding", f"{v} is not bound earlier in the program"), []
        return n, [n.name]
    if isinstance(v, list):
        out, deps = [], []
        for x in v:
            r, d = _deref(ctx, x)
            out.append(r); deps += d
        return out, deps
    return v, []


def _typed_identity(t) -> tuple[str | None, str | None, str | None, dict | None]:
    """(as_of, unit, measure, window) of a typed value."""
    if isinstance(t, tc.TypedSeries):
        last = t.points[-1][0].isoformat() if t.points else None
        first = t.points[0][0].isoformat() if t.points else None
        return last, t.unit_class.upper(), t.quantity, ({"start": first, "end": last} if first else None)
    if isinstance(t, tc.Typed):
        if t.instant:
            return t.instant.isoformat(), t.unit_class.upper(), t.quantity, None
        if t.interval:
            return t.interval[1].isoformat(), t.unit_class.upper(), t.quantity, {"start": t.interval[0].isoformat(), "end": t.interval[1].isoformat()}
        leaves = (t.recorded_basis or {}).get("leaves") or {}
        ends = list(leaves.get("instants") or []) + [iv[1] for iv in (leaves.get("intervals") or [])]
        return (max(ends) if ends else None), t.unit_class.upper(), t.quantity, None
    return None, None, None, None


async def _scalar_from_ref(ctx: _Ctx, node: Node, ref: str, payload: dict | None = None) -> Node:
    t = await tc._resolve(ctx.db, ref)
    if isinstance(t, dict):
        node.kind, node.refusal = ABSENCE, t
        return node
    node.ref, node.typed, node.payload = ref, t, payload or {}
    node.kind = SERIES if isinstance(t, tc.TypedSeries) else SCALAR
    node.as_of, node.unit, node.measure, _w = _typed_identity(t)
    return node


async def _from_payload(ctx: _Ctx, node: Node, payload: dict) -> Node:
    """Type a service payload: a scalar (value + calc_id), a series (points +
    calc_id), a payload of several figures (each with its calc_id), or a row
    the namer can list (a scenario, an analysis, a run)."""
    if not isinstance(payload, dict):
        node.kind, node.refusal = ABSENCE, _err("tool_error", f"{node.name}: no payload")
        return node
    if payload.get("error"):
        node.kind, node.refusal, node.payload = ABSENCE, payload, payload
        return node
    cid = payload.get("calc_id")
    if isinstance(cid, str) and (_is_num(payload.get("value")) or isinstance(payload.get("points"), list)):
        return await _scalar_from_ref(ctx, node, cid, payload)
    figures = [(k, v["calc_id"]) for k, v in payload.items()
               if isinstance(v, dict) and isinstance(v.get("calc_id"), str) and _is_num(v.get("value"))]
    if figures:
        node.kind, node.payload = TABLE, payload
        node.ref = cid if isinstance(cid, str) else figures[0][1]
        for k, r in figures:
            t = await tc._resolve(ctx.db, r)
            if isinstance(t, dict):
                continue
            node.entries.append((k, r, t.value, t.unit_class.upper()))
        node.as_of = next((payload.get(k) for k in ("as_of", "to", "period_end") if isinstance(payload.get(k), str)), None)
        return node
    if isinstance(cid, str):
        resolved = await qn.of_ref(ctx.db, cid)
        if resolved.quantities:
            node.kind, node.ref, node.payload = TABLE, cid, payload
            node.entries = [(q.label, f"{cid}:{q.label}", q.value, q.unit_class) for q in resolved.quantities if q.not_alone is None]
            node.as_of = (payload.get("as_of") if isinstance(payload.get("as_of"), str) else None)
            return node
        return await _scalar_from_ref(ctx, node, cid, payload)
    node.kind, node.refusal, node.payload = ABSENCE, _err("untyped_result", f"{node.name}: the service returned no ledger row to type"), payload
    return node


# ── primitives ───────────────────────────────────────────────────────────────

async def _metric_is_instant(db: AsyncSession, ticker: str, metric: str) -> bool | None:
    try:
        c = await company_service.get_by_ticker(db, ticker.upper())
    except company_service.CompanyNotFound:
        return None
    row = (await db.execute(select(FinancialFact.period_start).where(
        FinancialFact.company_id == c.id, FinancialFact.normalized_metric == metric).limit(1))).first()
    return None if row is None else row[0] is None


async def _p_fundamentals(ctx: _Ctx, node: Node, ticker: str, metric: str | None = None, months=None,
                          start=None, end=None, at=None, last_n=None) -> Node:
    tk = str(ticker).upper()
    if metric is None:
        sheet = await fundamentals_service.get_balance_sheet(ctx.db, tk, at=at, invoked_by=ctx.invoked_by)
        if sheet.get("error"):
            node.kind, node.refusal, node.payload = ABSENCE, sheet, sheet
            return node
        node.kind, node.payload, node.as_of = TABLE, sheet, sheet.get("as_of")
        for m, b in (sheet.get("balances") or {}).items():
            if isinstance(b, dict) and _is_num(b.get("value")) and isinstance(b.get("fact_id"), str):
                node.entries.append((m, b["fact_id"], float(b["value"]), str(b.get("unit_class") or "MONEY").upper()))
        node.ref = node.entries[0][1] if node.entries else None
        return node
    instant = await _metric_is_instant(ctx.db, tk, metric)
    if instant is None:
        node.kind, node.refusal = ABSENCE, _err("metric_not_filed", f"{tk} has no filed facts under {metric!r}", ticker=tk, metric=metric)
        return node
    if instant:
        if last_n is not None:
            return await _from_payload(ctx, node, await fundamentals_service.get_balance_series(
                ctx.db, tk, metric, last_n=int(last_n), invoked_by=ctx.invoked_by))
        sheet = await fundamentals_service.get_balance_sheet(ctx.db, tk, at=at, invoked_by=ctx.invoked_by)
        if sheet.get("error"):
            node.kind, node.refusal = ABSENCE, sheet
            return node
        b = (sheet.get("balances") or {}).get(metric)
        if not b:
            node.kind, node.refusal = ABSENCE, _err("not_reported_at_this_date", f"{metric} is not reported by {tk} at {sheet.get('as_of')}",
                                                    last_reported=(sheet.get("not_reported_at_this_date") or {}).get(metric))
            return node
        return await _scalar_from_ref(ctx, node, b["fact_id"], {"metric": metric, "as_of": sheet.get("as_of")})
    return await _from_payload(ctx, node, await fundamentals_service.get_flow(
        ctx.db, tk, metric, months=(int(months) if months is not None else None), start=start, end=end,
        last_n=(int(last_n) if last_n is not None else None), invoked_by=ctx.invoked_by))


async def _p_prices(ctx: _Ctx, node: Node, ticker: str, window: str | None = None) -> Node:
    return await _from_payload(ctx, node, await pas.get_price_series(
        ctx.db, str(ticker).upper(), window=window or pas._DEFAULT_WINDOW, invoked_by=ctx.invoked_by))


async def _p_price(ctx: _Ctx, node: Node, ticker: str, as_of: str | None = None) -> Node:
    return await _from_payload(ctx, node, await pas.get_price(ctx.db, str(ticker).upper(), as_of=as_of, invoked_by=ctx.invoked_by))


async def _p_run(ctx: _Ctx, node: Node, portfolio: str, which: str | None = None) -> Node:
    which = which or "latest"
    if which.startswith("run_"):
        run = await run_reads_service.completed_run(ctx.db, which)
    else:
        fresh = await run_reads_service.get_run_freshness(ctx.db, portfolio)
        latest_id = fresh.get("latest_completed_run") if isinstance(fresh, dict) else None
        if not latest_id:
            node.kind, node.refusal = ABSENCE, _err("no_completed_run", f"{portfolio} has no completed run", **({"portfolio": portfolio}))
            return node
        run = await run_reads_service.completed_run(ctx.db, latest_id)
        if which == "prev" and not isinstance(run, dict):
            prev = (await ctx.db.execute(
                select(ExposureRun).where(ExposureRun.portfolio_id == portfolio, ExposureRun.status == "completed",
                                          ExposureRun.as_of_date < run.as_of_date)
                .order_by(ExposureRun.as_of_date.desc(), ExposureRun.created_at.desc()).limit(1))).scalar_one_or_none()
            if prev is None:
                node.kind, node.refusal = ABSENCE, _err("no_prior_run", f"{portfolio} has no completed run before {run.as_of_date.isoformat()}; there is nothing earlier to compare with")
                return node
            run = prev
        elif which != "latest":
            node.kind, node.refusal = ABSENCE, _err("type_mismatch", f"which is 'latest', 'prev' or a run_ id; got {which!r}")
            return node
    if isinstance(run, dict):
        node.kind, node.refusal = ABSENCE, run
        return node
    node.kind, node.ref, node.as_of = RUN, run.id, run.as_of_date.isoformat()
    node.payload = {"run_id": run.id, "portfolio_id": run.portfolio_id, "as_of": node.as_of}
    return node


def _run_ref(x: Any) -> str | dict:
    if isinstance(x, Node):
        if x.kind == RUN or (x.kind == TABLE and x.ref and x.ref.startswith("calc_")):
            return x.ref
        return _err("type_mismatch", f"${x.name} is a {x.kind}, not a run or scenario")
    if isinstance(x, str) and x.startswith(("run_", "calc_")):
        return x
    return _err("type_mismatch", f"a run is {{fn: 'run', portfolio: …}} or a run_ id; got {x!r}")


async def _p_column(ctx: _Ctx, node: Node, run: Any, table: str, col: str) -> Node:
    rid = _run_ref(run)
    if isinstance(rid, dict):
        node.kind, node.refusal = ABSENCE, rid
        return node
    resolved = await qn.of_ref(ctx.db, rid)
    prefix, suffix = f"{table}.", f".{col}"
    for q in resolved.quantities:
        if q.not_alone is None and q.label.startswith(prefix) and q.label.endswith(suffix) and q.label.count(".") >= 2:
            label = q.label[len(prefix):-len(suffix)]
            node.entries.append((label, f"{rid}:{q.label}", q.value, q.unit_class))
    if not node.entries:
        tables = sorted({q.label.split(".")[0] for q in resolved.quantities})
        cols = sorted({q.label.rsplit(".", 1)[-1] for q in resolved.quantities if q.label.startswith(prefix)})
        node.kind, node.refusal = ABSENCE, _err("unknown_name", f"{rid} holds no column {table}.<label>.{col}",
                                                tables=tables, columns_of_table=cols)
        return node
    node.kind, node.ref = VECTOR, rid
    node.unit = node.entries[0][3]
    node.measure = f"{table}.{col}"
    node.as_of = run.as_of if isinstance(run, Node) else None
    node.payload = {"run": rid, "table": table, "col": col, "labels": [e[0] for e in node.entries]}
    return node


async def _p_figure(ctx: _Ctx, node: Node, run: Any, name: str) -> Node:
    rid = _run_ref(run)
    if isinstance(rid, dict):
        node.kind, node.refusal = ABSENCE, rid
        return node
    return await _scalar_from_ref(ctx, node, f"{rid}:{name}", {"run": rid, "name": name})


async def _p_method(ctx: _Ctx, node: Node, name: str, subject: Any, params: dict | None = None) -> Node:
    spec = skill.METHODS.get(name)
    if spec is None:
        node.kind, node.refusal = ABSENCE, _err("unknown_method", f"{name!r} is not a method this desk has", nearest=skill.nearest(name))
        return node
    subj = subject.ref if isinstance(subject, Node) else subject
    if not isinstance(subj, str):
        node.kind, node.refusal = ABSENCE, _err("type_mismatch", f"method {name}: subject is a ticker, a run or a portfolio id")
        return node
    p = {k: v for k, v in (params or {}).items() if v is not None}
    from exposure_workbench.tools.arg_validation import validate_args   # the one pure validator, no registry
    problems = validate_args(spec.params_schema, p)
    if problems:
        node.kind, node.refusal = ABSENCE, _err("invalid_params", f"{name}: params do not fit the method's schema", problems=problems, params_schema=spec.params_schema)
        return node
    payload = await _dispatch_method(ctx, spec, subj, p)
    return await _from_payload(ctx, node, payload)


async def _dispatch_method(ctx: _Ctx, spec: skill.Method, subject: str, p: dict) -> dict:
    db, ib, ex = ctx.db, ctx.invoked_by, spec.executor
    if ex == "formula":
        if p.get("last_n"):
            return await formula_service.evaluate_formula_series(db, subject.upper(), spec.name, months=int(p.get("months") or 12), last_n=int(p["last_n"]), invoked_by=ib)
        return await formula_service.evaluate_formula(db, subject.upper(), spec.name, months=int(p.get("months") or 12), at=p.get("at"), invoked_by=ib)
    if ex == "formula.panel":
        return await formula_service.build_panel(db, subject.upper(), months=int(p.get("months") or 12), at=p.get("at"), invoked_by=ib)
    if ex == "price.rolling_volatility":
        return await pas.rolling_volatility(db, subject.upper(), window_days=int(p.get("window_days") or 30), invoked_by=ib)
    if ex == "price.beta":
        return await pas.beta(db, subject.upper(), benchmark=(p.get("benchmark") or "SPY").upper(), window=p.get("window") or pas._DEFAULT_WINDOW, invoked_by=ib)
    if ex == "price.momentum_12_1":
        return await pas.momentum_12_1(db, subject.upper(), invoked_by=ib)
    if ex == "price.distance_from_52w_high":
        return await pas.distance_from_52w_high(db, subject.upper(), invoked_by=ib)
    if ex == "price.adv":
        return await pas.adv(db, subject.upper(), window_days=int(p.get("window_days") or 20), invoked_by=ib)
    if ex == "price.drawdown":
        return await pas.drawdown(db, subject.upper(), window=p.get("window") or pas._DEFAULT_WINDOW, invoked_by=ib)
    if ex == "price.window_return":
        from datetime import timedelta
        from exposure_workbench.services import market_data_service
        days = {"1m": 30, "3m": 91, "6m": 182, "1y": 365}.get(p.get("window") or "1y", 365)
        end = await market_data_service.latest_session_date(db)
        if end is None:
            return _err("no_price_data", "no market prices are loaded yet")
        return await cs.window_return(db, subject.upper(), end - timedelta(days=days), end,
                                      benchmark=(p["benchmark"].upper() if p.get("benchmark") else None), invoked_by=ib)
    if ex == "book.analysis":
        return await integration_service.get_portfolio_analysis(db, subject)
    if ex == "book.reconcile":
        return await reconcile_service.reconcile_move(db, subject)
    if ex == "book.drawdown_episodes":
        return await drawdown_service.get_drawdown_episodes(db, subject, p.get("span") or "1y")
    if ex == "book.explain_episode":
        return await drawdown_service.explain_episode(db, subject, p["peak"], p["trough"])
    if ex == "book.sell":
        return await scenario_service.hypothetical_book(db, subject, p["sales"])
    if ex == "book.buy":
        return await scenario_service.hypothetical_buy(db, subject, p["buys"])
    raise ValueError(f"{spec.name}: executor {ex!r} has no dispatch")


def _operand_refs(x: Any) -> list[tuple[str, str]] | dict:
    """(label, ref) for a scalar node (one entry) or a vector/ranking/table node."""
    if isinstance(x, Node):
        if x.kind == SCALAR:
            return [("", x.ref)]
        if x.kind in (VECTOR, RANKING, TABLE):
            return [(e[0], e[1]) for e in x.entries]
        if x.kind == ABSENCE:
            return _err("depends_on_refused", f"${x.name} was refused: {(x.refusal or {}).get('error')}", node=x.name)
        return _err("type_mismatch", f"${x.name} is a {x.kind}; an arithmetic operand is a figure or a vector of figures")
    if isinstance(x, str) and x.startswith(_ID_PREFIXES):
        return [("", x)]
    return _err("type_mismatch", f"an operand is a binding ($name) or an id; got {x!r}")


async def _p_binary(ctx: _Ctx, node: Node, fn: str, a: Any, b: Any) -> Node:
    op = _BINARY[fn]
    la, lb = _operand_refs(a), _operand_refs(b)
    for side in (la, lb):
        if isinstance(side, dict):
            node.kind, node.refusal = ABSENCE, side
            return node
    if len(la) == 1 and len(lb) == 1:
        return await _from_payload(ctx, node, await tc.calculate(ctx.db, op, la[0][1], lb[0][1], invoked_by=ctx.invoked_by))
    # broadcast: a vector against one figure, or two vectors aligned by label
    if len(la) == 1 or len(lb) == 1:
        one, many, left = (la[0][1], lb, False) if len(la) == 1 else (lb[0][1], la, True)
        pairs = [(lab, (r, one) if left else (one, r)) for lab, r in many]
    else:
        right = dict(lb)
        pairs = [(lab, (r, right[lab])) for lab, r in la if lab in right]
        if not pairs:
            node.kind, node.refusal = ABSENCE, _err("misaligned_vectors", f"{fn}: the two vectors share no label", left=[l for l, _ in la], right=[l for l, _ in lb])
            return node
    node.kind, node.payload = VECTOR, {"op": op, "pairs": len(pairs)}
    refused = []
    for lab, (x, y) in pairs:
        r = await tc.calculate(ctx.db, op, x, y, invoked_by=ctx.invoked_by)
        if r.get("error"):
            refused.append({"label": lab, **{k: r[k] for k in ("error", "detail") if k in r}})
            continue
        node.entries.append((lab, r["calc_id"], float(r["value"]), str((r.get("type") or {}).get("unit_class") or "").upper()))
        node.measure = node.measure or (r.get("type") or {}).get("quantity")
    if refused and not node.entries:
        node.kind, node.refusal = ABSENCE, _err(refused[0]["error"], f"{fn}: every pair was refused; first: {refused[0].get('detail')}", refused=refused)
        return node
    if refused:
        node.payload["refused"] = refused
    node.ref = node.entries[0][1]
    node.unit = node.entries[0][3]
    return node


async def _p_scale(ctx: _Ctx, node: Node, of: Any, factor: Any, unit: str | None = None) -> Node:
    refs = _operand_refs(of)
    if isinstance(refs, dict) or len(refs) != 1:
        node.kind, node.refusal = ABSENCE, (refs if isinstance(refs, dict) else _err("type_mismatch", "scale takes one figure"))
        return node
    if not _is_num(factor):
        node.kind, node.refusal = ABSENCE, _err("type_mismatch", "scale: factor is a number")
        return node
    left = await tc._resolve(ctx.db, refs[0][1])
    if isinstance(left, dict):
        node.kind, node.refusal = ABSENCE, left
        return node
    return await _from_payload(ctx, node, await tc.scale(ctx.db, refs[0][1], float(factor), unit_class=(unit or left.unit_class), invoked_by=ctx.invoked_by))


async def _fold_add(ctx: _Ctx, refs: list[str]) -> dict:
    acc, step = refs[0], {}
    for nxt in refs[1:]:
        step = await tc.calculate(ctx.db, "add", acc, nxt, invoked_by=ctx.invoked_by)
        if step.get("error"):
            return step | {"at": nxt}
        acc = step["calc_id"]
    return step


async def _p_set(ctx: _Ctx, node: Node, fn: str, of: Any) -> Node:
    refs = _operand_refs(of)
    if isinstance(refs, dict):
        node.kind, node.refusal = ABSENCE, refs
        return node
    ids = [r for _, r in refs]
    if fn == "abs":
        if len(ids) != 1:
            node.kind, node.refusal = ABSENCE, _err("type_mismatch", "abs takes one figure")
            return node
        return await _from_payload(ctx, node, await tc.aggregate(ctx.db, "abs", ids, invoked_by=ctx.invoked_by))
    if isinstance(of, Node) and of.kind == SERIES:
        return await _p_series_op(ctx, node, fn, of)
    if len(ids) < 2:
        node.kind, node.refusal = ABSENCE, _err("type_mismatch", f"{fn} over a set needs two or more figures (a vector); over one series, pass the series")
        return node
    if fn == "sum":
        return await _from_payload(ctx, node, await _fold_add(ctx, ids))
    return await _from_payload(ctx, node, await tc.aggregate(ctx.db, fn, ids, invoked_by=ctx.invoked_by))


async def _p_rank(ctx: _Ctx, node: Node, of: Any, direction: str | None = None) -> Node:
    refs = _operand_refs(of)
    if isinstance(refs, dict):
        node.kind, node.refusal = ABSENCE, refs
        return node
    r = await tc.rank(ctx.db, [x for _, x in refs], direction=direction or "highest", invoked_by=ctx.invoked_by)
    if r.get("error"):
        node.kind, node.refusal = ABSENCE, r
        return node
    node.kind, node.ref, node.payload, node.as_of = RANKING, r["calc_id"], r, r.get("as_of")
    node.measure = r.get("quantity")
    node.unit = str((r.get("type") or {}).get("unit_class") or "").upper()
    node.entries = [(e["label"], e["ref"], e["value"], node.unit) for e in r["ordering"]]
    return node


async def _p_top(ctx: _Ctx, node: Node, of: Any, n: Any, direction: str | None = None) -> Node:
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        node.kind, node.refusal = ABSENCE, _err("type_mismatch", "top: n is a positive integer")
        return node
    ranked = await _p_rank(ctx, Node(f"_{node.name}_rank", RANKING, None), of, direction)
    if not ranked.ok:
        node.kind, node.refusal = ABSENCE, ranked.refusal
        return node
    ctx.nodes[ranked.name] = ranked
    node.deps.append(ranked.name)
    node.kind, node.ref, node.unit, node.measure, node.as_of = VECTOR, ranked.ref, ranked.unit, ranked.measure, ranked.as_of
    node.entries = ranked.entries[:n]
    node.payload = {"of": ranked.ref, "n": n, "direction": direction or "highest", "labels": [e[0] for e in node.entries]}
    return node


async def _p_series_op(ctx: _Ctx, node: Node, fn: str, of: Any) -> Node:
    if not (isinstance(of, Node) and of.kind == SERIES):
        node.kind, node.refusal = ABSENCE, _err("type_mismatch", f"{fn} takes a series; ${getattr(of, 'name', '?')} is a {getattr(of, 'kind', type(of).__name__)}")
        return node
    s: tc.TypedSeries = of.typed
    pts = [so.SeriesPoint(period_end=d, value=t.value, input_fact_ids=[t.source_id] if t.source_id else []) for d, t in s.points]
    rtype = {"unit_class": s.unit_class, "kind": s.kind, "quantity": s.quantity}
    return await _from_payload(ctx, node, await series_service.stat_over(ctx.db, pts, rtype, s.source_id or of.ref, fn, invoked_by=ctx.invoked_by))


async def _p_at(ctx: _Ctx, node: Node, of: Any, period: str) -> Node:
    if not (isinstance(of, Node) and of.kind == SERIES and of.ref):
        node.kind, node.refusal = ABSENCE, _err("type_mismatch", "at takes a series and a period (YYYY-MM-DD)")
        return node
    resolved = await qn.of_ref(ctx.db, of.ref)
    labels = [q.label for q in resolved.quantities if q.label.endswith(f"@{period}")]
    if not labels:
        held = sorted(q.label.rsplit("@", 1)[-1] for q in resolved.quantities if "@" in q.label)
        node.kind, node.refusal = ABSENCE, _err("unknown_point", f"${of.name} holds no point at {period}", available=held[-12:])
        return node
    return await _scalar_from_ref(ctx, node, f"{of.ref}:{labels[0]}", {"series": of.ref, "period": period})


async def _p_scenario(ctx: _Ctx, node: Node, fn: str, run: Any, trades: Any) -> Node:
    rid = _run_ref(run)
    if isinstance(rid, dict):
        node.kind, node.refusal = ABSENCE, rid
        return node
    if fn == "sell":
        payload = await scenario_service.hypothetical_book(ctx.db, rid, trades)
    else:
        payload = await scenario_service.hypothetical_buy(ctx.db, rid, trades)
    return await _from_payload(ctx, node, payload)


async def _evaluate(ctx: _Ctx, name: str, expr: Any) -> Node:
    node = Node(name, ABSENCE, expr)
    if not (isinstance(expr, dict) and "fn" in expr):
        # a literal binding: kept for reference (a rate, a date); not a figure
        val, deps = _deref(ctx, expr)
        if isinstance(val, Node):
            ctx.nodes[name] = val
            return val
        node.kind, node.payload, node.deps = TABLE, {"literal": val}, deps
        return node
    fn = expr["fn"]
    if fn not in PRIMITIVES:
        node.refusal = _err("unknown_primitive", f"{fn!r} is not a primitive of this desk", primitives=sorted(PRIMITIVES))
        return node
    req, opt = PRIMITIVES[fn]
    given = {k: v for k, v in expr.items() if k != "fn"}
    missing = [k for k in req if k not in given]
    extra = [k for k in given if k not in req + opt]
    if missing or extra:
        node.refusal = _err("type_mismatch", f"{fn} takes {req}{' and optionally ' + str(opt) if opt else ''}"
                                             + (f"; missing {missing}" if missing else "") + (f"; unknown {extra}" if extra else ""))
        return node
    args, deps = {}, []
    for k, v in given.items():
        val, d = _deref(ctx, v)
        if isinstance(val, dict) and val.get("error") == "unknown_binding":
            node.refusal = val
            return node
        args[k] = val
        deps += d
    node.deps = deps
    for d in deps:
        dep = ctx.nodes[d]
        if dep.kind == ABSENCE and fn not in ("run",):
            node.refusal = _err("depends_on_refused", f"${d} was refused: {(dep.refusal or {}).get('error')}: {(dep.refusal or {}).get('detail', '')[:160]}", node=d)
            return node
    try:
        if fn == "fundamentals":
            return await _p_fundamentals(ctx, node, **args)
        if fn == "prices":
            return await _p_prices(ctx, node, **args)
        if fn == "price":
            return await _p_price(ctx, node, **args)
        if fn == "run":
            return await _p_run(ctx, node, **args)
        if fn == "column":
            return await _p_column(ctx, node, **args)
        if fn == "figure":
            return await _p_figure(ctx, node, **args)
        if fn == "method":
            return await _p_method(ctx, node, **args)
        if fn in _BINARY:
            return await _p_binary(ctx, node, fn, **args)
        if fn == "scale":
            return await _p_scale(ctx, node, **args)
        if fn in ("sum",) + _SET_OPS:
            return await _p_set(ctx, node, fn, **args)
        if fn == "rank":
            return await _p_rank(ctx, node, **args)
        if fn == "top":
            return await _p_top(ctx, node, **args)
        if fn in _SERIES_OPS:
            return await _p_series_op(ctx, node, fn, **args)
        if fn == "at":
            return await _p_at(ctx, node, **args)
        if fn in ("sell", "buy"):
            return await _p_scenario(ctx, node, fn, args["run"], args.get("sales") if fn == "sell" else args.get("buys"))
    except TypeError as exc:
        node.kind, node.refusal = ABSENCE, _err("type_mismatch", f"{fn}: {exc}")
        return node
    node.refusal = _err("unknown_primitive", f"{fn!r} has no dispatch")     # PRIMITIVES ⊆ dispatch is pinned by test
    return node


# ── facts ────────────────────────────────────────────────────────────────────

def _subject_of(t, fallback: str | None) -> str | None:
    if isinstance(t, (tc.Typed, tc.TypedSeries)) and len(t.issuers) == 1 and isinstance(t.issuers[0], str):
        return t.issuers[0]
    if isinstance(t, tc.Typed) and t.base:
        return t.base
    return fallback


def _facts_of(node: Node) -> list[F.Fact]:
    """The Facts a settled node puts on the table. A vector is one scalar Fact
    per entry, each carrying the node it belongs to and its label."""
    p = {"node": node.name}
    group = "book_derived" if (node.ref or "").startswith(("run_", "calc_")) and node.kind in (VECTOR, RANKING, TABLE) else "derived"
    if node.kind == SCALAR and isinstance(node.typed, tc.Typed):
        as_of, unit, measure, window = _typed_identity(node.typed)
        return [F.fact(F.SCALAR, measure or node.name, subject=_subject_of(node.typed, None), unit=unit,
                       value=float(node.typed.value), as_of=as_of, window=window, params=p,
                       sources=(node.ref,) if node.ref else (), group=group)]
    if node.kind == SERIES and isinstance(node.typed, tc.TypedSeries):
        as_of, unit, measure, window = _typed_identity(node.typed)
        pts = tuple((d.isoformat(), float(t.value)) for d, t in node.typed.points)
        return [F.fact(F.SERIES, measure or node.name, subject=_subject_of(node.typed, None), unit=unit,
                       points=pts, as_of=as_of, window=window, params=p, sources=(node.ref,) if node.ref else (), group=group)]
    if node.kind in (VECTOR, RANKING, TABLE):
        out = []
        for i, (label, ref, value, unit) in enumerate(node.entries):
            if value is None:
                continue
            extra = dict(p, label=label)
            if node.kind == RANKING:
                extra["rank"] = i + 1
            measure = node.measure if node.kind in (VECTOR, RANKING) and node.measure else label
            subj = label if node.kind in (VECTOR, RANKING) else (node.ref if node.kind == TABLE else None)
            if node.kind == TABLE and ":" not in ref and "." in label:
                parts = label.split(".")
                if len(parts) == 3:
                    measure, subj = f"{parts[0]}.{parts[2]}", parts[1]
            out.append(F.fact(F.SCALAR, measure, subject=subj, unit=unit or None, value=float(value),
                              as_of=node.as_of or "n/a", params=extra, sources=(ref,) if ref else (), group=group))
        return out
    if node.kind == ABSENCE and node.refusal:
        r = node.refusal
        return [F.fact(F.ABSENCE, node.name, text=f"{r.get('error')}: {r.get('detail', '')}"[:600],
                       as_of="n/a", params={**p, "error": r.get("error")}, group=group)]
    return []


# ── the entry point ──────────────────────────────────────────────────────────

async def run(db: AsyncSession, program: dict, *, invoked_by: str = "agent") -> dict:
    """Parse, evaluate and record one program. Returns the result table:
    `nodes` (name → identity and value, or refusal), `facts` (record form, one
    per figure), `program_id` (the ledger row of the run)."""
    parsed = parse(program)
    if isinstance(parsed, dict):
        return parsed
    ctx = _Ctx(db, invoked_by)
    for name, expr in parsed.bindings:
        node = await _evaluate(ctx, name, expr)
        node.name = name
        ctx.nodes[name] = node
    facts: list[F.Fact] = []
    nodes_out: dict[str, dict] = {}
    refs: list[str] = []
    for name, node in ctx.nodes.items():
        node.facts = _facts_of(node)
        facts += node.facts
        if node.ref:
            refs.append(node.ref)
        nodes_out[name] = _note_of(node)
    program_id = await cs._record(
        db, None, PROGRAM_OP,
        {"program": parsed.source, "nodes": {n: nd.ref for n, nd in ctx.nodes.items()},
         "refused": [n for n, nd in ctx.nodes.items() if nd.kind == ABSENCE]},
        {"nodes": {n: {"kind": nd.kind, "facts": [f.id for f in nd.facts]} for n, nd in ctx.nodes.items()}},
        list(dict.fromkeys(refs)), {}, invoked_by)
    settled = sum(1 for n in ctx.nodes.values() if n.kind != ABSENCE and not n.name.startswith("_"))
    refused = [n for n, nd in ctx.nodes.items() if nd.kind == ABSENCE and not n.startswith("_")]
    return {"program_id": program_id, "returns": parsed.returns, "nodes": nodes_out,
            "settled": settled, "refused": refused,
            "_facts": [F.for_record(f) for f in facts]}


def _note_of(node: Node) -> dict:
    out: dict = {"kind": node.kind}
    if node.deps:
        out["deps"] = node.deps
    if node.kind == ABSENCE:
        out["refusal"] = {k: v for k, v in (node.refusal or {}).items() if k in ("error", "detail", "node", "available", "nearest", "tables", "columns_of_table", "problems", "refused", "last_reported")}
        if node.facts:
            out["fact"] = node.facts[0].id
        return out
    if node.unit:
        out["unit"] = node.unit
    if node.measure:
        out["measure"] = node.measure
    if node.as_of:
        out["as_of"] = node.as_of
    if node.kind == RUN:
        out["run"] = node.ref
        out["portfolio"] = node.payload.get("portfolio_id")
        return out
    if node.kind in (SCALAR, SERIES) and node.facts:
        out["fact"] = node.facts[0].id
        out["subject"] = node.facts[0].subject
        if node.kind == SCALAR:
            out["value"] = node.facts[0].value
        else:
            out["points"] = len(node.facts[0].points or ())
            out["window"] = node.facts[0].window
        if node.payload.get("basis"):
            out["basis"] = node.payload["basis"]
        return out
    if node.kind in (VECTOR, RANKING, TABLE):
        by_label = {f.params.get("label"): f for f in node.facts}
        out["entries"] = {label: {"fact": by_label[label].id, "value": by_label[label].value,
                                  **({"unit": unit} if node.kind == TABLE and unit else {})}
                          for label, _r, _v, unit in node.entries if label in by_label}
        if node.kind == RANKING:
            out["order"] = [e[0] for e in node.entries]
            out["leader"] = node.entries[0][0] if node.entries else None
        if node.payload.get("refused"):
            out["refused_entries"] = node.payload["refused"]
        if node.payload.get("literal") is not None:
            out["literal"] = node.payload["literal"]
        return out
    if node.payload.get("literal") is not None:
        out["literal"] = node.payload["literal"]
    return out
