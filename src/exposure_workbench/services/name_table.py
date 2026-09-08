"""The name table (V27): every name a model can write into a tool argument,
with what it is and how it is used — one table behind the catalogue's rows,
the tools' enums and every unknown-name refusal.

The 2026-09-07 battery: 110 method names sent to read_book, 34 filed lines
sent to compute, ~38 method names sent to read_fundamentals, in 244 turns.
Three tools took free strings, describe printed bare names, and which tool
consumes which name was something the model had to remember. This module is
that binding as data. It is a VIEW over the four owners (skill's methods and
domains, resources' sections, concept_mapping's filed lines, series_ops' ops)
— nothing is declared twice — and a name that appears under two kinds is an
import-time error, so the answer to "what is X" is always one thing.

Imports only analytics and the pure concept map: the tool registry reads this
module, and compute_service reads the registry, so nothing here may reach a
service that reaches the registry.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from exposure_workbench.analytics import resources, series_ops, skill
from exposure_workbench.services import concept_mapping as cm

# What read_book reads besides row names: a portfolio's sections, a run's.
PORTFOLIO_SECTIONS: tuple[str, ...] = ("positions", "limits", "alerts", "freshness", "runs")
RUN_SECTIONS: tuple[str, ...] = ("alerts", "attribution", "risk_state")
# The Items read_filings reads whole (FilingSection.item_code, as the desk indexes them).
FILING_ITEMS: tuple[str, ...] = ("1", "1A", "2", "3", "7", "7A", "8", "9A")
# describe's data-domain views (catalogue_service.EXPANDS minus the domains).
VIEWS: tuple[str, ...] = ("fundamentals", "methods", "procedures", "book", "filings", "readings")

PLACEHOLDER = {"issuer": "<ticker>", "price": "<ticker>", "run": "<run_…>", "portfolio": "<port_…>",
               "scenario": "<calc_…>", "series": "<f_…>"}


@dataclass(frozen=True)
class Entry:
    name: str
    kind: str            # what the model is told it IS: "portfolio method", "filed line", …
    consumer: str        # the tool that takes it
    does: str            # one line
    subject_kind: str | None = None   # for methods and domains: what `subject` must be
    on: tuple[str, ...] = ()          # for sections: which ref kinds hold it


def _build() -> dict[str, Entry]:
    table: dict[str, Entry] = {}

    def put(e: Entry) -> None:
        if e.name in table and table[e.name].kind != e.kind:
            raise RuntimeError(f"name table: {e.name!r} is both {table[e.name].kind} and {e.kind}")
        table[e.name] = e

    for m in skill.METHODS.values():
        put(Entry(m.name, f"{m.subject_kind} method", "compute", m.describes, subject_kind=m.subject_kind))
    for p in skill.PROCEDURES.values():
        put(Entry(p.name, "domain", "describe", p.question, subject_kind=p.subject_kind))
    for n in cm.SUPPORTED_METRICS:
        put(Entry(n, "filed line", "read_fundamentals", "a line as the issuer filed it, by period"))
    for n in PORTFOLIO_SECTIONS:
        put(Entry(n, "section", "read_book", f"a portfolio's {n}", on=("portfolio",)))
    for n in RUN_SECTIONS:
        prev = table.get(n)
        on = tuple(sorted(set((prev.on if prev else ()) + ("run",))))
        put(Entry(n, "section", "read_book", f"a run's {n}", on=on))
    for n in FILING_ITEMS:
        put(Entry(n, "filing item", "read_filings", f"Item {n} of the latest filing, whole"))
    for n in skill.SCALAR_OPS + (skill.SCALE_OP, skill.RANK_OP, skill.REGRESS_OP) + tuple(series_ops.CHANGE_MODES) + tuple(series_ops.STAT_OPS):
        put(Entry(n, "op", "compute", "arithmetic over fact ids"))
    for n in VIEWS:
        put(Entry(n, "view", "describe", f"describe(subject, expand='{n}')"))
    return table


TABLE: dict[str, Entry] = _build()
TABLE_FILED_LINES: tuple[str, ...] = tuple(cm.SUPPORTED_METRICS)

# What a Procedure's `reads` may name: a run's figure groups, filed lines,
# filing items and sections — checked by test, since skill may not import here.
READABLE: frozenset[str] = frozenset(
    {key for key, _q, _p in resources.RUN_GROUPS} | set(cm.SUPPORTED_METRICS) | set(FILING_ITEMS)
    | set(PORTFOLIO_SECTIONS) | set(RUN_SECTIONS))


def get(name: str) -> Entry | None:
    return TABLE.get(name)


def method_names(kinds: tuple[str, ...]) -> list[str]:
    """The compute enum for a face: its kinds' methods, in registry order."""
    return [m.name for m in skill.METHODS.values() if m.subject_kind in kinds]


def _stub(schema: dict, name: str = "") -> str:
    """A placeholder for a required parameter, from its schema — enough to copy."""
    t = schema.get("type")
    if isinstance(t, list):
        t = next((k for k in t if k != "null"), "string")
    if t == "array":
        return "[" + _stub(schema.get("items") or {"type": "string"}) + "]"
    if t == "object":
        props = schema.get("properties") or {}
        req = schema.get("required") or list(props)
        return "{" + ", ".join(f"'{k}': {_stub(props.get(k, {}), k)}" for k in req) + "}"
    if t == "number" or t == "integer":
        return "<n>"
    if schema.get("enum"):
        return repr(next(v for v in schema["enum"] if v is not None))
    desc = (schema.get("description") or "").upper()
    if "YYYY" in desc or name in ("peak", "trough", "at", "start", "end"):
        return "'<YYYY-MM-DD>'"
    if name == "ticker":
        return "'<T>'"
    return "'<…>'"


def call(entry: Entry, subject: str | None = None, ref: str | None = None) -> str:
    """How the model uses this name: one call it can copy. A concrete subject
    when the caller has one (the subject level, where it is a fact), a
    placeholder otherwise (the root, which chooses no subject)."""
    if entry.consumer == "compute" and entry.kind.endswith(" method"):
        m = skill.METHODS[entry.name]
        subj = subject or PLACEHOLDER[m.subject_kind]
        req = (m.params_schema or {}).get("required") or []
        props = (m.params_schema or {}).get("properties") or {}
        params = ", ".join(f"'{k}': {_stub(props.get(k, {}), k)}" for k in req)
        tail = f", params={{{params}}}" if params else ""
        return f"compute(method='{entry.name}', subject='{subj}'{tail})"
    if entry.kind == "op":
        return f"compute(op='{entry.name}', operands=['<f_…>', '<f_…>'])"
    if entry.kind == "filed line":
        return f"read_fundamentals('{subject or '<ticker>'}', metric='{entry.name}')"
    if entry.kind == "filing item":
        return f"read_filings('{subject or '<ticker>'}', item='{entry.name}')"
    if entry.kind == "section":
        r = ref or PLACEHOLDER["run" if "run" in entry.on and "portfolio" not in entry.on else "portfolio"]
        return f"read_book('{r}', names=['{entry.name}'])"
    if entry.kind == "domain":
        return f"describe('{subject or PLACEHOLDER[entry.subject_kind or 'portfolio']}', expand='{entry.name}')"
    if entry.kind == "view":
        return f"describe('{subject or '<subject>'}', expand='{entry.name}')"
    raise ValueError(entry.kind)


def route(name: str, subject: str | None = None, ref: str | None = None) -> dict | None:
    """'This is X, used as Y' for a name the table knows; None otherwise."""
    e = TABLE.get(name)
    if e is None:
        return None
    return {"name": e.name, "is": e.kind, "call": call(e, subject, ref)}


def nearest(name: str, n: int = 5, subject: str | None = None) -> list[dict]:
    """The closest names across every kind, each with what it is and its call."""
    close = difflib.get_close_matches(name, list(TABLE), n=n, cutoff=0.5)
    return [route(c, subject) for c in close]


def row(entry: Entry, subject: str | None = None, ref: str | None = None) -> dict:
    """The catalogue's entry for a name: name, what it is, one line, the call."""
    out = {"name": entry.name, "is": entry.kind, "does": entry.does, "call": call(entry, subject, ref)}
    if entry.kind.endswith(" method"):
        m = skill.METHODS[entry.name]
        props = list((m.params_schema or {}).get("properties") or {})
        if props:
            out["params"] = props
        if m.yields and list(m.yields) != [entry.name]:
            out["yields"] = list(m.yields)
    return out
