"""Evaluate a named formula, and the panel that is nothing but a batch of them.

Every value here is produced by the same primitives an agent can call itself:
get_flow for a window, get_balance_sheet for an instant, containment cover for a
total, the typed calculator for the arithmetic. This service adds no arithmetic
of its own — the test that matters asserts the panel's lines can each be
reproduced by one evaluate_formula call, which is the difference between a
convenience and a privileged path.

Nothing here decides anything. No threshold, no flag, no verdict: the panel lays
out measured values with their definitions and period bases, and the reading
belongs to the reader.

Financial issuers are refused outright. Interest expense is an operating cost
for a bank — JPM's quarterly interest of 24.356bn exceeds its net income of
16.494bn — so leverage and coverage built on adding it back describe nothing,
and every ratio on this panel rests on that.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import containment as ct
from exposure_workbench.analytics import formulas as fm
from exposure_workbench.db.models import Position
from exposure_workbench.services import fundamentals_service as fs
from exposure_workbench.services import typed_calculator as tc

FINANCIAL_SECTORS = {"Financials", "Financial Services"}
DAYS_IN_YEAR = 365


async def _sector(db: AsyncSession, ticker: str) -> str | None:
    """positions is the only usable sector here: companies.sector holds a SIC
    code for one issuer and NULL for the rest, and security_master has no
    sector column."""
    return (await db.execute(
        select(Position.sector).where(Position.ticker == ticker.upper(),
                                      Position.sector.is_not(None)).limit(1)
    )).scalar_one_or_none()


async def _bank_refusal(db: AsyncSession, ticker: str) -> dict | None:
    sector = await _sector(db, ticker)
    if sector in FINANCIAL_SECTORS:
        return {"error": "not_applicable", "ticker": ticker, "sector": sector,
                "detail": ("these are non-financial credit measures and they do not apply "
                           "to a financial issuer: interest expense is an operating cost "
                           "for a bank, so coverage and leverage built on adding it back "
                           "describe nothing")}
    return None


async def _operand(db: AsyncSession, ticker: str, name: str, months: int,
                   at: str | None, cache: dict, invoked_by: str,
                   window: tuple[str, str] | None = None) -> dict:
    """A metric or a formula, as {id, value} — or an error dict.

    `window` pins the period for flow inputs. It is not optional in practice:
    without it each metric picks its own most recent derivable window, and the
    acceptance battery caught what that produces — NVDA's EBIT built from 2026
    net income and 2024 interest expense, the two windows merely failing to
    overlap. A formula's flow inputs describe ONE period or they describe
    nothing.
    """
    key = (name, window)
    if key in cache:
        return cache[key]

    if name in fm.FORMULAS:
        # A formula used as an input returns an evaluation, whose id lives under
        # calc_id. Normalised here so the caller sees one operand shape whether
        # it fetched a fact, a window or a nested formula.
        ev = await evaluate_formula(db, ticker, name, months=months, at=at,
                                    invoked_by=invoked_by, _cache=cache, _window=window)
        got = ev if ev.get("error") else {"id": ev["calc_id"], "value": ev["value"],
                                          "basis": ev["basis"]}
    elif name == "total_debt":
        got = await _total_debt(db, ticker, at, invoked_by)
    else:
        bs = cache.get("_balance_sheet")
        if bs is None:
            bs = await fs.get_balance_sheet(db, ticker, at=at, invoked_by=invoked_by)
            cache["_balance_sheet"] = bs
        if not bs.get("error") and name in bs.get("balances", {}):
            line = bs["balances"][name]
            got = {"id": line["fact_id"], "value": line["value"],
                   "basis": f"as of {line['as_of']}"}
        else:
            flow = (await fs.get_flow(db, ticker, name, start=window[0], end=window[1],
                                      invoked_by=invoked_by) if window
                    else await fs.get_flow(db, ticker, name, months=months,
                                           invoked_by=invoked_by))
            got = (flow if flow.get("error")
                   else {"id": flow["calc_id"], "value": flow["value"],
                         "basis": flow["basis"], "period": flow.get("period")})
    cache[key] = got
    return got


async def _total_debt(db: AsyncSession, ticker: str, at: str | None, invoked_by: str) -> dict:
    """Composed by containment cover, then summed through the typed calculator so
    every step is ledgered like any other."""
    bs = await fs.get_balance_sheet(db, ticker, at=at, invoked_by=invoked_by)
    if bs.get("error"):
        return bs
    available = {m: line["value"] for m, line in bs["balances"].items()}
    cover = ct.cover(available, family="debt")
    if isinstance(cover, ct.NoCover):
        return {"error": "not_reported", "metric": "total_debt", "detail": cover.reason}

    ids = [bs["balances"][m]["fact_id"] for m in cover.terms]
    running_id, running_value = ids[0], bs["balances"][cover.terms[0]]["value"]
    for term, fid in zip(cover.terms[1:], ids[1:]):
        step = await tc.calculate(db, "add", running_id, fid, invoked_by=invoked_by)
        if step.get("error"):
            return step
        running_id, running_value = step["calc_id"], step["value"]
    return {"id": running_id, "value": running_value,
            "basis": f"as of {bs['as_of']}", "formula": cover.formula,
            "uncovered": list(cover.uncovered)}


async def _common_window(db: AsyncSession, ticker: str, f, months: int,
                         invoked_by: str) -> tuple[str, str] | None:
    """The most recent window EVERY flow input of a formula can reach.

    Anchored on the BINDING input — the one whose data runs out first — not on
    the most recent one. Anchoring on the newest was the first attempt and it
    refuses formulas the data supports: LLY's interest expense (under the tag it
    moved to) reaches 2025-12-31 while its net income reaches 2026, so a window
    anchored on net income fails on an input that was there all along.

    Each input may satisfy the anchor through a named alternative, which is why
    the alternatives are consulted here as well as at fetch time.
    """
    from exposure_workbench.analytics import formulas as _fm
    flows = [i for i in f.inputs if i not in _fm.FORMULAS and i != "total_debt"]
    binding: tuple[str, str] | None = None
    for metric in flows:
        candidates = (metric,) + tuple(f.alternatives.get(metric, ()))
        reach: tuple[str, str] | None = None
        for cand in candidates:
            got = await fs.get_flow(db, ticker, cand, months=months, invoked_by=invoked_by)
            if got.get("error"):
                continue
            p_ = got["period"]
            if reach is None or p_["end"] > reach[1]:
                reach = (p_["start"], p_["end"])
        if reach is None:
            continue                      # unavailable entirely; reported at fetch
        if binding is None or reach[1] < binding[1]:
            binding = reach
    return binding


async def evaluate_formula(db: AsyncSession, ticker: str, name: str, *,
                           months: int = 12, at: str | None = None,
                           invoked_by: str = "agent", _cache: dict | None = None,
                           _window: tuple[str, str] | None = None) -> dict:
    """One named measure, built from the primitives an agent could call itself."""
    ticker = ticker.upper()
    if name not in fm.FORMULAS and name != "total_debt":
        return {"error": "unknown_formula", "formula": name,
                "known": sorted(fm.FORMULAS)}
    refusal = await _bank_refusal(db, ticker)
    if refusal:
        return refusal

    cache = _cache if _cache is not None else {}
    if name == "total_debt":
        got = await _total_debt(db, ticker, at, invoked_by)
        if got.get("error"):
            return got
        f = fm.FORMULAS["total_debt"]
        return {"formula": name, "ticker": ticker, "value": got["value"],
                "calc_id": got["id"], "definition": got.get("formula", f.expression),
                "basis": got["basis"], "source_url": f.source_url, "note": f.note,
                "uncovered": got.get("uncovered", [])}

    f = fm.FORMULAS[name]
    window = _window
    if window is None and f.basis in ("window", "mixed"):
        window = await _common_window(db, ticker, f, months, invoked_by)

    operands, used_instead = [], {}
    for i in f.inputs:
        got = await _operand(db, ticker, i, months, at, cache, invoked_by, window)
        if got.get("error"):
            # A named alternative answers the same question with a different
            # reported quantity. Which one was used goes into the definition, so
            # the substitution is on the page rather than in the code.
            for alt in f.alternatives.get(i, ()):
                trial = await _operand(db, ticker, alt, months, at, cache, invoked_by, window)
                if not trial.get("error"):
                    got, used_instead[i] = trial, alt
                    break
        if got.get("error"):
            # A nested formula reports the deepest cause, not its own name: an
            # EBITDA that says "missing: ebit" tells the reader nothing they can
            # act on.
            deepest = got.get("missing") if got.get("error") == "input_unavailable" else i
            return {"error": "input_unavailable", "formula": name,
                    "missing": deepest or i,
                    "detail": got.get("detail") or got.get("error"),
                    "definition": f.expression}
        operands.append(got)

    if f.op == "sum":
        acc = operands[0]
        for nxt in operands[1:]:
            step = await tc.calculate(db, "add", acc["id"], nxt["id"], invoked_by=invoked_by)
            if step.get("error"):
                return {"error": "not_combinable", "formula": name,
                        "detail": step["detail"], "definition": f.expression}
            acc = {"id": step["calc_id"], "value": step["value"], "basis": step["basis"]}
    elif f.op == "difference":
        acc = operands[0]
        for nxt, sign in zip(operands[1:], f.signs[1:]):
            step = await tc.calculate(db, "add" if sign > 0 else "subtract",
                                      acc["id"], nxt["id"], invoked_by=invoked_by)
            if step.get("error"):
                return {"error": "not_combinable", "formula": name,
                        "detail": step["detail"], "definition": f.expression}
            acc = {"id": step["calc_id"], "value": step["value"], "basis": step["basis"]}
    else:  # divide
        step = await tc.calculate(db, "divide", operands[0]["id"], operands[1]["id"],
                                  invoked_by=invoked_by)
        if step.get("error"):
            return {"error": "not_combinable", "formula": name,
                    "detail": step["detail"], "definition": f.expression}
        acc = {"id": step["calc_id"], "value": step["value"], "basis": step["basis"]}
        if name in fm.DAYS_FORMULAS:
            acc = {"id": acc["id"], "value": acc["value"] * DAYS_IN_YEAR,
                   "basis": acc["basis"], "scaled": DAYS_IN_YEAR}

    definition = f.expression
    for wanted, actual in used_instead.items():
        definition += f" [{actual.replace('_', ' ')} used for {wanted.replace('_', ' ')}]"
    out = {"formula": name, "ticker": ticker, "value": acc["value"],
           "calc_id": acc["id"], "definition": definition, "basis": acc["basis"],
           "source_url": f.source_url, "note": f.note, "unit_class": f.unit_class}
    if used_instead:
        out["substituted_inputs"] = used_instead
    if acc.get("scaled"):
        out["definition"] = f"{f.expression} (the ratio's calc_id is before the × 365)"
    return out


async def build_panel(db: AsyncSession, ticker: str, *, months: int = 12,
                      at: str | None = None, invoked_by: str = "agent") -> dict:
    """Every formula in the registry, evaluated once. No logic of its own."""
    ticker = ticker.upper()
    refusal = await _bank_refusal(db, ticker)
    if refusal:
        return refusal

    lines: dict[str, dict] = {}
    for name in ("total_debt",) + fm.evaluation_order():
        if name in lines:
            continue
        lines[name] = await evaluate_formula(db, ticker, name, months=months, at=at,
                                             invoked_by=invoked_by)
    return {
        "ticker": ticker,
        "judgement": ("none: these are measured values with their definitions and period "
                      "bases. Thresholds and conclusions are the reader's."),
        "lines": lines,
    }
