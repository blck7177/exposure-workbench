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
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from exposure_workbench.analytics import resources as rs
from exposure_workbench.services import facts as F
from exposure_workbench.utils import json as ejson

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
    "proceeds": MONEY, "market_value_sold": MONEY, "value_then": MONEY, "market_value": MONEY,
    # ratios
    "depth": RATIO, "gap": RATIO, "tolerance": RATIO, "difference": RATIO, "factor_share": RATIO,
    "unexplained_share": RATIO, "signed_for_this_risk": RATIO, "room_to_warning": RATIO,
    "room_to_breach": RATIO, "current": RATIO, "net_beta": RATIO, "gross_beta": RATIO,
    "sum_of_contributions": RATIO, "sum_of_factor_contributions": RATIO, "alpha_plus_residual": RATIO,
    "recorded_alpha_plus_residual": RATIO, "reported_floor": RATIO, "fraction": RATIO,
    "deepest_depth": RATIO, "spread": RATIO,
    # counts
    "count": COUNT, "total_holdings": COUNT, "quantity": COUNT, "sessions": COUNT, "sessions_behind": COUNT,
    "runs_in_flight": COUNT, "checks_run": COUNT, "checks_clear": COUNT, "evaluated": COUNT, "fired": COUNT,
    "clear": COUNT, "terms": COUNT, "n": COUNT, "unmatched_points": COUNT, "trough_days": COUNT,
    "recovery_days": COUNT, "skipped_recent_sessions": COUNT, "positions": COUNT, "alerts": COUNT,
    "metrics": COUNT, "passages": COUNT, "flow": COUNT, "instant": COUNT, "methods_computable": COUNT,
    "periods_without_comparable_prior": COUNT, "runs": COUNT, "filings": COUNT, "limits": COUNT,
    "holdings": COUNT, "checks": COUNT, "names": COUNT, "periods": COUNT,
}

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
PASSTHROUGH_KEYS = frozenset({"params_schema", "problems", "known", "nearest", "available", "held_on",
                              "expected", "supported", "allowed"})

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
                       sources=_sources_of(node, ctx), group=ctx.group)
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
                       params={**ctx.params, **_params_of(node, ctx)},
                       standalone=ctx.standalone and node.get("quotable_individually", True) is not False,
                       sources=_sources_of(node, ctx), group=ctx.group)
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
                        default_unit=declared.upper() if isinstance(declared, str) else ctx.default_unit)
        if isinstance(node.get("ticker"), str) and key not in ("brief",):
            sub = sub.child(subject=node["ticker"])
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
        return [_harvest(v, key, f"{path}[{i}]", ctx, facts) for i, v in enumerate(node)]
    if _is_num(node):
        if key in PARAM_KEYS:
            return node
        measure = f"{ctx.table}.{key}" if ctx.table else MEASURE_ALIAS.get(key, path or key)
        f = F.fact(F.SCALAR, measure, subject=ctx.subject, unit=_unit_for(key, ctx), value=float(node),
                   as_of=ctx.as_of, window=ctx.window, params=dict(ctx.params), standalone=ctx.standalone,
                   sources=ctx.sources, group=ctx.group)
        facts.append(f)
        return f.id
    return node


def _harvest_row(row: dict, key: str, path: str, ctx: Ctx, facts: list[F.Fact]) -> dict:
    """One row of a table: its label is the subject of every figure in it."""
    label = _label_of(row)
    sub = ctx.child(subject=label or ctx.subject, as_of=_as_of_of(row, ctx), window=_window_of(row, ctx),
                    sources=_sources_of(row, ctx), params={**ctx.params, **_params_of(row, ctx)},
                    standalone=ctx.standalone and row.get("quotable_individually", True) is not False)
    out: dict = {}
    for k, v in row.items():
        if k in DROP_KEYS:
            continue
        if k in PASSTHROUGH_KEYS:
            out[k] = v
            continue
        if _is_num(v) and k not in PARAM_KEYS:
            table = ctx.table or MEASURE_TABLE.get(key) or key
            f = F.fact(F.SCALAR, f"{table}.{k}", subject=sub.subject, unit=_unit_for(k, sub.child(table=ctx.table), row),
                       value=float(v), as_of=sub.as_of, window=sub.window, params=dict(sub.params),
                       standalone=sub.standalone, sources=sub.sources, group=ctx.group)
            facts.append(f)
            out[k] = f.id
        else:
            out[k] = _harvest(v, k, f"{path}.{k}", sub, facts)
    return out


def _params_of(obj: dict, ctx: Ctx) -> dict:
    p: dict = {}
    for k in ("benchmark", "rank", "factor", "months", "window_days", "days", "direction", "op",
              "peak_date", "trough_date", "recovery_date", "high_date", "form_type", "item", "fiscal_year",
              "fiscal_quarter", "confidence", "fraction", "scenario"):
        v = obj.get(k)
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
    # a balance sheet: every balance carries its own as_of and fact_id (typed figures)
    # under its metric name — the walker names each by its key.
    facts, note = harvest(result, ctx)
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


def compute(args: dict, result: dict) -> tuple[list[F.Fact], dict]:
    if isinstance(result.get("results"), list):
        allf: list[F.Fact] = []
        notes = []
        for r in result["results"]:
            fs, n = compute(args, r)
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
    ctx = Ctx("compute", subject=subject.upper() if isinstance(subject, str) and not subject.startswith(("run_", "port_", "calc_")) else subject,
              as_of=result.get("as_of"), group=group,
              sources=tuple(s for s in (result.get("calc_id"),) if _is_id(s)))
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
        f = F.fact(F.SCALAR, measure, subject=ctx.subject, unit=unit.upper(), value=float(r.pop("value")),
                   as_of=_as_of_of(r, ctx), window=_window_of(r, ctx), params=_params_of(r, ctx),
                   sources=_sources_of(r, ctx), group=group)
        facts, note = harvest(r, ctx.child(as_of=f.as_of, window=f.window))
        note["fact"] = f.id
        return [f, *facts], note
    facts, note = harvest(r, ctx)
    return facts, note


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


ADAPTERS: dict[str, Adapter] = {
    "describe": describe,
    "read_fundamentals": read_fundamentals,
    "read_filings": read_filings,
    "read_prices": read_prices,
    "read_book": read_book,
    "compute": compute,
    "search_web": search_web,
    "start": start,
    "think": no_facts,
    "respond": no_facts,
    "submit_brief": no_facts,
}

# How the held-back facts of a tool are read by name, for the `held_back` note.
READ_BY_NAME = {
    "describe": "read_book(ref, names=[…]) for a run or scenario; read_fundamentals(ticker, metric) for an issuer",
    "read_book": "read_book(ref, names=[…]) with fewer names",
    "compute": "read_book(<calc_id>, names=[…]) reads a scenario's figures by name",
    "read_prices": "read_prices(ticker, as_of=YYYY-MM-DD) reads one session",
}


def adapt(tool: str, args: dict, result: dict) -> tuple[list[F.Fact], dict, dict | None]:
    """(facts shown, note, held_back) for one tool result — the wrapper's call.

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
    facts, note = adapter(args or {}, ejson.loads(ejson.dumps(result)))
    kept, held = F.cap(facts)
    if held:
        held["how"] = READ_BY_NAME.get(tool, "ask for fewer names")
        dropped = {f.id for f in facts[len(kept):]}
        note = _blank_ids(note, dropped)
    return kept, note, held


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
