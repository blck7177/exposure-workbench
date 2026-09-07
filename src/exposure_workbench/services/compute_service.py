"""compute — the one entry through which a figure is COMPUTED on this desk (V23).

Two things arrive here and nothing else computes:

  * an OP over operands — the four scalar operators, `rank`, the series
    statistics and the regression — dispatched to the typed calculator, the
    series service and the price service exactly as the seven tools they
    replace did;
  * a METHOD from the skill registry (analytics/skill.py) over a subject —
    an issuer measure, a price statistic, a book derivation, a scenario —
    dispatched to the service that has always computed it.

Why one tool: thirteen tools existed because each method needed an entry
point, and each entry point needed a description that told the model WHEN to
use it — thirty-one thousand characters of "use this for" that took the
analyst's judgement away from the agent (IMPLEMENTATION_PLAN_V23 §0). The
method is data; the tool is its executor; the description is one line.

What does not move: every refusal the calculator and the services make.
R1–R3, the units, the base rules, the observation floors, the scenario's
five refusals — all of it runs unchanged inside the executors this module
calls. Compute adds exactly two refusals of its own: an unknown method (with
the nearest names) and params that do not fit the method's declared schema.

Subjects and methods take LISTS. Ten issuers' net margin is one call; the
result is one entry per subject, each its own row with its own id or its own
refusal. This is what retires the per-call unit of the budget: the call is
charged once per message (agent_session_service.reserve, V23).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import skill
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services import drawdown_service, formula_service, integration_service
from exposure_workbench.services import price_analytics_service as pas
from exposure_workbench.services import reconcile_service, scenario_service, series_service
from exposure_workbench.services import typed_calculator as tc
from exposure_workbench.tools.arg_validation import validate_args
from exposure_workbench.tools.registry import current_session_id

# The ops, as the model spells them. Series ops come from the series module's
# own list so a change there is a change here.
SERIES_OPS: tuple[str, ...] = tuple(series_service.OPS)
OPS: tuple[str, ...] = skill.SCALAR_OPS + (skill.SCALE_OP, skill.RANK_OP, skill.REGRESS_OP) + SERIES_OPS


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


async def compute(db: AsyncSession, *, op: str | None = None, method: str | list[str] | None = None,
                  operands: list[str] | None = None, subject: str | list[str] | None = None,
                  params: dict | None = None, as_quantity: str | None = None,
                  direction: str | None = None) -> dict:
    if (op is None) == (method is None):
        return _err("op_or_method", "give exactly one of `op` (arithmetic over operands) or "
                                    "`method` (a registry method over a subject)")
    if op is not None:
        return await _op(db, op, operands or [], as_quantity, direction, params or {})
    methods = [method] if isinstance(method, str) else list(method)
    subjects = [subject] if isinstance(subject, str) else list(subject or [])
    if not subjects:
        return _err("subject_required", "a method is computed over a subject: a ticker, a run id "
                                        "(run_…) or a portfolio id, or a list of them")
    unknown = [m for m in methods if m not in skill.METHODS]
    if unknown:
        return _err("unknown_method",
                    f"{', '.join(unknown)}: not a method this desk has",
                    held_on={"method": method} if isinstance(method, str) else {},
                    nearest={m: skill.nearest(m) for m in unknown},
                    known=sorted(skill.METHODS))
    invoked_by = current_session_id()
    results: list[dict] = []
    for m in methods:
        spec = skill.METHODS[m]
        problems = validate_args(spec.params_schema, params or {})
        if problems:
            return _err("invalid_params", f"{m}: params do not fit the method's schema",
                        problems=problems, params_schema=spec.params_schema)
        for s in subjects:
            out = await _run_method(db, spec, s, params or {}, invoked_by)
            results.append({"method": m, "subject": s, **out})
    if len(results) == 1:
        return results[0]
    return {"results": results, "count": len(results)}


# ── ops ──────────────────────────────────────────────────────────────────────

async def _op(db: AsyncSession, op: str, operands: list[str], as_quantity: str | None,
              direction: str | None, params: dict) -> dict:
    invoked_by = current_session_id()
    by = params.get("by")
    if by is not None and not isinstance(by, str):
        return _err("params", "params.by names ONE figure (a fact_/calc_/f_ id or ref:name) that every "
                              "operand is combined with")
    if op == skill.SCALE_OP:
        # A constant is not an operand (typed_calculator.scale's docstring): the
        # first live V23 turn wrote "book_market_value*0.15" as an operand.
        if len(operands) != 1 or not isinstance(params.get("factor"), (int, float)):
            return _err("operands", "scale takes one operand and params.factor (a number): "
                                    "compute(op='scale', operands=[ref], params={'factor': 0.15})")
        left = await tc._resolve(db, operands[0])
        if isinstance(left, dict):
            return left
        unit = params.get("unit_class") or left.unit_class
        return await tc.scale(db, operands[0], float(params["factor"]), unit_class=unit,
                              quantity=as_quantity, invoked_by=invoked_by)
    if op in skill.SCALAR_OPS:
        # V25: the four operators used to take exactly two operands, and the
        # 2026-09-06 battery paid for it in round trips — the top-five share
        # was seven `add` calls and lost the turn; five uses of cash over one
        # operating cash flow was five `divide` calls. A sum or a product is
        # folded pairwise through the SAME calculate, so every pair rule (R1–R3,
        # the units, the books) still fires, on the pair it fires on. A list
        # against ONE figure (params.by) is each operand combined with it.
        if by is not None:
            if not operands:
                return _err("operands", f"{op} with params.by takes one or more operands, each "
                                        f"{op}d with the figure `by` names")
            return await _broadcast(db, op, operands, by, as_quantity, invoked_by)
        if op in ("add", "multiply"):
            if len(operands) < 2:
                return _err("operands", f"{op} takes two or more operands (fact_/calc_ ids or ref:name "
                                        f"figures on a run, analysis or scenario row); got {len(operands)}")
            return await _fold(db, op, operands, as_quantity, invoked_by)
        if len(operands) != 2:
            return _err("operands", f"{op} takes exactly two operands; to {op} each of a list by one "
                                    f"figure, pass the list as operands and the figure as params.by; "
                                    f"got {len(operands)}")
        return await tc.calculate(db, op, operands[0], operands[1], invoked_by=invoked_by,
                                  as_quantity=as_quantity,
                                  named_by="session" if as_quantity else None)
    if op == skill.RANK_OP:
        if len(operands) < 2:
            return _err("operands", "rank takes two or more operands, one per name being ordered")
        return await tc.rank(db, operands, direction=direction or "highest",
                             as_quantity=as_quantity, invoked_by=invoked_by)
    if op == skill.REGRESS_OP:
        if len(operands) != 2:
            return _err("operands", "regress takes two operands: [series_x, series_y] as calc_ ids")
        return await pas.regress(db, operands[0], operands[1], invoked_by=invoked_by)
    if op in SERIES_OPS:
        return await _stat(db, op, operands, as_quantity, invoked_by)
    return _err("unsupported_op", f"{op!r} is not an op this desk has", supported=list(OPS))


async def _fold(db: AsyncSession, op: str, operands: list[str], as_quantity: str | None,
                invoked_by: str) -> dict:
    """add or multiply over N operands: the pairwise operator, folded. Each
    intermediate is a ledger row of its own; the last carries the caller's
    name. A refusal names the operand the fold stopped at."""
    acc = operands[0]
    steps: list[str] = []
    step: dict = {}
    for i, nxt in enumerate(operands[1:], start=2):
        final = i == len(operands)
        step = await tc.calculate(db, op, acc, nxt, invoked_by=invoked_by,
                                  as_quantity=as_quantity if final else None,
                                  named_by="session" if (as_quantity and final) else None)
        if step.get("error"):
            return step | {"at": nxt, "folded_so_far": steps,
                           "detail": f"{op} stopped at operand {i} of {len(operands)} ({nxt}): "
                                     + step.get("detail", step["error"])}
        acc = step["calc_id"]
        steps.append(acc)
    return step | {"operands": list(operands), "folded": steps[:-1],
                   "basis": f"{op} over {len(operands)} figures, folded pairwise; " + step.get("basis", "")}


async def _broadcast(db: AsyncSession, op: str, operands: list[str], by: str,
                     as_quantity: str | None, invoked_by: str) -> dict:
    """Each operand combined with ONE figure: five uses of cash each divided by
    operating cash flow, ten weights each multiplied by the book's market
    value. One entry per operand, each its own row or its own refusal, the
    shape a method over a list of subjects already returns."""
    results = []
    for x in operands:
        r = await tc.calculate(db, op, x, by, invoked_by=invoked_by, as_quantity=as_quantity,
                               named_by="session" if as_quantity else None)
        results.append({"operand": x, **r})
    return {"op": op, "by": by, "results": results, "count": len(results),
            "basis": f"each of {len(operands)} figures, {op} {by}"}


async def _stat(db: AsyncSession, op: str, operands: list[str], as_quantity: str | None,
                invoked_by: str) -> dict:
    """A series statistic over ONE series, or a set statistic over SEVERAL
    figures. V25: the series ops were defined on a ledgered series only, and
    the battery asked them of a set of figures six times (`sum` of five
    weights, `abs` of one distance) and read `unknown_series` six times. A set
    of like figures is the other thing an analyst takes a statistic of."""
    if not operands:
        return _err("operands", f"{op} takes one series, or two or more figures")
    if len(operands) == 1:
        left = await tc._resolve(db, operands[0])
        if isinstance(left, dict):
            return left
        if isinstance(left, tc.TypedSeries):
            return await series_service.series_stat(db, operands[0], op, invoked_by=invoked_by)
        if op == "abs":
            return await tc.aggregate(db, "abs", operands, as_quantity=as_quantity, invoked_by=invoked_by)
        return _err("not_a_series",
                    f"{operands[0]} is one figure, and {op} over one figure is not defined. Over a "
                    f"series, {op} takes the series' calc_ id (read_fundamentals(last_n=…), "
                    f"read_prices(window=…), or compute(method=…, params={{'last_n': …}}) "
                    f"produce one); over a set, it takes two or more figures.")
    if op == "sum":
        return await _fold(db, "add", operands, as_quantity, invoked_by)
    if op in tc.SET_OPS:
        return await tc.aggregate(db, op, operands, as_quantity=as_quantity, invoked_by=invoked_by)
    return _err("series_only",
                f"{op} compares points of ONE series in time; it has no meaning over a set of "
                f"separate figures. The change between two figures is subtract (the difference) "
                f"or divide (the ratio); a series to take {op} of comes from read_fundamentals"
                f"(last_n=…), read_prices(window=…) or compute(method=…, params={{'last_n': …}}).")


# ── methods ──────────────────────────────────────────────────────────────────

async def _run_method(db: AsyncSession, spec: skill.Method, subject: str, params: dict,
                      invoked_by: str) -> dict:
    ex = spec.executor
    p = {k: v for k, v in params.items() if v is not None}
    if ex == "formula":
        if p.get("last_n"):
            return await formula_service.evaluate_formula_series(
                db, subject.upper(), spec.name, months=int(p.get("months") or 12),
                last_n=int(p["last_n"]), invoked_by=invoked_by)
        return await formula_service.evaluate_formula(
            db, subject.upper(), spec.name, months=int(p.get("months") or 12), at=p.get("at"),
            invoked_by=invoked_by)
    if ex == "formula.panel":
        if p.get("last_n"):
            return _err("invalid_params", "issuer.panel has no series form; ask one measure for "
                                          "its last_n periods: compute(method='gross_margin', "
                                          "subject=…, params={'last_n': 8})")
        return await formula_service.build_panel(
            db, subject.upper(), months=int(p.get("months") or 12), at=p.get("at"), invoked_by=invoked_by)
    if ex == "price.rolling_volatility":
        return await pas.rolling_volatility(db, subject.upper(), window_days=int(p.get("window_days") or 30),
                                            invoked_by=invoked_by)
    if ex == "price.beta":
        return await pas.beta(db, subject.upper(), benchmark=(p.get("benchmark") or "SPY").upper(),
                              window=p.get("window") or pas._DEFAULT_WINDOW, invoked_by=invoked_by)
    if ex == "price.momentum_12_1":
        return await pas.momentum_12_1(db, subject.upper(), invoked_by=invoked_by)
    if ex == "price.distance_from_52w_high":
        return await pas.distance_from_52w_high(db, subject.upper(), invoked_by=invoked_by)
    if ex == "price.adv":
        return await pas.adv(db, subject.upper(), window_days=int(p.get("window_days") or 20),
                             invoked_by=invoked_by)
    if ex == "price.drawdown":
        return await pas.drawdown(db, subject.upper(), window=p.get("window") or pas._DEFAULT_WINDOW,
                                  invoked_by=invoked_by)
    if ex == "price.window_return":
        return await _window_return(db, subject.upper(), p.get("window") or "1y",
                                    p.get("benchmark"), invoked_by)
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
    raise ValueError(f"{spec.name}: executor {ex!r} has no dispatch")   # skill.EXECUTORS pins this


async def _window_return(db: AsyncSession, ticker: str, window: str, benchmark: str | None,
                         invoked_by: str) -> dict:
    """The old get_market_stats: a total return over a named window ending at
    the last completed session (a server fact, never the clock)."""
    from exposure_workbench.services import market_data_service
    days = {"1m": 30, "3m": 91, "6m": 182, "1y": 365}.get(window, 365)
    end = await market_data_service.latest_session_date(db)
    if end is None:
        return _err("no_price_data", "no market prices are loaded yet")
    start = end - timedelta(days=days)
    return await cs.window_return(db, ticker, start, end,
                                  benchmark=(benchmark.upper() if benchmark else None),
                                  invoked_by=invoked_by)


def executors_dispatched() -> tuple[str, ...]:
    """Every executor string `_run_method` handles — for the symmetry test
    against skill.EXECUTORS, so a registry entry cannot name an executor the
    dispatcher does not have (and vice versa)."""
    import inspect
    src = inspect.getsource(_run_method)
    return tuple(e for e in skill.EXECUTORS if f'ex == "{e}"' in src)
