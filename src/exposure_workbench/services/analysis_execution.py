"""`analyze`: one intent, executed as a table — the mechanical work the model used to schedule.

The Q07 live runs showed the lead reading twelve cells one call at a time, pairing
numerators and denominators by hand, subtracting the pairs it had matched and
ranking what it had subtracted — eleven calls to express one request: "cash
conversion for these names, latest twelve months against the comparable twelve
months before, ranked". This module takes that request and does the rest:

    bind the scope        services/scope: the subjects, their book, its two runs
    bind the periods      services/period_semantics: each issuer's own calendar
    read every cell       formula_service / fundamentals_service / book_columns
    change                typed_calculator.change, with its kind stated
    rank                  a VIEW over the cells: places and ties, never a new fact
    record                every cell a Fact; the table a manifest on the ledger

What comes back is an AnalysisView: the aligned table with each cell's display,
period and id, the orderings, what is missing and why, and the scope's status.
The model reads it and writes; it is never asked for a date, a cell, an operand
or a join key. Nothing here decides which measure matters or what the table
means — that is the model's, and the registry's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Collection

from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.analytics import formulas as fm
from exposure_workbench.analytics import registry
from exposure_workbench.analytics import value_semantics as vs
from exposure_workbench.services import book_columns, calc_service as cs, compute_service, facts as F
from exposure_workbench.services import formula_service, fundamentals_service, method_index as mi
from exposure_workbench.services import period_semantics as ps, scope as scope_svc
from exposure_workbench.services import typed_calculator as tc

logger = logging.getLogger(__name__)

OP_TABLE = "analysis.table"          # the manifest's ledger operation
SCHEMA_VERSION = 1
MAX_REQUESTS = 8
MAX_CELLS = 256
DIRECTIONS = ("highest", "lowest")
CHANGE_KINDS = {"absolute": vs.ABSOLUTE_CHANGE, "relative": vs.RELATIVE_CHANGE}
ALL_COMPARES = ps.COMPARES + mi.BOOK_COMPARES


@dataclass(frozen=True)
class Request:
    measure: str
    compare: str | None = None
    rank: bool = False
    direction: str = "highest"
    change: str = "absolute"          # absolute | relative
    params: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out: dict = {"measure": self.measure}
        if self.compare:
            out["compare"] = self.compare
            out["change"] = self.change
        if self.rank:
            out["rank"] = True
            out["direction"] = self.direction
        if self.params:
            out["params"] = self.params
        return out


@dataclass(frozen=True)
class Reading:
    """One cell as read: a value with its identity and the ledger ref the typed
    calculator resolves (a calc_ id, or a run's named figure)."""
    value: float
    unit: str                         # RATIO | MONEY | …
    ref: str
    period: dict                      # {"start","end"} | {"instant"} | {"run","as_of"}
    kind: str = vs.LEVEL
    definition: str = ""
    sources: tuple[str, ...] = ()
    semantic: dict | None = None


@dataclass(frozen=True)
class Missing:
    reason: str
    detail: str


def _err(code: str, detail: str, **more) -> dict:
    return {"error": code, "detail": detail, **more}


def parse_requests(raw: Any, allowed: Collection[str]) -> list[Request] | dict:
    if not isinstance(raw, list) or not raw:
        return _err("invalid_requests", "requests is a non-empty list of {measure, compare?, rank?}")
    if len(raw) > MAX_REQUESTS:
        return _err("too_many_requests", f"at most {MAX_REQUESTS} requests in one analysis; got {len(raw)}")
    out: list[Request] = []
    for i, r in enumerate(raw):
        if not isinstance(r, dict) or not isinstance(r.get("measure"), str):
            return _err("invalid_requests", f"requests[{i}] names no measure")
        measure = r["measure"].strip()
        if measure not in allowed:
            near = registry.nearest(measure)
            return _err("unknown_measure", f"{measure!r} is not a measure this analysis takes",
                        measure=measure, **({"nearest": near} if near else {}))
        compare = r.get("compare") or None
        if compare is not None:
            if compare not in ALL_COMPARES:
                return _err("unknown_compare", f"compare is one of {', '.join(ALL_COMPARES)}; got {compare!r}")
            if compare not in mi.compares_for(measure):
                takes = mi.compares_for(measure)
                return _err("compare_not_applicable",
                            f"{measure} is compared against " + (" | ".join(takes) if takes else "nothing")
                            + f", not {compare}", measure=measure)
        direction = r.get("direction") or "highest"
        if direction not in DIRECTIONS:
            return _err("invalid_requests", f"direction is one of {', '.join(DIRECTIONS)}")
        change = r.get("change") or "absolute"
        if change not in CHANGE_KINDS:
            return _err("invalid_requests", "change is absolute or relative")
        params = r.get("params") if isinstance(r.get("params"), dict) else {}
        out.append(Request(measure=measure, compare=compare, rank=bool(r.get("rank")), direction=direction,
                           change=change, params=params))
    return out


# ── reading one cell ──────────────────────────────────────────────────────────

def _iso(d: date | str | None) -> str | None:
    return d.isoformat() if isinstance(d, date) else d


async def _read_formula(db: AsyncSession, subject: str, measure: str, months: int, at: str | None,
                        invoked_by: str) -> Reading | Missing:
    f = fm.FORMULAS[measure]
    window = None
    if f.basis in ("window", "mixed"):
        window = await formula_service._common_window(db, subject, f, months, invoked_by, ending_at=at)
        if window is None:
            return Missing("window_not_derivable",
                           f"no {months}-month window every input of {measure} reaches for {subject}"
                           + (f" ending at {at}" if at else ""))
    got = await formula_service.evaluate_formula(db, subject, measure, months=months,
                                                 at=at or (window[1] if window else None), invoked_by=invoked_by)
    if got.get("error"):
        return Missing(str(got["error"]), str(got.get("statement") or got.get("detail") or got["error"]))
    period = ({"start": window[0], "end": window[1]} if window
              else {"instant": at} if at else {"instant": _iso(got.get("as_of"))})
    return Reading(value=float(got["value"]), unit=str(got.get("unit_class") or f.unit_class).upper(),
                   ref=got["calc_id"], period=period, definition=str(got.get("definition") or f.expression),
                   sources=(got["calc_id"],))


async def _read_line(db: AsyncSession, subject: str, metric: str, months: int, at: str | None,
                     invoked_by: str) -> Reading | Missing:
    from exposure_workbench.tools import definitions as D
    company = await D._resolve_company(db, subject)
    if company.get("error"):
        return Missing(str(company["error"]), str(company.get("detail") or company["error"]))
    instant = await D._metric_is_instant(db, company["id"], metric)
    if instant is None:
        return Missing("metric_not_filed", f"{subject} files no line under {metric!r}")
    if instant:
        sheet = await fundamentals_service.get_balance_sheet(db, subject, at=at, invoked_by=invoked_by)
        if sheet.get("error"):
            return Missing(str(sheet["error"]), str(sheet.get("detail") or sheet["error"]))
        here = (sheet.get("balances") or {}).get(metric)
        if not here:
            return Missing("not_reported_at_this_date", f"{subject} reports no {metric} at {sheet.get('as_of')}")
        return Reading(value=float(here["value"]), unit=str(here.get("unit_class") or "UNKNOWN"),
                       ref=here["fact_id"], period={"instant": here["as_of"]}, definition=f"{metric}, as filed",
                       sources=(here["fact_id"],))
    got = await fundamentals_service.get_flow(db, subject, metric, months=months, end=at, invoked_by=invoked_by)
    if got.get("error"):
        return Missing(str(got["error"]), str(got.get("statement") or got.get("detail") or got["error"]))
    return Reading(value=float(got["value"]), unit=str(got["unit_class"]), ref=got["calc_id"],
                   period=dict(got["period"]), definition=f"{metric}, as filed ({got.get('derivation')})",
                   sources=(got["calc_id"],))


async def _read_book(db: AsyncSession, subject: str, measure: str, book: str | None, which: str) -> Reading | Missing:
    got = await book_columns.read_column(db, subject, measure.split(".", 1)[1], book=book, which=which)
    if got.get("error"):
        return Missing(str(got["error"]), str(got.get("detail") or got["error"]))
    return Reading(value=float(got["value"]), unit=str(got["unit_class"]), ref=got["ref"],
                   period={"run": got["run_id"], "as_of": got["as_of"]}, definition=str(got.get("basis") or ""),
                   sources=(got["run_id"],))


async def _read_price(db: AsyncSession, subject: str, measure: str, params: dict, invoked_by: str) -> Reading | Missing:
    spec = registry.METHODS[measure]
    got = await compute_service._run_method(db, spec, subject, params, invoked_by)
    if got.get("error"):
        return Missing(str(got["error"]), str(got.get("detail") or got["error"]))
    if not isinstance(got.get("value"), (int, float)):
        return Missing("not_a_figure", f"{measure} yields no single figure for {subject}; ask `metric` for it")
    unit = str(got.get("unit_class") or (got.get("type") or {}).get("unit_class") or spec.unit_class or "RATIO").upper()
    return Reading(value=float(got["value"]), unit=unit, ref=got["calc_id"],
                   period={"instant": _iso(got.get("as_of"))} if got.get("as_of") else {"name": str(got.get("window") or "")},
                   definition=spec.describes, sources=(got["calc_id"],))


def _months_for(compare: str | None) -> int:
    return 3 if compare == "previous_quarter" else 12


async def _current(db: AsyncSession, subject: str, req: Request, sc: scope_svc.Scope, invoked_by: str) -> Reading | Missing:
    fam = mi.family_of(req.measure)
    if fam == "book.column":
        return await _read_book(db, subject, req.measure, sc.book, "latest")
    if fam == "price":
        return await _read_price(db, subject, req.measure, req.params, invoked_by)
    months = _months_for(req.compare)
    at = None
    if req.compare == "previous_fy":
        cal = await ps.fiscal_calendar(db, subject)
        if cal is None or not cal.years:
            return Missing("no_fiscal_calendar", f"{subject} has filed no fiscal year this desk can place")
        at = cal.years[-1].end.isoformat()
    if fam == "formula":
        return await _read_formula(db, subject, req.measure, months, at, invoked_by)
    return await _read_line(db, subject, req.measure, months, at, invoked_by)


async def _baseline(db: AsyncSession, subject: str, req: Request, current: Reading, sc: scope_svc.Scope,
                    invoked_by: str) -> Reading | Missing:
    fam = mi.family_of(req.measure)
    if req.compare == "previous_run":
        if not sc.runs.get("prev"):
            return Missing("no_prior_run", f"{sc.book or 'the book'} has no completed run before {sc.runs.get('latest', {}).get('id')}")
        return await _read_book(db, subject, req.measure, sc.book, "prior")
    end = current.period.get("end") or current.period.get("instant")
    if not end:
        return Missing("no_period", f"the current reading of {req.measure} for {subject} carries no period to compare from")
    prior_end = await ps.comparable_end(db, subject, date.fromisoformat(end), req.compare)
    if prior_end is None:
        return Missing("no_comparable_period",
                       f"{subject}'s filed calendar has no {req.compare.replace('_', ' ')} for the period ending {end}")
    months = _months_for(req.compare)
    if fam == "formula":
        return await _read_formula(db, subject, req.measure, months, prior_end.isoformat(), invoked_by)
    return await _read_line(db, subject, req.measure, months, prior_end.isoformat(), invoked_by)


async def _change(db: AsyncSession, current: Reading, baseline: Reading, kind: str, invoked_by: str) -> Reading | Missing:
    got = await tc.change(db, current.ref, baseline.ref, kind=kind, invoked_by=invoked_by)
    if got.get("error"):
        return Missing(str(got["error"]), str(got.get("detail") or got["error"]))
    # the endpoints' periods are the readings' own: the calculator records the
    # operands' bases, which for a formula is the mixed basis of its inputs
    semantic = vs.Semantics(kind=kind, measure=(got.get(vs.KEY) or {}).get("measure"), current=current.ref,
                            baseline=baseline.ref, current_period=current.period, baseline_period=baseline.period)
    return Reading(value=float(got["value"]), unit=str(got["unit_class"]).upper(), ref=got["calc_id"],
                   period={"from": baseline.period, "to": current.period}, kind=kind,
                   definition=f"{kind.replace('_', ' ')}, {vs.period_words(baseline.period)} to {vs.period_words(current.period)}",
                   sources=(got["calc_id"],), semantic=semantic.as_params())


# ── the view ──────────────────────────────────────────────────────────────────

def _period_words(period: dict) -> str:
    if "from" in period and "to" in period:
        return f"{vs.period_words(period['from'])} → {vs.period_words(period['to'])}"
    return vs.period_words(period) or str(period.get("name") or "")


def _rank(cells: dict[str, Reading | Missing], direction: str) -> dict:
    """Competition ranking over the subjects that have a value: equal values share a
    place. A view, not a fact: nothing new is minted, the places are read off the cells."""
    scored = sorted(((s, r) for s, r in cells.items() if isinstance(r, Reading)),
                    key=lambda sr: sr[1].value, reverse=(direction == "highest"))
    order, ties = [], []
    place = 0
    for i, (subject, r) in enumerate(scored):
        if i and r.value == scored[i - 1][1].value:
            ties.append([scored[i - 1][0], subject])
        else:
            place = i + 1
        order.append({"subject": subject, "place": place, "display": dc.display(r.value, r.unit, r.kind)})
    excluded = [{"subject": s, "reason": m.reason} for s, m in cells.items() if isinstance(m, Missing)]
    return {"direction": direction, "of": len(scored), "order": order, "ties": ties, "excluded": excluded}


def _column(key: str, req: Request, role: str, kind: str, unit: str | None) -> dict:
    words = {"previous_ttm": ("latest twelve months", "same twelve months a year earlier"),
             "previous_fy": ("latest fiscal year", "fiscal year before"),
             "previous_quarter": ("latest fiscal quarter", "quarter before"),
             "previous_run": ("latest run", "run before")}
    name = registry.reads_as(req.measure)
    if role == "current":
        period_words = words[req.compare][0] if req.compare else ("latest" if mi.family_of(req.measure) != "price" else "")
        label = f"{name}, {period_words}" if period_words else name
    elif role == "baseline":
        label = f"{name}, {words[req.compare][1]}"
    else:
        pp = kind == vs.ABSOLUTE_CHANGE and unit in ("RATIO", "PERCENT")
        label = f"{name}, {req.change} change" + (" (pp)" if pp else "") + f" vs {words[req.compare][1]}"
    return {"key": key, "measure": req.measure, "role": role, "kind": kind, "unit": unit, "label": label}


async def analyze(db: AsyncSession, *, scope: dict | None, requests: Any, allowed_measures: Collection[str],
                  invoked_by: str = "agent") -> dict:
    """The entry the `analyze` tool wraps. Returns the AnalysisView with its facts under
    `_facts` (the adapter records them and strips the key), or a refusal."""
    reqs = parse_requests(requests, allowed_measures)
    if isinstance(reqs, dict):
        return reqs
    sc = await scope_svc.bind(db, scope)
    if isinstance(sc, dict):
        return sc
    cells_needed = sum((3 if r.compare else 1) for r in reqs) * len(sc.subjects)
    if cells_needed > MAX_CELLS:
        return _err("too_many_cells", f"{cells_needed} cells; one analysis reads at most {MAX_CELLS} — fewer subjects, "
                                      f"fewer measures, or split it")

    columns: list[dict] = []
    table: dict[str, dict[str, Reading | Missing]] = {s: {} for s in sc.subjects}
    ranks: dict[str, dict] = {}
    definitions: dict[str, str] = {}
    for req in reqs:
        cur_key = req.measure
        base_key, chg_key = f"{req.measure}@baseline", f"{req.measure}.change"
        kind = CHANGE_KINDS[req.change]
        unit_seen: str | None = None
        for subject in sc.subjects:
            cur = await _current(db, subject, req, sc, invoked_by)
            table[subject][cur_key] = cur
            if isinstance(cur, Reading):
                unit_seen = unit_seen or cur.unit
                definitions.setdefault(req.measure, cur.definition)
            if not req.compare:
                continue
            if isinstance(cur, Missing):
                table[subject][base_key] = Missing("no_current", "no current reading to compare against")
                table[subject][chg_key] = Missing("no_current", "no current reading to compare against")
                continue
            base = await _baseline(db, subject, req, cur, sc, invoked_by)
            table[subject][base_key] = base
            if isinstance(base, Missing):
                table[subject][chg_key] = Missing(base.reason, base.detail)
                continue
            table[subject][chg_key] = await _change(db, cur, base, kind, invoked_by)
        columns.append(_column(cur_key, req, "current", vs.LEVEL, unit_seen))
        if req.compare:
            columns.append(_column(base_key, req, "baseline", vs.LEVEL, unit_seen))
            chg_unit = "RATIO" if kind == vs.RELATIVE_CHANGE else unit_seen
            columns.append(_column(chg_key, req, "change", kind, chg_unit))
        if req.rank:
            ranks[cur_key] = _rank({s: table[s][cur_key] for s in sc.subjects}, req.direction)
            if req.compare:
                ranks[chg_key] = _rank({s: table[s][chg_key] for s in sc.subjects}, req.direction)

    # the facts: one per cell read, every one openable by id, with its kind stated
    facts: dict[tuple[str, str], F.Fact] = {}
    for subject, cells in table.items():
        for key, r in cells.items():
            if not isinstance(r, Reading):
                continue
            col = next(c for c in columns if c["key"] == key)
            name = f"{col['measure']}.{r.kind}" if col["role"] == "change" else col["measure"]
            params: dict = {"role": col["role"], vs.KEY: (r.semantic or vs.Semantics().as_params())}
            if col["role"] == "change":
                params["compare"] = next(rq.compare for rq in reqs if rq.measure == col["measure"])
            window = ({"start": r.period["start"], "end": r.period["end"]} if r.period.get("start") else None)
            as_of = (r.period.get("end") or r.period.get("instant") or r.period.get("as_of")
                     or (r.period.get("to") or {}).get("end") or (r.period.get("to") or {}).get("as_of"))
            group = "book_derived" if mi.family_of(col["measure"]) == "book.column" else \
                "price" if mi.family_of(col["measure"]) == "price" else \
                "fundamentals" if mi.family_of(col["measure"]) == mi.FILED_LINE else "derived"
            facts[(subject, key)] = F.fact(F.SCALAR, name, subject=subject, unit=r.unit, value=r.value,
                                           as_of=as_of, window=window, params=params, sources=r.sources, group=group)

    rows_manifest = [{"subject": s, "cells": {k: facts[(s, k)].id for k in cells if (s, k) in facts}}
                     for s, cells in table.items()]
    missing = [{"subject": s, "column": k, "reason": m.reason, "detail": m.detail}
               for s, cells in table.items() for k, m in cells.items() if isinstance(m, Missing)]
    manifest_id = await cs._record(
        db, None, OP_TABLE,
        {"schema_version": SCHEMA_VERSION, "scope": sc.as_dict(), "requests": [r.as_dict() for r in reqs],
         "columns": columns, "rows": rows_manifest, "ranks": ranks, "missing": missing,
         "result_type": {"kind": "table", "quantity": OP_TABLE}},
        {"kind": "table", "rows": len(rows_manifest), "cells": len(facts)},
        sorted({ref for f in facts.values() for ref in f.sources}), {}, invoked_by)
    facts = {k: replace(f, params={**f.params, "view": manifest_id}) for k, f in facts.items()}

    complete = [s for s, cells in table.items() if all(isinstance(r, Reading) for r in cells.values())]
    limitations: list[str] = []
    if sc.status == scope_svc.MISMATCH:
        limitations.append(f"scope: {sc.expected_count} subjects were expected, {sc.resolved_count} resolved "
                           f"({sc.basis}); the table covers the {sc.resolved_count}")
    for m in missing:
        limitations.append(f"{m['subject']}, {m['column']}: {m['detail']}")
    view = {
        "view": manifest_id,
        "scope": sc.as_dict(),
        "requests": [r.as_dict() for r in reqs],
        "columns": columns,
        "rows": [{"subject": s, **({"sector": sc.sectors[s]} if sc.sectors.get(s) else {}),
                  "cells": {k: ({"display": dc.display(r.value, r.unit, r.kind), "value": r.value,
                                 "period": _period_words(r.period), "ref": facts[(s, k)].id}
                                if isinstance(r, Reading) else {"missing": r.reason})
                            for k, r in cells.items()}}
                 for s, cells in table.items()],
        "ranks": ranks,
        "missing": missing,
        "coverage": {"subjects": sc.resolved_count, "subjects_complete": len(complete), "cells": len(facts),
                     "scope_status": sc.status},
        "definitions": definitions,
        "limitations": limitations,
        "_facts": [F.for_record(f) for f in facts.values()],
    }
    return view
