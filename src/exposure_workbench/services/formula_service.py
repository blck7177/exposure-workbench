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
from exposure_workbench.services import absence_service as ab
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


_BANK_REASON = ("these are non-financial credit measures and they do not apply to a "
                "financial issuer: interest expense is an operating cost for a bank, so "
                "coverage and leverage built on adding it back describe nothing")


async def _bank_refusal(db: AsyncSession, ticker: str, name: str | None = None,
                        invoked_by: str = "agent") -> dict | None:
    """Refused for being a bank — with an id, and with the reason kept verbatim.

    V11-A. The reason was already the best sentence any refusal in this codebase
    produced, and the battery caught the agent replacing it with "not applicable
    in this framework because JPM is a Financials issuer" — a tautology that
    explains nothing — while inventing `co_jpm` and `run_?` to satisfy the
    citation gate. Both failures come from the same missing thing: an absence
    with no identity of its own.

    No stand-in is proposed. Which measures DO describe a bank is a claim about
    bank analysis, and manufacturing one here would be exactly the issuer-
    behaviour rule this design refuses to hold.
    """
    sector = await _sector(db, ticker)
    if sector not in FINANCIAL_SECTORS:
        return None
    statement = (f"{name or 'This measure'} is not applicable to {ticker}: " + _BANK_REASON
                 + ". This is a statement about the measure, not about the issuer's "
                   "creditworthiness, and this desk proposes no substitute for it.")
    return await ab.refuse(
        db, "not_applicable", kind="not_applicable", ticker=ticker,
        statement=statement,
        tried={"formula": name, "sector": sector},
        stopped_at={"sector": sector},
        invoked_by=invoked_by,
        sector=sector, detail=_BANK_REASON, **({"formula": name} if name else {}))


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
    # Everything this issuer files, at this date or another one. Without it the
    # cover cannot tell "AAPL has never filed short-term borrowings" from "AAPL
    # files it and not on this instant", and reported both as debt left out.
    ever = frozenset(bs["balances"]) | frozenset(bs.get("not_reported_at_this_date", {}))
    cover = ct.cover(available, family="debt", ever_reported=ever)
    if isinstance(cover, ct.NoCover):
        # Say WHICH date, and where the components were last seen. "no debt
        # component reported at this date" travelled up into debt_to_ebitda's
        # refusal with the date dropped on the way, and read there as if the
        # issuer had no debt at all.
        absent = bs.get("not_reported_at_this_date") or {}
        seen = [absent[m]["last_reported"] for m in ct.FAMILIES["debt"] if m in absent]
        detail = f"{cover.reason} ({bs['as_of']})"
        if seen:
            detail += f"; debt components were last reported at {max(seen)}"
        return {"error": "not_reported", "metric": "total_debt", "detail": detail}

    ids = [bs["balances"][m]["fact_id"] for m in cover.terms]
    running_id, running_value = ids[0], bs["balances"][cover.terms[0]]["value"]
    for term, fid in zip(cover.terms[1:], ids[1:]):
        step = await tc.calculate(db, "add", running_id, fid, invoked_by=invoked_by)
        if step.get("error"):
            return step
        running_id, running_value = step["calc_id"], step["value"]
    return {"id": running_id, "value": running_value,
            "basis": f"as of {bs['as_of']}", "formula": cover.formula,
            "missing_at_this_date": list(cover.missing_at_this_date),
            "no_facts_for_issuer": list(cover.no_facts_for_issuer)}


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


async def _leaf_inputs(f, seen: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """Every reported metric a formula bottoms out in, through nested formulas."""
    out: list[str] = []
    for i in f.inputs:
        if i in seen:
            continue
        nested = fm.FORMULAS.get(i)
        for leaf in (await _leaf_inputs(nested, seen | {i}) if nested else (i,)):
            if leaf not in out:
                out.append(leaf)
    return tuple(out)


async def _unavailable(db: AsyncSession, ticker: str, name: str, f, missing: str,
                       detail: str, months: int, invoked_by: str,
                       cache: dict | None = None) -> dict:
    """An input this desk cannot supply, said in terms of what it does hold.

    The battery's two worst refusals were both this one, and both moved the gap
    from our coverage onto the issuer: LLY files capex every quarter under a tag
    the mapping has not learned, and MSFT files depreciation every quarter and
    simply not the combined line EBITDA needs. Neither sentence was ours — the
    payload named the missing input and nothing else, so the model wrote its own.
    """
    # ebitda and debt_to_ebitda fail on the same missing input for the same
    # reason. Minting a row per dependent would put three ids on one fact and
    # repeat its paragraph three times in a panel; they share one.
    shared = None if cache is None else cache.get(("_absence", missing))
    if shared is not None:
        return {**shared, "formula": name, "definition": f.expression,
                "authority": fm.authority(f)}

    leaves = await _leaf_inputs(f)
    covers = await ab.coverage(db, ticker, leaves)
    alts = ab.superseded_by(missing)
    latest = await ab.issuer_latest(db, ticker)

    held = [f"{m} through {c['through']}" for m, c in covers.items() if c]
    if missing in fm.FORMULAS:
        # A COMPOSED input — total_debt is assembled by containment cover and is
        # never a filed line — so coverage() has nothing to say about it, and its
        # absence is whatever its own producer said, scoped as the producer
        # scoped it. This case used to fall through to the branch below, and
        # "this desk holds no total_debt for AAPL at any date" went out over an
        # issuer whose total debt is 84.7B at the last date it filed: the
        # coverage table had no row for a name that is not a metric, and the
        # sentence read a missing row as a missing fact. The model transcribed
        # it faithfully, which is what V11 asked of it.
        why = f"{missing} could not be assembled: {detail}"
    elif covers.get(missing) is None:
        why = (f"this desk holds no {missing} for {ticker} at any date"
               + (f", and no {' or '.join(alts)} either" if alts else ""))
    else:
        why = (f"{ticker}'s {missing} runs through {covers[missing]['through']}, and "
               f"{name} needs every input over one shared window")
    statement = (f"{name} cannot be produced for {ticker}: {why}. "
                 + (f"What this desk does hold: {'; '.join(held)}. " if held else "")
                 + (f"{ticker}'s most recent filed period ends {latest}. " if latest else "")
                 + "This is a statement about this desk's coverage, not a statement "
                   "that the issuer does not disclose the item.")
    out = await ab.refuse(
        db, "input_unavailable", kind="input_unavailable", ticker=ticker,
        statement=statement,
        tried={"formula": name, "months": months, "definition": f.expression},
        stopped_at={"input": missing, "detail": detail,
                    "coverage": covers.get(missing)},
        neighbours={"input_coverage": covers, "superseded_by": list(alts),
                    "issuer_latest_period_end": latest},
        invoked_by=invoked_by,
        formula=name, missing=missing, detail=detail,
        definition=f.expression, authority=fm.authority(f),
    )
    if cache is not None:
        cache[("_absence", missing)] = out
    return out


async def evaluate_formula(db: AsyncSession, ticker: str, name: str, *,
                           months: int = 12, at: str | None = None,
                           invoked_by: str = "agent", _cache: dict | None = None,
                           _window: tuple[str, str] | None = None) -> dict:
    """One named measure, built from the primitives an agent could call itself."""
    ticker = ticker.upper()
    if name not in fm.FORMULAS and name != "total_debt":
        return {"error": "unknown_formula", "formula": name,
                "known": sorted(fm.FORMULAS)}
    refusal = await _bank_refusal(db, ticker, name, invoked_by)
    if refusal:
        return refusal

    cache = _cache if _cache is not None else {}
    if name == "total_debt":
        got = await _total_debt(db, ticker, at, invoked_by)
        if got.get("error"):
            return got
        f = fm.FORMULAS["total_debt"]
        out = {"formula": name, "ticker": ticker, "value": got["value"],
               "calc_id": got["id"], "definition": got.get("formula", f.expression),
               "basis": got["basis"], "authority": fm.authority(f), "note": f.note,
               "unit_class": f.unit_class}
        # Only when there is something to say. An empty list beside every total
        # invites a sentence about what was left out when nothing was.
        for key in ("missing_at_this_date", "no_facts_for_issuer"):
            if got.get(key):
                out[key] = got[key]
        return out

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
            return await _unavailable(db, ticker, name, f, deepest or i,
                                      got.get("detail") or got.get("error"),
                                      months, invoked_by, cache)
        operands.append(got)

    if f.op == "sum":
        acc = operands[0]
        for nxt in operands[1:]:
            step = await tc.calculate(db, "add", acc["id"], nxt["id"], invoked_by=invoked_by)
            if step.get("error"):
                return {"error": "not_combinable", "formula": name,
                        "detail": step["detail"], "definition": f.expression,
                    "authority": fm.authority(f)}
            acc = {"id": step["calc_id"], "value": step["value"], "basis": step["basis"]}
    elif f.op == "difference":
        acc = operands[0]
        for nxt, sign in zip(operands[1:], f.signs[1:]):
            step = await tc.calculate(db, "add" if sign > 0 else "subtract",
                                      acc["id"], nxt["id"], invoked_by=invoked_by)
            if step.get("error"):
                return {"error": "not_combinable", "formula": name,
                        "detail": step["detail"], "definition": f.expression,
                    "authority": fm.authority(f)}
            acc = {"id": step["calc_id"], "value": step["value"], "basis": step["basis"]}
    else:  # divide
        step = await tc.calculate(db, "divide", operands[0]["id"], operands[1]["id"],
                                  invoked_by=invoked_by)
        if step.get("error"):
            return {"error": "not_combinable", "formula": name,
                    "detail": step["detail"], "definition": f.expression,
                    "authority": fm.authority(f)}
        acc = {"id": step["calc_id"], "value": step["value"], "basis": step["basis"]}
        if name in fm.DAYS_FORMULAS:
            # The x365 gets its own ledger row. Doing it here in Python was the
            # first version, and it published a number no evidence could support:
            # the panel printed 143.67 days beside a calc_id holding 0.3936.
            scaled = await tc.scale(db, acc["id"], DAYS_IN_YEAR,
                                    unit_class=tc.COUNT, quantity=name,
                                    invoked_by=invoked_by)
            if scaled.get("error"):
                return {"error": "not_combinable", "formula": name,
                        "detail": scaled["detail"], "definition": f.expression,
                    "authority": fm.authority(f)}
            acc = {"id": scaled["calc_id"], "value": scaled["value"],
                   "basis": acc["basis"]}

    definition = f.expression
    for wanted, actual in used_instead.items():
        definition += f" [{actual.replace('_', ' ')} used for {wanted.replace('_', ' ')}]"
    out = {"formula": name, "ticker": ticker, "value": acc["value"],
           "calc_id": acc["id"], "definition": definition, "basis": acc["basis"],
           "authority": fm.authority(f), "note": f.note, "unit_class": f.unit_class}
    if used_instead:
        out["substituted_inputs"] = used_instead
    return out


_REGISTRY_PROSE = ("note", "authority")


async def build_panel(db: AsyncSession, ticker: str, *, months: int = 12,
                      at: str | None = None, invoked_by: str = "agent") -> dict:
    """Every formula in the registry, evaluated once. No logic of its own."""
    ticker = ticker.upper()
    refusal = await _bank_refusal(db, ticker, "this panel", invoked_by)
    if refusal:
        return refusal

    lines: dict[str, dict] = {}
    shared: dict = {}
    seen_absences: set[str] = set()
    for name in ("total_debt",) + fm.evaluation_order():
        if name in lines:
            continue
        line = await evaluate_formula(db, ticker, name, months=months, at=at,
                                      invoked_by=invoked_by, _cache=shared)
        # Formulas that fail on the same input share one absence row, so the
        # paragraph explaining it belongs on the page once. The id stays on every
        # line that has it: that is what says they are the same fact.
        aid = line.get("absence_id")
        if aid is not None:
            if aid in seen_absences:
                line = {k: v for k, v in line.items() if k != "statement"}
            seen_absences.add(aid)
        # `note` and `authority` are registry prose: the same bytes for every
        # issuer on every call, and 2.0kB of the 8.2kB NVDA panel. Shipping them
        # sixteen times pushed the payload past the context cap and silently cost
        # the model four whole lines, net_debt among them. What varies per issuer
        # — the value, the period, which input was substituted — stays; the
        # invariant prose is one evaluate_formula call away.
        lines[name] = {k: v for k, v in line.items() if k not in _REGISTRY_PROSE}
    return {
        "ticker": ticker,
        "judgement": ("none: these are measured values with their definitions and period "
                      "bases. Thresholds and conclusions are the reader's."),
        "per_formula_sources": ("call evaluate_formula(name=...) for a formula's source url "
                                "and its caveats"),
        "lines": lines,
    }
