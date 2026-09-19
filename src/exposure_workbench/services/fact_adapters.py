"""Fact adapters (V24): the one place a tool's payload becomes Facts.

Each tool has an adapter `(args, result) -> (facts, note)`. The adapter knows
its tool's payload; it turns every figure in it into a Fact with the identity
the payload carries (what, whose, unit, as of, window, sources) and returns the
NOTE — the payload with each figure replaced by its fact id — so the model
reads structure in the note and values in the facts, once each.

THE INVARIANTS the tests pin (tests/test_fact_adapters.py):
  I1  no numeric leaf survives in the note — a number reaches the model only
      as a Fact. No allowlist: a number the model must not see is REMOVED here
      (a retrieval score, a character span), never left as a bare leaf.
  I2  every Fact carries `as_of` or `window`, except a task.
  I3  every Fact's unit is declared: a numeric key with no unit is an error
      naming the key, raised here, not a guess.

HOW. One walker (`_harvest`) knows five payload shapes — the shapes the
services actually return, read off the phase-0 fixtures — and a context per
tool says what the walker cannot see in the payload: the subject, the as-of,
the row the figures rest on, the group. Per-tool code is the context plus the
handful of fields that are not figures but identity (a window, a benchmark,
a scenario's inputs).

    absence      {absence_id, statement}                -> one ABSENCE
    series       {calc_id?, points: [{period_end|end|as_of, value, fact_ids?}]}  -> one SERIES
    typed figure {value, calc_id|fact_id|ref, quantity|label?, unit_class?, as_of?} -> one SCALAR
    row table    [ {label column, numeric columns…}, … ] -> one SCALAR per numeric column per row,
                 the label the subject, the measure `<table>.<column>` in the run's own table names
    bare leaf    a number under a key                   -> one SCALAR, measure = the dotted path

Units come from the desk's own declarations (analytics/resources: a column's
unit) plus the short table below for the keys those declarations do not
cover — service outputs that are not run children. Adding a numeric key to a
service means adding its unit here, and I3 says so at the first test.
"""

from __future__ import annotations

import copy
import contextvars
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from exposure_workbench.analytics import registry
from exposure_workbench.analytics import resources as rs
from exposure_workbench.analytics import skill
from exposure_workbench.services import facts as F
from exposure_workbench.utils import json as ejson

logger = logging.getLogger(__name__)

# ── units ─────────────────────────────────────────────────────────────────────

MONEY, RATIO, COUNT, MULTIPLE, MONEY_PER_SHARE = "MONEY", "RATIO", "COUNT", "MULTIPLE", "MONEY_PER_SHARE"

_DECLARED_UNITS: dict[str, str] = {}
for _r in rs.RUN_CHILDREN:
    for _c in _r.columns:
        _DECLARED_UNITS.setdefault(_c.name, _c.unit)

# Keys the run declarations do not cover: service outputs about the book, a
# scenario, a reconciliation, a price statistic, a catalogue count.
UNIT_BY_KEY: dict[str, str] = {
    **_DECLARED_UNITS,
    # money
    # How many figures a set statistic rested on (typed_calculator._fold, V25) —
    # a count, declared here because V25's set statistics were used ZERO times in
    # the 102-turn battery that followed them, so this leaf had never met the
    # adapter until V28 opened the route (the third payload of this shape).
    "entries": COUNT,
    "proceeds": MONEY, "market_value_sold": MONEY, "value_then": MONEY, "market_value": MONEY,
    # ratios
    "depth": RATIO, "gap": RATIO, "tolerance": RATIO, "difference": RATIO, "factor_share": RATIO,
    "unexplained_share": RATIO, "room_to_warning": RATIO,
    "room_to_breach": RATIO, "current": RATIO,
    # A BETA IS A MULTIPLE wherever it sits (V1). The net and gross betas are
    # declared once, in resources.CALC_RESULTS, and read from there: this list
    # said RATIO after that one said MULTIPLE, and the smoke read a credit beta
    # of −0.24 as "-23.9%". A leg signed for its risk is the same beta with the
    # risk's sense applied.
    **{k: v for k, v in rs.CALC_RESULTS["portfolio.integration"].items() if k in ("net_beta", "gross_beta")},
    "signed_for_this_risk": MULTIPLE,
    "sum_of_contributions": RATIO, "sum_of_factor_contributions": RATIO, "alpha_plus_residual": RATIO,
    "recorded_alpha_plus_residual": RATIO, "reported_floor": RATIO, "fraction": RATIO,
    "deepest_depth": RATIO,
    # counts
    "count": COUNT, "total_holdings": COUNT, "quantity": COUNT, "sessions": COUNT, "sessions_behind": COUNT,
    "runs_in_flight": COUNT, "checks_run": COUNT, "checks_clear": COUNT, "evaluated": COUNT, "fired": COUNT,
    "clear": COUNT, "terms": COUNT, "n": COUNT, "unmatched_points": COUNT, "trough_days": COUNT,
    "recovery_days": COUNT, "skipped_recent_sessions": COUNT, "positions": COUNT, "alerts": COUNT,
    "metrics": COUNT, "passages": COUNT, "flow": COUNT, "instant": COUNT, "methods_computable": COUNT,
    "periods_without_comparable_prior": COUNT, "runs": COUNT, "filings": COUNT, "limits": COUNT,
    "holdings": COUNT, "checks": COUNT, "names": COUNT, "periods": COUNT,
}

# Keys whose unit is NOT a property of the name. They carry the unit of whatever
# was ranked, subtracted or compared, so the producer's declaration decides and
# a key list cannot: `rank`'s spread is max − min of the ranked measure, MONEY
# when market values are ranked. Pinned to RATIO until V29, it rendered a
# $1,135,470 spread to the reader as "113547000.0%" — the fourth time this batch
# that a consumer-side guess overruled a producer that knew.
POLYMORPHIC_KEYS = frozenset({"spread", "difference", "gap"})

# A key whose name is the tool's, not the reader's.
MEASURE_ALIAS = {"n": "observations"}

# Numbers that are not figures for the model: removed from the note, never a
# Fact. A retrieval score ranks passages for the tool; a character span
# locates a passage in a file. Neither is something an answer states.
DROP_KEYS = frozenset({"score", "char_span"})

# Structures that are not the tool's figures at all — a refusal's schema for the
# params it wanted, its list of problems, the names it knows — kept in the note
# verbatim. The first live V24 round hit `minItems` inside `params_schema` and
# the refusal the model needed became an adapter error.
# `quality_flags` is diagnostics the resolver already excludes from a row's
# figures (typed_calculator._is_single_valued), so the adapter walking it for
# figures was the adapter doing the producer's job: `unmatched_periods` lives
# under it, is in none of the five key tables, and raised UnknownUnit — which
# discarded every figure in the result. V31 §4.3.
PASSTHROUGH_KEYS = frozenset({"params_schema", "problems", "known", "nearest", "available", "held_on",
                              "expected", "supported", "allowed", "quality_flags"})

# Numbers that are identity, not figures: kept in the note as they are (they
# are parameters the model may write, and G3 resolves them from the Fact's
# window/params), and copied onto the Facts they qualify.
PARAM_KEYS = frozenset({"months", "window_days", "days", "factor", "rank", "sign", "k", "last_n"})

# A row's label column, by preference. `entity_id` qualifies an alert's type.
LABEL_KEYS = ("ticker", "label", "check", "factor_name", "sector", "limit_type", "alert_type", "metric", "formula")

# Section names as the tools spell them -> the run's own table names, so a
# weight read through read_book(port, positions) is the same measure as one
# read by name (`issuer_exposures.weight`), and G3's name lookup has one
# spelling per figure.
MEASURE_TABLE = {
    "positions": "issuer_exposures", "holdings": "issuer_exposures", "factors": "factor_attributions",
    "alerts": "risk_alerts", "limit_checks": "limit_checks", "headroom": "limit_checks",
    "limits": "limit_checks", "sectors": "sector_exposures", "metrics": "exposure_metrics",
    "metadata": "exposure_metrics",
}

_ID_PREFIXES = ("fact_", "calc_", "chunk_", "src_", "run_", "alert_", "pos_", "task_", "rrun_")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


class UnknownUnit(ValueError):
    """A numeric key the adapters have no unit for (I3)."""


# The untyped leaves of the adapt() call in flight. A ContextVar rather than a
# parameter because every adapter builds its own Ctx and none of them should
# have to carry a channel they do not use.
_UNTYPED: contextvars.ContextVar[list | None] = contextvars.ContextVar("fact_adapters_untyped", default=None)


def _untyped_leaf(key: str, exc: "UnknownUnit") -> str:
    """A numeric leaf the desk cannot name a unit for: it does not become a
    Fact, and it does not stay a number either.

    I1 holds — no number reaches the model without an identity — and so does
    the reason the raise existed: nothing is guessed. What changes is the
    blast radius. `compute` raised UnknownUnit on `unmatched_periods` and the
    wrapper turned the whole result into `fact_adapter_error`, discarding every
    figure that HAD typed: three times in 191 baseline turns, and once in
    L02-days-arent-price t1 where the model had asked for one honest `abs`.
    The producer knows what its numbers are; when the adapter does not, that is
    the adapter's failure on ONE key, and it fails there. V31 §4.3.
    """
    seen = _UNTYPED.get()
    if seen is not None and not any(u["key"] == key for u in seen):
        seen.append({"key": key, "reason": str(exc)})
    # Still loud, in the place loudness costs nothing: the desk's log. The
    # producer's missing declaration is a defect to fix, and the raise was how
    # V28 and V29 found four of them; what it must not go on doing is billing
    # the model for it.
    logger.warning("untyped numeric leaf %r: %s", key, exc)
    return f"untyped:{key}"


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_id(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(_ID_PREFIXES)


@dataclass
class Ctx:
    tool: str
    subject: str | None = None
    as_of: str | None = None
    window: dict | None = None
    sources: tuple[str, ...] = ()
    group: str = "other"
    params: dict = field(default_factory=dict)
    table: str | None = None       # the run table the current rows belong to
    standalone: bool = True
    default_unit: str | None = None   # the unit a result declared for its figures (rank's `type`)
    # V28 C2: a container that says `numeric_unit` declares the unit of every
    # numeric leaf beneath it — the producer's declaration, read before the
    # consumer-side key list. A catalogue's structural counts arrive this way.
    leaf_unit: str | None = None
    # V1: the registry words said beside the figures being walked — a check's
    # `status`, a net exposure's `direction`, a collinear row — so the Fact
    # carries what the service computed (analytics/registry.words_beside).
    means: dict = field(default_factory=dict)

    def child(self, **changes) -> "Ctx":
        return replace(self, **changes)


# ── the walker ────────────────────────────────────────────────────────────────

def _unit_for(key: str, ctx: Ctx, obj: dict | None = None) -> str:
    if obj and isinstance(obj.get("unit_class"), str):
        return obj["unit_class"].upper()
    if ctx.table:
        declared = rs.column_unit(ctx.table, key)
        if declared:
            return declared
    if key in POLYMORPHIC_KEYS:
        declared = ctx.default_unit or ctx.leaf_unit
        if declared:
            return declared
        raise UnknownUnit(f"{ctx.tool}: {key!r} carries the unit of what it was computed over "
                          f"(subject {ctx.subject}); the result must declare it in `type.unit_class`")
    unit = UNIT_BY_KEY.get(key) or ctx.leaf_unit or (ctx.default_unit if key in ("value",) else None)
    if unit is None:
        raise UnknownUnit(f"{ctx.tool}: no unit declared for numeric key {key!r} (subject {ctx.subject}); "
                          f"add it to fact_adapters.UNIT_BY_KEY or remove it from the payload")
    return unit


def _period_of(p: dict) -> str | None:
    for k in ("period_end", "end", "as_of", "date", "period"):
        v = p.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _as_of_of(obj: dict, ctx: Ctx) -> str | None:
    for k in ("as_of", "period_end", "to", "valued_as_of", "run_as_of", "high_date", "latest_period_end",
              "catalogue_as_of"):
        v = obj.get(k)
        if isinstance(v, str) and _DATE.match(v):
            return v
    w = _window_of(obj, None)
    if w and w.get("end"):
        return w["end"]
    if w and w.get("instant"):
        return w["instant"]
    per = obj.get("period") or obj.get("window") or obj.get("formation")
    if isinstance(per, dict):
        for k in ("end", "to"):
            if isinstance(per.get(k), str):
                return per[k]
    iv = obj.get("interval")
    if isinstance(iv, list) and len(iv) == 2 and isinstance(iv[1], str):
        return iv[1]
    return ctx.as_of


def _window_of(obj: dict, ctx: Ctx | None) -> dict | None:
    # the typed calculator's periods: {instants: [...], intervals: [[s, e], ...]}
    # and a result's declared basis {interval: [s, e]} | {instant: d} | {leaves: {...}}
    for holder in (obj.get("periods"), (obj.get("type") or {}).get("basis") if isinstance(obj.get("type"), dict) else None):
        if isinstance(holder, dict):
            leaves = holder.get("leaves") if isinstance(holder.get("leaves"), dict) else holder
            iv = leaves.get("intervals") or ([leaves["interval"]] if isinstance(leaves.get("interval"), list) else [])
            ins = leaves.get("instants") or ([leaves["instant"]] if isinstance(leaves.get("instant"), str) else [])
            # THE ROW STATES THE PERIOD IT HAS — both of them, when it has two. The
            # calculator records every leaf's period; this took the last and dropped the
            # rest, so 30-day volatility over 252-day volatility read as a figure "for
            # 2026-07-30 to 2026-09-10" (V1 smoke), and a balance's change between two
            # dates read "as of" the later one.
            spans = sorted({(str(x[0]), str(x[1])) for x in iv if isinstance(x, list) and len(x) == 2})
            if len(spans) > 1:
                return {"mixed": " and ".join(f"{s} to {e}" for s, e in spans)}
            dates = sorted({str(d) for d in ins})
            if not spans and len(dates) > 1:
                return {"start": dates[0], "end": dates[-1]}
            if iv and isinstance(iv[-1], list) and len(iv[-1]) == 2:
                return {"start": iv[-1][0], "end": iv[-1][1]}
            if ins:
                return {"instant": max(ins)}
    per = obj.get("period")
    if isinstance(per, dict) and per.get("start") and per.get("end"):
        return {"start": per["start"], "end": per["end"]}
    for k in ("window", "formation"):
        w = obj.get(k)
        if isinstance(w, dict) and (w.get("from") or w.get("start")):
            return {"start": w.get("from") or w.get("start"), "end": w.get("to") or w.get("end")}
        if isinstance(w, str) and w:
            return {"name": w}
    iv = obj.get("interval")
    if isinstance(iv, list) and len(iv) == 2:
        return {"start": iv[0], "end": iv[1]}
    if _is_num(obj.get("months")):
        return {"months": obj["months"]}
    if _is_num(obj.get("window_days")):
        return {"days": obj["window_days"]}
    if isinstance(obj.get("from"), str) and isinstance(obj.get("to"), str):
        return {"start": obj["from"], "end": obj["to"]}
    return ctx.window if ctx else None


def _sources_of(obj: dict, ctx: Ctx) -> tuple[str, ...]:
    out = list(ctx.sources)
    for k in ("calc_id", "fact_id", "ref", "cite", "absence_id", "run_id", "chunk_id", "series"):
        v = obj.get(k)
        if _is_id(v) and v not in out:
            out.append(v)
    for k in ("fact_ids", "operands"):
        for v in obj.get(k) or []:
            if _is_id(v) and v not in out:
                out.append(v)
    terms = obj.get("terms")
    for t in (terms if isinstance(terms, list) else []):
        v = t.get("fact_id") if isinstance(t, dict) else None
        if _is_id(v) and v not in out:
            out.append(v)
    return tuple(out)


def _label_of(row: dict) -> str | None:
    for k in LABEL_KEYS:
        v = row.get(k)
        if isinstance(v, str) and v:
            if k == "alert_type" and isinstance(row.get("entity_id"), str):
                return f"{v}:{row['entity_id']}"
            return v
    return None


def _is_dated_row(row: dict) -> bool:
    return any(isinstance(row.get(k), str) and row[k] for k in ("peak_date", "trough_date", "period_end", "as_of", "date"))


def _is_absence(obj: dict) -> bool:
    return isinstance(obj.get("absence_id"), str) and isinstance(obj.get("statement"), str)


def _is_series(obj: dict) -> bool:
    pts = obj.get("points")
    return isinstance(pts, list) and bool(pts) and all(isinstance(p, dict) and _is_num(p.get("value")) for p in pts)


def _is_typed_figure(obj: dict) -> bool:
    return _is_num(obj.get("value")) and any(_is_id(obj.get(k)) for k in ("calc_id", "fact_id", "ref"))


def _measure_name(obj: dict, key: str) -> str:
    for k in ("quantity", "metric", "formula", "label"):
        v = obj.get(k)
        if isinstance(v, str) and v and k != "label":
            return v
    return key


def _harvest(node: Any, key: str, path: str, ctx: Ctx, facts: list[F.Fact]) -> Any:
    """Return the note form of `node` (figures replaced by fact ids), appending Facts."""
    if isinstance(node, dict):
        if _is_absence(node):
            f = F.fact(F.ABSENCE, node.get("metric") or node.get("formula") or node.get("kind") or key,
                       subject=node.get("ticker") or ctx.subject, text=node["statement"],
                       as_of=_as_of_of(node, ctx) or "n/a", params={k: v for k, v in node.items()
                                                                    if k in ("error", "missing", "formula", "metric")},
                       sources=_sources_of(node, ctx), group=ctx.group,
                       means={"reason": registry.reason_of(node.get("error") or "not_held")})
            facts.append(f)
            note = {k: v for k, v in node.items() if k != "statement"}
            note = _harvest(note, key, path, ctx.child(as_of=f.as_of), facts)
            note["fact"] = f.id
            return note
        if _is_series(node):
            unit = node.get("unit_class") or (node.get("type") or {}).get("unit_class") or (ctx.table and None)
            pts = tuple((_period_of(p) or "?", float(p["value"])) for p in node["points"])
            srcs = list(_sources_of(node, ctx))
            for p in node["points"]:
                for fid in p.get("fact_ids") or []:
                    if _is_id(fid) and fid not in srcs:
                        srcs.append(fid)
            measure = _measure_name(node, key)
            f = F.fact(F.SERIES, measure, subject=node.get("ticker") or ctx.subject,
                       unit=(unit.upper() if isinstance(unit, str) else _unit_for(measure.split(".")[-1], ctx)),
                       points=pts, as_of=pts[-1][0] if pts and pts[-1][0] != "?" else _as_of_of(node, ctx),
                       window=_window_of(node, ctx) or {"start": pts[0][0], "end": pts[-1][0]},
                       params={**ctx.params, **_params_of(node, ctx)}, sources=tuple(srcs), group=ctx.group)
            facts.append(f)
            note = {k: v for k, v in node.items() if k not in ("points",)}
            note = _harvest(note, key, path, ctx.child(as_of=f.as_of, window=f.window, sources=f.sources), facts)
            note["fact"] = f.id
            return note
        if _is_typed_figure(node):
            measure = _measure_name(node, key)
            unit = node.get("unit_class")
            f = F.fact(F.SCALAR, measure, subject=node.get("ticker") or ctx.subject,
                       unit=(unit.upper() if isinstance(unit, str) else _unit_for(key if key else measure, ctx, node)),
                       value=float(node["value"]), as_of=_as_of_of(node, ctx), window=_window_of(node, ctx),
                       params={**ctx.params, **_params_of(node, ctx), **_composition_of(node)},
                       standalone=ctx.standalone and node.get("quotable_individually", True) is not False,
                       sources=_sources_of(node, ctx), group=ctx.group,
                       means=registry.merged(ctx.means, registry.words_beside(node)))
            facts.append(f)
            note = {k: v for k, v in node.items() if k != "value"}
            note = _harvest(note, key, path, ctx.child(as_of=f.as_of, window=f.window, sources=f.sources), facts)
            note["fact"] = f.id
            return note
        # a plain object: descend, with what it says about itself as context
        declared = (node.get("type") or {}).get("unit_class") if isinstance(node.get("type"), dict) else node.get("unit_class")
        sub = ctx.child(as_of=_as_of_of(node, ctx), window=_window_of(node, ctx), sources=_sources_of(node, ctx),
                        params={**ctx.params, **_params_of(node, ctx)},
                        standalone=ctx.standalone and node.get("quotable_individually", True) is not False,
                        default_unit=declared.upper() if isinstance(declared, str) else ctx.default_unit,
                        means=registry.merged(ctx.means, registry.words_beside(node)))
        if isinstance(node.get("ticker"), str) and key not in ("brief",):
            sub = sub.child(subject=node["ticker"])
        elif path:
            # the reconciliation's "largest factor contribution −0.75%" did not say WHICH
            # factor: the name sat beside the number as a string, and strings are not rows
            who = next((node[k] for k in ("factor_name", "sector", "check") if isinstance(node.get(k), str) and node[k]), None)
            if who:
                sub = sub.child(subject=who)
        if isinstance(node.get("numeric_unit"), str):
            sub = sub.child(leaf_unit=node["numeric_unit"].upper())
        out: dict = {}
        for k, v in node.items():
            if k in DROP_KEYS:
                continue
            if k in PASSTHROUGH_KEYS:
                out[k] = v
                continue
            if k in MEASURE_TABLE and isinstance(v, (list, dict)):
                out[k] = _harvest(v, k, f"{path}.{k}" if path else k, sub.child(table=MEASURE_TABLE[k]), facts)
            else:
                out[k] = _harvest(v, k, f"{path}.{k}" if path else k, sub, facts)
        return out
    if isinstance(node, list):
        if node and all(isinstance(r, dict) for r in node) and any(_label_of(r) for r in node):
            return [_harvest_row(r, key, path, ctx, facts) for r in node]
        # ROWS THAT ARE DATED ARE ONE MEASURE AT SEVERAL DATES. A book's drawdown episodes came
        # back as "episodes[0] depth" and "episodes[1] depth" — two measures, by their names — and
        # the lead's "the last one took 24 sessions to recover, the one before 13" was refused as
        # a change between two different quantities (V1 live smoke). The index is the list's; the
        # row's own dates say which episode it is, and the row shows them (facts.when_of).
        if node and all(isinstance(r, dict) and _is_dated_row(r) for r in node):
            return [_harvest(r, key, path, ctx, facts) for r in node]
        return [_harvest(v, key, f"{path}[{i}]", ctx, facts) for i, v in enumerate(node)]
    if _is_num(node):
        if key in PARAM_KEYS:
            return node
        measure = f"{ctx.table}.{key}" if ctx.table else MEASURE_ALIAS.get(key, path or key)
        try:
            unit = _unit_for(key, ctx)
        except UnknownUnit as exc:
            return _untyped_leaf(key, exc)
        f = F.fact(F.SCALAR, measure, subject=ctx.subject, unit=unit, value=float(node),
                   as_of=ctx.as_of, window=ctx.window, params=dict(ctx.params), standalone=ctx.standalone,
                   sources=ctx.sources, group=ctx.group, means=registry.for_leaf(key, ctx.means))
        facts.append(f)
        return f.id
    return node


def _harvest_row(row: dict, key: str, path: str, ctx: Ctx, facts: list[F.Fact]) -> dict:
    """One row of a table: its label is the subject of every figure in it."""
    label = _label_of(row)
    sub = ctx.child(subject=label or ctx.subject, as_of=_as_of_of(row, ctx), window=_window_of(row, ctx),
                    sources=_sources_of(row, ctx), params={**ctx.params, **_params_of(row, ctx)},
                    standalone=ctx.standalone and row.get("quotable_individually", True) is not False,
                    means=registry.merged(ctx.means, registry.words_beside(row)))
    out: dict = {}
    for k, v in row.items():
        if k in DROP_KEYS:
            continue
        if k in PASSTHROUGH_KEYS:
            out[k] = v
            continue
        if _is_num(v) and k not in PARAM_KEYS:
            table = ctx.table or MEASURE_TABLE.get(key) or key
            try:
                unit = _unit_for(k, sub.child(table=ctx.table), row)
            except UnknownUnit as exc:
                out[k] = _untyped_leaf(k, exc)
                continue
            f = F.fact(F.SCALAR, f"{table}.{k}", subject=sub.subject, unit=unit,
                       value=float(v), as_of=sub.as_of, window=sub.window, params=dict(sub.params),
                       standalone=sub.standalone, sources=sub.sources, group=ctx.group,
                       means=registry.for_leaf(k, sub.means))
            facts.append(f)
            out[k] = f.id
        else:
            out[k] = _harvest(v, k, f"{path}.{k}", sub, facts)
    return out


def _composition_of(obj: dict) -> dict:
    """What a composed figure was built from — `made_of`, and which filed line stood
    in for which — as the params the row is rendered with (registry.composition_words).
    One rule for a measure asked alone and for the same measure as a line of a panel:
    the panel's total debt said nothing of the substitution its own row was built on."""
    out: dict = {}
    if isinstance(obj.get("made_of"), dict) and obj["made_of"]:
        out["made_of"] = obj["made_of"]
    if isinstance(obj.get("substituted_inputs"), dict) and obj["substituted_inputs"]:
        out["substituted"] = dict(obj["substituted_inputs"])
    return out


def _params_of(obj: dict, ctx: Ctx) -> dict:
    p: dict = {}
    for k in ("benchmark", "rank", "factor", "months", "window_days", "days", "direction", "op",
              "peak_date", "trough_date", "recovery_date", "high_date", "form_type", "item", "fiscal_year",
              "fiscal_quarter", "confidence", "fraction", "scenario"):
        v = obj.get(k)
        if k == "direction" and v in registry.DIRECTION:
            continue          # an exposure's direction is what the figure MEANS (V1), not a parameter of it
        if isinstance(v, (str, int, float)) and not isinstance(v, bool):
            p[k] = v
    return p


def _strip(note: Any, ctx: Ctx) -> Any:
    """Drop the keys the model must not see, at any depth of a note fragment."""
    if isinstance(note, dict):
        return {k: _strip(v, ctx) for k, v in note.items() if k not in DROP_KEYS}
    if isinstance(note, list):
        return [_strip(v, ctx) for v in note]
    return note


def harvest(result: dict, ctx: Ctx) -> tuple[list[F.Fact], dict]:
    facts: list[F.Fact] = []
    note = _harvest(copy.deepcopy(result), "", "", ctx, facts)
    return facts, note


# ── per-tool adapters ─────────────────────────────────────────────────────────

Adapter = Callable[[dict, dict], tuple[list[F.Fact], dict]]


def _ticker(args: dict) -> str | None:
    t = args.get("ticker") or args.get("subject")
    return t.upper() if isinstance(t, str) and not t.startswith(("port_", "run_", "calc_", "task_", "rrun_")) else None


def describe(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    subject = result.get("subject") or args.get("subject")
    as_of = result.get("as_of") or result.get("catalogue_as_of")
    # The catalogue's three kinds of "missing" are one kind of Fact (plan §3):
    # `not_reported` already arrives as an absence row; `not_held` and `cannot`
    # are the catalogue's own sentences — each becomes an absence fact the
    # honest answer can POINT at. Measured before this: the two honest_absence
    # misses of the first battery had no absence fact on their ledger at all.
    facts: list[F.Fact] = []
    r = copy.deepcopy(result)
    for reason in ("not_held", "cannot"):
        entries = r.get(reason)
        if isinstance(entries, dict) and entries:
            pointed: dict = {}
            for key, sentence in entries.items():
                if not isinstance(sentence, str) or not sentence:
                    continue
                f = F.fact(F.ABSENCE, key, subject=subject, text=sentence, as_of=as_of or "n/a",
                           params={"reason": reason}, group="fundamentals" if result.get("kind") == "issuer" else "book_derived")
                facts.append(f)
                pointed[key] = f.id
            r[reason] = pointed
    more, note = harvest(r, Ctx("describe", subject=subject, as_of=as_of,
                                group="fundamentals" if result.get("kind") == "issuer" else "book_derived"))
    facts += more
    # The catalogue's map — names a run holds, methods, procedures — is the note. Its
    # counts and latest values are facts (I1); nothing else in it is a figure.
    note.pop("table_names", None)
    return facts, note


def read_fundamentals(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    if isinstance(result.get("results"), list):
        # one line over several issuers: each entry is its own read, or its own refusal as a row
        facts_all: list[F.Fact] = []
        notes = []
        for r in result["results"]:
            asked = {**args, "ticker": r.get("asked") or r.get("ticker")}
            if r.get("error"):
                facts_all.append(refusal_fact("filings_read", asked, r))
                notes.append({"ticker": asked["ticker"], "error": r.get("error")})
                continue
            fs, n = read_fundamentals(asked, {k: v for k, v in r.items() if k != "asked"})
            facts_all += fs
            notes.append(n)
        return facts_all, {"results": notes}
    tk = result.get("ticker") or _ticker(args)
    ctx = Ctx("read_fundamentals", subject=tk, as_of=result.get("as_of"), group="fundamentals")
    if result.get("error") == "not_reported_at_this_date":
        # last_reported carries the balance at the date it was last reported: a fact
        # of its own, as of THAT date; shares are a count, every other balance money.
        lr = result.get("last_reported") or {}
        facts: list[F.Fact] = []
        note = {k: v for k, v in result.items() if k != "last_reported"}
        if _is_num(lr.get("value_then")) and isinstance(lr.get("last_reported"), str):
            f = F.fact(F.SCALAR, result.get("metric") or "balance", subject=tk,
                       unit=COUNT if result.get("metric") == "shares_outstanding" else MONEY,
                       value=float(lr["value_then"]), as_of=lr["last_reported"], group="fundamentals")
            facts.append(f)
            note["last_reported"] = {"last_reported": lr["last_reported"], "fact": f.id, "note": lr.get("note")}
        return facts, note
    # A LINE THE SHEET DOES NOT CARRY AT THIS DATE is an absence, not a figure. The
    # block gives what it read at ANOTHER date; harvested as it stood, that value
    # became a scalar dated to this sheet ("commercial paper … as of 2026-03-31:
    # $0.00", V1 smoke) — a number at a date it was never reported for. The row
    # says it is not here and names the date it is, which is the call to make.
    missing = result.get("not_reported_at_this_date")
    absent: list[F.Fact] = []
    if isinstance(missing, dict) and not result.get("error"):
        result = {k: v for k, v in result.items() if k != "not_reported_at_this_date"}
        for line, was in missing.items():
            last = (was or {}).get("last_reported") if isinstance(was, dict) else None
            absent.append(F.fact(
                F.ABSENCE, line, subject=tk, as_of="n/a", group="fundamentals",
                text=(f"{line} is not on {tk}'s balance sheet as of {result.get('as_of')}"
                      + (f"; it was last reported as of {last}" if last else ""))[:600],
                params={"error": "not_reported_at_this_date"},
                means={"reason": registry.reason_of("not_reported_at_this_date"),
                       **({"way_out": f"read it at the date it has: at={last}"} if last else {})}))
    # a balance sheet: every balance carries its own as_of and fact_id (typed figures)
    # under its metric name — the walker names each by its key.
    facts, note = harvest(result, ctx)
    facts = [*facts, *absent]
    if result.get("metric") and not result.get("error"):
        # a flow or a series is named by its metric, not by the key it sits under
        facts = [replace(f, measure=result["metric"]) if f.measure in ("", "value", "points") else f for f in facts]
    return facts, note


def read_filings(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    tk = result.get("ticker") or _ticker(args)
    facts: list[F.Fact] = []
    if isinstance(result.get("passages"), list):
        note = {k: v for k, v in result.items() if k != "passages"}
        note["passages"] = []
        for p in result["passages"]:
            cit = p.get("citation") or {}
            f = F.fact(F.PASSAGE, f"{cit.get('form_type') or 'filing'} {p.get('item') or ''}".strip(), subject=tk,
                       text=p.get("text") or "", as_of=cit.get("filing_date") or "n/a",
                       params={k: v for k, v in (("form_type", cit.get("form_type")), ("item", p.get("item")),
                                                 ("accession", cit.get("accession")), ("section_title", p.get("section_title")))
                               if v},
                       sources=tuple(s for s in (p.get("chunk_id"),) if _is_id(s)), group="fundamentals")
            facts.append(f)
            note["passages"].append({"fact": f.id, "item": p.get("item"), "section_title": p.get("section_title"),
                                     "source_url": cit.get("source_url")})
        return facts, note
    if isinstance(result.get("text"), str) and not result.get("error"):
        cit = result.get("citation") or {}
        f = F.fact(F.PASSAGE, f"{cit.get('form_type') or 'filing'} {result.get('item_code') or ''}".strip(), subject=tk,
                   text=result["text"], as_of=cit.get("filing_date") or "n/a",
                   params={k: v for k, v in (("form_type", cit.get("form_type")), ("item", result.get("item_code")),
                                             ("accession", cit.get("accession")), ("title", result.get("title"))) if v},
                   sources=tuple(s for s in (cit.get("id"),) if _is_id(s)), group="fundamentals")
        facts.append(f)
        note = {k: v for k, v in result.items() if k != "text"}
        note["fact"] = f.id
        return facts, _strip(note, Ctx("read_filings"))
    return facts, _strip(result, Ctx("read_filings"))


def read_prices(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    tk = result.get("ticker") or _ticker(args)
    facts, note = harvest(result, Ctx("read_prices", subject=tk, as_of=result.get("as_of") or result.get("to"), group="price"))
    return facts, note


def read_book(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    ref = args.get("ref") or ""
    subject = result.get("run_id") or result.get("portfolio_id") or result.get("ticker") or ref
    # a task's state
    if result.get("kind") in ("task", "research_run", "exposure_run") and isinstance(result.get("status"), str):
        f = F.fact(F.TASK, result["kind"], subject=result.get("id") or ref, text=result["status"],
                   as_of=(result.get("completed_at") or None),
                   params={k: v for k, v in result.items() if k in ("type", "error", "run_id") and v},
                   sources=tuple(s for s in (result.get("id"), result.get("run_id")) if _is_id(s)), group="book_derived")
        return [f], {k: v for k, v in result.items() if k not in ("status",)} | {"fact": f.id}
    # figures by name on a run or scenario row: {name: {value, unit_class}}
    if isinstance(result.get("figures"), dict):
        facts: list[F.Fact] = []
        note = {k: v for k, v in result.items() if k not in ("figures", "units")}
        note["figures"] = {}
        for name, fig in result["figures"].items():
            table, _, rest = name.partition(".")
            who, col = (rest.rsplit(".", 1) if "." in rest else (None, rest))
            f = F.fact(F.SCALAR, f"{table}.{col}" if table != "count" else name, subject=who or subject,
                       unit=str(fig.get("unit_class")).upper(), value=float(fig["value"]),
                       as_of=result.get("as_of"), params=({"of": subject} if who else {}),
                       sources=(ref,) if _is_id(ref) else (), group=rs.group_of(name) or "book_derived")
            facts.append(f)
            note["figures"][name] = f.id
        return facts, note
    # the brief: its prose per section, never its blocks (they are a stored answer)
    sec = result.get("section") or {}
    if isinstance(sec.get("brief"), dict) and "blocks" in sec["brief"]:
        r = copy.deepcopy(result)
        b = r["section"]["brief"]
        b["sections"] = {k: (v.get("text") if isinstance(v, dict) else v) for k, v in (b.pop("blocks") or {}).items()}
        result = r
    # A portfolio's own sections (limits, freshness) describe the book as it
    # stands when read: their date is the reading's, not a run's.
    from datetime import date as _date
    facts, note = harvest(result, Ctx("read_book", subject=subject,
                                      as_of=result.get("as_of") or (_date.today().isoformat() if ref.startswith("port_") else None),
                                      group="book_derived", sources=(ref,) if _is_id(ref) else ()))
    return facts, note


def analysis(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    """WHAT `book.analysis` DERIVED, UNDER THE NAMES THE REGISTRY SAYS IT YIELDS.

    The measure nets each risk's factor betas and measures the room from every
    check to its tiers; that is what it records (integration_service._record) and
    what `Method.yields` declares. Its payload also repeats what it read — every
    position, every check's value and tiers, every leg — and walked generically
    (V1 step 3, until the smoke) that was 146 rows where 46 are the measure's own,
    under a third spelling of the same figures ("net exposures rates up net
    beta"), with three things wrong that the offline fixtures did not show:

      · a COLLINEAR fit made the whole risk's object "not quotable alone", the NET
        included — so the gate would refuse the one figure the flag says is
        quotable (`collinear fit: the net is quotable, no single leg is`);
      · the legs came back as rows, which `book_read` withholds as undetermined;
      · a risk no factor measures is a dict with no number in it, so it produced
        no row at all, and a book with no row for a risk reads as not exposed.

    So: a net and a gross beta per measured risk, an ABSENCE per unmeasured one,
    the two rooms per check, and an absence for what is withheld. The run's own
    columns are read off the run (`book_read`), where their one spelling lives."""
    op = "portfolio.integration"
    units = rs.CALC_RESULTS[op]
    run, as_of = result.get("run_id") or result.get("subject"), result.get("as_of")
    sources = tuple(s for s in (result.get("calc_id"), run) if _is_id(s))
    made = {"method": "book.analysis"}
    facts: list[F.Fact] = []
    for risk, n in (result.get("net_exposures") or {}).items():
        if not isinstance(n, dict):
            continue
        if not n.get("measured"):
            facts.append(F.fact(F.ABSENCE, f"{op}.net_beta.{risk}", subject=run, as_of="n/a", group="factor_exposure",
                                text=f"the book's exposure to {risk.replace('_', ' ')} is not measured on this run: "
                                     f"{n.get('reason') or 'no factor measures it'}"[:600],
                                params={"error": "not_measured", **made}, sources=sources,
                                means={"reason": "not_held"}))
            continue
        words = registry.words_beside(n)
        for key in ("net_beta", "gross_beta"):
            if _is_num(n.get(key)):
                facts.append(F.fact(F.SCALAR, f"{op}.{key}.{risk}", subject=run, unit=units[key], value=float(n[key]),
                                    as_of=as_of, params=dict(made), sources=sources, group="factor_exposure",
                                    means=registry.for_leaf(key, words)))
    for h in result.get("headroom") or []:
        check = h.get("check")
        if not isinstance(check, str):
            continue
        for key in ("room_to_warning", "room_to_breach"):
            if _is_num(h.get(key)):
                facts.append(F.fact(F.SCALAR, f"{op}.{key}", subject=check, unit=units[key], value=float(h[key]),
                                    as_of=as_of, params={"of": run, **made}, sources=sources, group="mandate",
                                    means=registry.words_beside(h)))
    for check in result.get("headroom_not_recorded") or []:
        facts.append(F.fact(F.ABSENCE, f"{op}.room_to_breach", subject=str(check), as_of="n/a", group="mandate",
                            text=f"{check} recorded no measured value on this run, so there is no room to measure"[:600],
                            params={"error": "not_measured", "of": run, **made}, sources=sources,
                            means={"reason": "not_held", "status": "not_run"}))
    if isinstance(result.get("stress_withheld"), str) and result["stress_withheld"]:
        facts.append(F.fact(F.ABSENCE, "stress_results", subject=run, as_of="n/a", group="stress",
                            text=result["stress_withheld"][:600], params={"error": "withheld", **made},
                            sources=sources, means={"reason": "policy", "flags": ["withheld_pending_validation"]}))
    note = {k: v for k, v in result.items() if k in ("method", "subject", "run_id", "portfolio_id", "as_of", "calc_id")}
    return facts, note


# A measure whose payload is not "its figures and nothing else" is read by the
# adapter that knows what it derived; every other measure is walked.
_MEASURE_ADAPTERS: dict[str, Adapter] = {"book.analysis": analysis}


def compute(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    own = _MEASURE_ADAPTERS.get(result.get("method")) if isinstance(result.get("method"), str) else None
    if own is not None and not result.get("error"):
        return own(args, result)
    if isinstance(result.get("results"), list):
        allf: list[F.Fact] = []
        notes = []
        for r in result["results"]:
            # each entry of a list combined with ONE figure is made of that entry and that figure
            own = ({**args, "inputs": [r["operand"], *([result["by"]] if isinstance(result.get("by"), str) else [])]}
                   if isinstance(r, dict) and isinstance(r.get("operand"), str) else args)
            fs, n = compute(own, r)
            allf += fs
            notes.append(n)
        return allf, {"results": notes}
    subject = result.get("subject") or result.get("ticker") or result.get("run_id") or result.get("portfolio_id")
    if isinstance(args.get("subject"), str) and not subject:
        subject = args["subject"]
    method = result.get("method") or result.get("op") or args.get("method") or args.get("op") or "compute"
    group = ("price" if str(method).startswith("price.") else
             "book_derived" if str(method).startswith(("book.", "rank", "calc.set")) or (isinstance(subject, str) and subject.startswith(("run_", "port_", "calc_")))
             else "derived")
    # V28 C2: what unit a METHOD's figures carry is declared once, on the method
    # (skill.Method.unit_class), and read here — not guessed from a key name and
    # not copied into a second list. UNIT_BY_KEY still wins where a specific key
    # says otherwise (a method whose payload also counts sessions), so this is
    # the default for the leaves the key list does not name.
    # Found by book.explain_episode: called ZERO times in the 244-turn battery,
    # so its payload had never met the adapter; the first turn that reached it
    # (V27 routed the model there) died on `portfolio_window_return`.
    # `method` may be a LIST — compute takes lists, and a refused list call keeps
    # the whole list in args. One method declares a unit; several do not agree to,
    # and the per-result branch above has already handled the successful case.
    one = method if isinstance(method, str) else (method[0] if isinstance(method, list) and len(method) == 1 else None)
    declared = skill.METHODS[one].unit_class if one in skill.METHODS else None
    # V1: what the measure is BUILT ON is the registry entry's to say, and every
    # fact of it carries the word (ending balances, the adjusted close)
    built_on = {"basis": list(skill.METHODS[one].basis)} if one in skill.METHODS and skill.METHODS[one].basis else {}
    ctx = Ctx("compute", subject=subject.upper() if isinstance(subject, str) and not subject.startswith(("run_", "port_", "calc_")) else subject,
              as_of=result.get("as_of"), group=group,
              leaf_unit=declared.upper() if isinstance(declared, str) else None,
              sources=tuple(s for s in (result.get("calc_id"),) if _is_id(s)), means=built_on)
    r = copy.deepcopy(result)
    # an op over one issuer's figures is that issuer's figure: the typed
    # calculator records the operands' issuers, and a single one is the subject
    # (live round 2: ten `weight × beta` results labelled by measure alone)
    issuers = (r.get("type") or {}).get("issuers") if isinstance(r.get("type"), dict) else None
    if ctx.subject is None and isinstance(issuers, list) and len(issuers) == 1 and isinstance(issuers[0], str):
        ctx = ctx.child(subject=issuers[0])
    # a scalar op / formula / price method: the top-level value is the method's own figure
    if _is_num(r.get("value")):
        measure = (r.get("quantity") or r.get("formula") or (r.get("type") or {}).get("quantity")
                   or r.get("operation") or str(method))
        unit = r.get("unit_class") or (r.get("type") or {}).get("unit_class")
        if not isinstance(unit, str):
            raise UnknownUnit(f"compute {method}: top-level value carries no unit_class")
        params = _params_of(r, ctx)
        if one in skill.METHODS:
            params["method"] = one                            # the row's `from`: the measure that made it
        # WHAT A CALCULATION WAS MADE OF (V1 live smoke). `calc` promises "a new figure
        # with what it was made of", and the fact recorded only the operation — so once the
        # analyst named a quotient "fcf_to_debt_xom", nothing said free cash flow was in it,
        # and the check refused "free cash flow to debt is 39.4%" as naming a measure the
        # figure is not. The inputs are the f_ ids the call was made with.
        made_of = [i for i in (args.get("inputs") or []) if isinstance(i, str) and i.startswith(F.PREFIX)] \
            if isinstance(args.get("inputs"), list) else []
        if made_of and not (one in skill.METHODS):
            params["inputs"] = made_of[:_INPUTS_KEPT]
        params.update(_composition_of(r))                     # what a composed total was built from
        f = F.fact(F.SCALAR, measure, subject=ctx.subject, unit=unit.upper(), value=float(r.pop("value")),
                   as_of=_as_of_of(r, ctx), window=_window_of(r, ctx), params=params,
                   sources=_sources_of(r, ctx), group=group,
                   means=registry.merged(ctx.means, registry.words_beside(r)))
        facts, note = harvest(r, ctx.child(as_of=f.as_of, window=f.window))
        note["fact"] = f.id
        return [f, *facts], note
    facts, note = harvest(r, ctx)
    if isinstance(r.get("type"), dict) and r["type"].get("kind") == "ranking":
        facts = _ranked(facts, r)
    return facts, note


def _ranked(facts: list[F.Fact], r: dict) -> list[F.Fact]:
    """AN ORDERING'S ENTRIES, NAMED FOR WHAT WAS RANKED (V1 smoke). The walker
    names a leaf by the key it sits under, so ten ranked weights came back as ten
    rows called "ordering value" — the one thing the row did not say was what
    had been ordered. The payload says it (`quantity`), and says how many were
    ordered and which way, so the row reads "issuer exposures: weight, MSFT:
    16.0% — 1st highest of 10". `place` and `of` are the params the answer check
    already reads a superlative against (answer_check._ranked_aliases)."""
    what = r.get("quantity") or r["type"].get("quantity")
    n = len(r.get("operands") or r.get("ordering") or [])
    direction = r.get("direction") if r.get("direction") in ("highest", "lowest") else "highest"
    out: list[F.Fact] = []
    for f in facts:
        if f.measure == "ordering.value" and isinstance(f.params.get("rank"), int):
            params = {k: v for k, v in f.params.items() if k != "rank"}
            f = replace(f, measure=what or f.measure,
                        params={**params, "op": "rank", "place": f.params["rank"], "of": n, "direction": direction})
        elif f.measure == "spread" and what:
            f = replace(f, measure=f"{what}.spread", params={**f.params, "op": "rank", "of": n})
        out.append(f)
    return out


def search_web(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    tk = result.get("ticker") or _ticker(args)
    facts: list[F.Fact] = []
    if not isinstance(result.get("sources"), list):
        return facts, _strip(result, Ctx("search_web"))
    note = {k: v for k, v in result.items() if k != "sources"}
    note["sources"] = []
    for s in result["sources"]:
        sid = s.get("source_id") or s.get("id")
        text = s.get("snippet") or s.get("content") or s.get("title") or ""
        if not text:
            continue
        f = F.fact(F.PASSAGE, s.get("title") or "web source", subject=tk, text=text,
                   as_of=s.get("published_at") or s.get("published") or "n/a",
                   params={k: v for k, v in (("url", s.get("url")), ("publisher", s.get("publisher") or s.get("domain"))) if v},
                   sources=(sid,) if _is_id(sid) else (), group="fundamentals")
        facts.append(f)
        note["sources"].append({"fact": f.id, "title": s.get("title"), "url": s.get("url")})
    return facts, note


def start(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    tid = result.get("run_id") or result.get("task_id")
    if not result.get("enqueued") or not _is_id(tid):
        return [], _strip(result, Ctx("start"))
    f = F.fact(F.TASK, result.get("kind") or args.get("kind") or "task", subject=tid, text="enqueued",
               params={k: v for k, v in (("ticker", result.get("ticker")), ("reason", result.get("reason"))) if v},
               sources=tuple(s for s in (result.get("task_id"), result.get("run_id")) if _is_id(s)), group="book_derived")
    return [f], {**result, "fact": f.id}


def no_facts(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    return [], _strip(result, Ctx("none"))


# ── the primitives (V1): a book's rows, and every result as rows ─────────────

def book_read(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    """A run's or scenario's figures, read off the table they sit on. The payload
    names each figure as the book does (`limit_checks.issuer_concentration:LLY.
    current_value`) and carries the word its ROW said (a check's status); the
    Fact's measure and subject are split by the one rule every reader of a book
    name uses (analytics/resources.identity_of, V38/S4)."""
    ref = result.get("book") or args.get("book") or ""
    facts: list[F.Fact] = []
    note = {k: v for k, v in result.items() if k not in ("figures", "withheld")}
    for fig in result.get("figures") or []:
        name = fig["name"]
        measure, entity = rs.identity_of(name)
        facts.append(F.fact(F.SCALAR, measure if entity is not None else name, subject=entity or ref,
                            unit=str(fig["unit_class"]).upper(), value=float(fig["value"]),
                            as_of=result.get("as_of"), params=({"of": ref} if entity is not None else {}),
                            sources=(ref,) if _is_id(ref) else (), group=rs.group_of(name) or "book_derived",
                            means=registry.validate_means(fig.get("means") or {})))
    for held in result.get("withheld") or []:
        facts.append(F.fact(F.ABSENCE, held["name"], subject=ref, text=str(held["reason"])[:600], as_of="n/a",
                            params={"error": "not_alone"}, sources=(ref,) if _is_id(ref) else (),
                            group="book_derived", means={"reason": "meaningless"}))
    return facts, note


_BOOK_TABLES = frozenset(r.table for r in rs.RUN_CHILDREN if r.table)


def scenario(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    """A SCENARIO BUILDS A BOOK; READING IT IS `book_read` (V1 smoke). The payload
    is the trade AND every table of the book it made, and shown whole one sale
    was 99 rows — the analyst asked what happens to one check and was handed
    every weight, sector and tier. So the rows are the trade (what was sold or
    bought, the proceeds, the book's new value) and what the scenario does NOT
    carry, each as the absence it is; the new book's tables go on the ledger,
    where a sentence can point at them, and are read off the id it returns.

    The trade list the caller sent is not echoed back as figures: `sold` says
    what was done with it, and "sales fraction 50%" beside "sold fraction 50%"
    was one fact twice."""
    if result.get("error"):
        return compute(args, result)
    made = result.get("made") or result.get("calc_id")
    facts, note = compute(args, {k: v for k, v in result.items() if k not in ("sales", "buys")})
    why_not = ("a scenario re-prices the book and re-runs its concentration and exposure checks; it has no "
               "return history, so nothing fitted on returns is carried")
    for check in result.get("checks_not_run") or []:
        facts.append(F.fact(F.ABSENCE, f"limit_checks.{check}", subject=made, as_of="n/a", group="book_derived",
                            text=f"{check} is not re-run on the book after the trade: {why_not}"[:600],
                            params={"error": "not_run"}, sources=(made,) if _is_id(made) else (),
                            means={"reason": "meaningless", "status": "not_run"}))
    fx = result.get("factor_exposure")
    if isinstance(fx, dict) and fx.get("measured") is False:
        facts.append(F.fact(F.ABSENCE, "factor_attributions", subject=made, as_of="n/a", group="book_derived",
                            text=f"factor betas are not carried to the book after the trade: {fx.get('reason') or why_not}"[:600],
                            params={"error": "not_run"}, sources=(made,) if _is_id(made) else (),
                            means={"reason": "meaningless"}))
    return facts, note


def _is_table_row(f: F.Fact) -> bool:
    return f.kind != F.ABSENCE and f.measure.split(".")[0] in _BOOK_TABLES


# WHAT A VERB SHOWS OF WHAT IT RECORDS. Every fact an adapter makes goes on the
# ledger; a verb whose job is to BUILD something shows what it built and where it
# is, and leaves the reading of it to the verb that reads.
_RECORDED_NOT_SHOWN: dict[str, Any] = {"scenario": _is_table_row}


_INPUTS_KEPT = 40          # the most a `calc` takes (tools/primitives: inputs.maxItems)
PULL_PREFIX = "r_"
_WAY_OUT_KEYS = ("available", "nearest", "known", "allowed", "portfolios", "tables", "columns_of_table",
                 "items_indexed", "data_covers", "hint")


def stamped(f: F.Fact, pull: str) -> F.Fact:
    """The Fact carrying the id of the call that pulled it — what `open(r_…)`
    finds a call's rows by and what a row's `from` begins with."""
    return replace(f, params={**f.params, "pull": pull})


def _problems_said(problems: Any) -> str:
    said = []
    for p in problems if isinstance(problems, list) else []:
        if isinstance(p, dict):
            said.append(f"{p.get('field')}: {p.get('problem')}")
    return "; ".join(said)


def refusal_fact(tool: str, args: dict, result: dict) -> F.Fact:
    """WHAT A PRIMITIVE COULD NOT DO, AS A ROW (V1). The service's own sentence is
    the text; the reason is the registry's word for its code; the way out is
    whatever the refusal already names — the allowed values, the nearest names,
    the dates the data covers — so a refusal never hands the problem back bare."""
    code = result.get("error")
    detail = str(result.get("detail") or result.get("hint") or code or "the desk could not do this")
    said = _problems_said(result.get("problems"))
    if said:
        detail = f"{detail} — {said}" if detail != code else said
    ways = []
    for k in _WAY_OUT_KEYS:
        v = result.get(k)
        if isinstance(v, dict):
            v = [f"{a}: {b}" for a, b in list(v.items())[:6]]
        if isinstance(v, (list, tuple)) and v:
            ways.append(f"{k.replace('_', ' ')}: " + ", ".join(str(x) if not isinstance(x, dict) else
                                                              str(x.get("portfolio_id") or x.get("name") or x)
                                                              for x in list(v)[:12]))
        elif isinstance(v, str) and v:
            ways.append(v)
    subject = next((args.get(k) for k in ("ticker", "book", "subject") if isinstance(args.get(k), str)), None)
    want = next((args.get(k) for k in ("name", "line", "table", "item", "what", "op", "kind") if isinstance(args.get(k), str)), tool)
    means: dict = {"reason": registry.reason_of(code) if code != "invalid_arguments" else "param_out_of_range"}
    # A MEASURE OF ANOTHER FAMILY is not a misspelling: the name is right and the
    # asker is wrong. The enum refused it; the row says whose it is, so the line
    # goes back to the lead as "ask the other analyst" and not as "unavailable".
    elsewhere = [p.get("value") for p in (result.get("problems") or []) if isinstance(p, dict)
                 and p.get("field") == "name" and p.get("value") in registry.METHODS]
    # PARAMS THAT DO NOT FIT: the way out is what the measure DOES take, from its own
    # schema. "'window' was unexpected" sent the market analyst home with two lines
    # unsettled and thirteen calls unspent (V1 live smoke): it never learned the key.
    asked = args.get("name") if isinstance(args.get("name"), str) else None
    if code == "invalid_params" and asked in registry.METHODS and isinstance(result.get("params_schema"), dict):
        takes = registry.params_said(registry.METHODS[asked])
        ways.insert(0, f"{asked} takes: {takes}" if takes else f"{asked} takes no params")
    if tool == "metric" and elsewhere:
        owners = " and ".join(f"the {f} analyst" for f in registry.METHODS[elsewhere[0]].faces) or "no analyst (it is an action)"
        means["reason"] = "not_on_this_face"
        ways = [f"{elsewhere[0]} is a measure {owners} may ask for"]
        # and the sentence is about whose it is — the enum's own ("not one of the 34
        # names…; nearest: ebitda, roic") answers a misspelling nobody made
        detail = f"{elsewhere[0]} is not one of this analyst's measures"
    if ways:
        means["way_out"] = "; ".join(ways)
    return F.fact(F.ABSENCE, str(want)[:200], subject=subject, text=f"{tool}: {detail}"[:600], as_of="n/a",
                  params={"error": code, "tool": tool}, standalone=False, group="boundary", means=means)


def _call_said(tool: str, args: dict) -> str:
    shown = ", ".join(f"{k}={ejson.dumps(v)[:60]}" for k, v in args.items() if k != "why" and v is not None)
    return f"{tool}({shown})"


_PASS_THROUGH = ("catalogue", "made", "kept", "task_id", "run_id", "next_offset", "as_of", "book")


def present(tool: str, args: dict, shown: list[F.Fact], note: dict, held: dict | None, pull: str) -> dict:
    """One primitive's result as the model reads it: the call's id and what was
    called, then the rows. No legend: a row says what it is (services/facts.line)."""
    listed = note.get("catalogue") if isinstance(note, dict) else None
    n, unit = (len(listed), "name") if (listed and not shown) else (len(shown), "row")
    out: dict = {"pull": pull, "head": f"{pull} {_call_said(tool, args)} → {n} {unit}{'s' if n != 1 else ''}",
                 "rows": [F.line(f) for f in shown]}
    for k in _PASS_THROUGH:
        if isinstance(note, dict) and note.get(k) not in (None, "", [], {}):
            out[k] = note[k]
    if held and held.get("of_the_book_made") and out.get("made"):
        out["held_back"] = (f"the book it made holds {held['count']} more figures (weights, sector weights, every "
                            f"re-run check): read the ones you need off it with book_read(book=\"{out['made']}\")")
    elif held:
        out["held_back"] = (f"{held.get('count')} more rows were pulled and are on the ledger, not shown here: "
                            f"ask for less in one call (one column, one row, fewer subjects)")
    return out


ADAPTERS: dict[str, Adapter] = {
    "describe": describe,
    "read_fundamentals": read_fundamentals,
    "read_filings": read_filings,
    "read_prices": read_prices,
    "read_book": read_book,
    "compute": compute,
    "search_web": search_web,
    # V1: the primitives. A verb's payload is the payload of the service it
    # wraps, so it reads through the adapter that already knows that payload.
    "list": no_facts, "filings_read": read_fundamentals, "prices_read": read_prices, "book_read": book_read,
    "metric": compute, "calc": compute, "scenario": scenario,
    "filings_search": read_filings, "filings_section": read_filings, "web_search": search_web,
    "start": start,
    "think": no_facts,
    "submit_brief": no_facts,
}

def adapt(tool: str, args: dict, result: dict) -> tuple[list[F.Fact], dict, dict | None]:
    """(facts shown, note, held_back) for one tool result — the wrapper's call.
    `adapt_all` is the same call with the facts it HELD BACK as well: they are
    evidence either way, and the ledger records them (V33: a cap sized for a
    model's context was trimming the ledger, and a rank the analyst asked for
    never reached it).

    The adapter reads the payload in the form the model reads it: serialized
    once with the encoder the agent loop uses, and loaded back. In process a
    service hands over `datetime.date` and `Decimal`; on the wire those are an
    ISO string and a float, and that is the only form the fixtures ever held.
    _as_of_of asks `isinstance(v, str)`, so a date OBJECT was skipped and the
    holding fell back to the reading day: live read_book(port_001) showed every
    position "as of 2026-09-05" beside a payload saying valued_as_of 2026-09-03,
    and 2,006 offline tests over 47 wire-form fixtures could not see it. One
    round-trip here, and no adapter needs to know what a service returns.
    """
    adapter = ADAPTERS[tool]
    token = _UNTYPED.set([])
    try:
        facts, note = adapter(args or {}, ejson.loads(ejson.dumps(result)))
        untyped = _UNTYPED.get() or []
    finally:
        _UNTYPED.reset(token)
    if untyped and isinstance(note, dict):
        # Said, not swallowed: the model is told which numbers it cannot point
        # at and why, in the same note that carries the ones it can.
        note = {**note, "untyped": {u["key"]: u["reason"] for u in untyped}}
    kept, held = F.cap(facts)
    not_shown = _RECORDED_NOT_SHOWN.get(tool)
    if not_shown is not None and any(not_shown(f) for f in kept):
        hidden = [f for f in kept if not_shown(f)]
        kept = [f for f in kept if not not_shown(f)]
        held = {"count": len(hidden) + int((held or {}).get("count") or 0), "of_the_book_made": True,
                "measures": sorted({f.measure.split(".")[0] for f in hidden})}
    if held:
        kept_ids = {f.id for f in kept}
        note = _blank_ids(note, {f.id for f in facts if f.id not in kept_ids})
    _ALL.set(facts)
    return kept, note, held


# The facts one `adapt` made, held-back ones included: `adapt` returns what the
# model may READ, this is what the session KNOWS. Set by the call above and read
# by the wrapper right after it, in the same task.
_ALL: contextvars.ContextVar[list] = contextvars.ContextVar("adapt_all_facts", default=[])


def adapt_all(tool: str, args: dict, result: dict) -> tuple[list[F.Fact], dict, dict | None, list[F.Fact]]:
    """`adapt`, plus every fact it made — the ledger's share."""
    token = _ALL.set([])
    try:
        kept, note, held = adapt(tool, args, result)
        return kept, note, held, list(_ALL.get())
    finally:
        _ALL.reset(token)


def _blank_ids(node: Any, ids: set[str]) -> Any:
    if isinstance(node, dict):
        return {k: _blank_ids(v, ids) for k, v in node.items()}
    if isinstance(node, list):
        return [_blank_ids(v, ids) for v in node]
    if isinstance(node, str) and node in ids:
        return "held_back"
    return node


def numeric_leaves(node: Any, path: str = "") -> list[tuple[str, float]]:
    """Every number in a note that is a figure — I1 says there are none. A
    passthrough structure (a schema, a list of problems) is not walked: its
    numbers describe an argument, not the world. A test helper, exported."""
    out: list[tuple[str, float]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in PASSTHROUGH_KEYS:
                continue
            out += numeric_leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += numeric_leaves(v, f"{path}[{i}]")
    elif _is_num(node):
        out.append((path, node))
    return out
