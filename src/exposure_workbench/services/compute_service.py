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
        if len(operands) != 2:
            return _err("operands", f"{op} takes exactly two operands (fact_/calc_ ids or ref:name "
                                    f"figures on a run, analysis or scenario row); got {len(operands)}")
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
        if len(operands) != 1:
            return _err("operands", f"{op} takes one operand: a series' calc_ id")
        return await series_service.series_stat(db, operands[0], op, invoked_by=invoked_by)
    return _err("unsupported_op", f"{op!r} is not an op this desk has", supported=list(OPS))


# ── methods ──────────────────────────────────────────────────────────────────

async def _run_method(db: AsyncSession, spec: skill.Method, subject: str, params: dict,
                      invoked_by: str) -> dict:
    ex = spec.executor
    p = {k: v for k, v in params.items() if v is not None}
    if ex == "formula":
        return await formula_service.evaluate_formula(
            db, subject.upper(), spec.name, months=int(p.get("months") or 12), at=p.get("at"),
            invoked_by=invoked_by)
    if ex == "formula.panel":
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
