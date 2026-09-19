"""The name table (V27, re-cut for V1): every name a model can write into a tool
argument, with what it is and which VERB takes it — one table behind the tools'
enums and every unknown-name refusal.

The 2026-09-07 battery: 110 method names sent to the book read, 34 filed lines
sent to compute, ~38 method names sent to the fundamentals read, in 244 turns.
Which tool consumes which name was something the model had to remember. This
module is that binding as data: a name written at the wrong door is told what it
is and the door that takes it, instead of the nearest spelling of something else.

It is a VIEW over its owners (the registry's measures, the concept map's filed
lines, the run's declared tables, the calculator's ops) — nothing is declared
twice — and a name that appears under two kinds is an import-time error, so the
answer to "what is X" is always one thing.

Imports only analytics and the pure concept map: the tool registry reads this
module, and compute_service reads the registry, so nothing here may reach a
service that reaches the registry.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from exposure_workbench.analytics import registry, resources, series_ops
from exposure_workbench.services import concept_mapping as cm

# The Items a filing is read by (FilingSection.item_code, as the desk indexes them).
FILING_ITEMS: tuple[str, ...] = ("1", "1A", "2", "3", "7", "7A", "8", "9A")

PLACEHOLDER = {"issuer": "<ticker>", "price": "<ticker>", "run": "<run_…>", "portfolio": "<port_…>",
               "scenario": "<calc_…>", "series": "<f_…>"}


@dataclass(frozen=True)
class Entry:
    name: str
    kind: str            # what the model is told it IS: "issuer measure", "filed line", …
    consumer: str        # the verb that takes it (tools/primitives)
    does: str            # one line
    subject_kind: str | None = None   # for measures: what `subject` must be


def _build() -> dict[str, Entry]:
    table: dict[str, Entry] = {}

    def put(e: Entry) -> None:
        if e.name in table and table[e.name].kind != e.kind:
            raise RuntimeError(f"name table: {e.name!r} is both {table[e.name].kind} and {e.kind}")
        table[e.name] = e

    for m in registry.METHODS.values():
        verb = "scenario" if m.executor in ("book.sell", "book.buy") else "metric"
        put(Entry(m.name, f"{m.subject_kind} measure", verb, m.describes, subject_kind=m.subject_kind))
    for n in cm.SUPPORTED_METRICS:
        put(Entry(n, "filed line", "filings_read", "a line as the issuer filed it, by period"))
    for r in resources.RUN_CHILDREN:
        put(Entry(r.table, "book table", "book_read", f"a run's {r.table.replace('_', ' ')}"))
    for n in FILING_ITEMS:
        put(Entry(n, "filing item", "filings_section", f"Item {n} of the latest filing, a page at a time"))
    for n in (registry.SCALAR_OPS + (registry.SCALE_OP, registry.RANK_OP) + tuple(series_ops.CHANGE_MODES)
              + tuple(series_ops.STAT_OPS)):
        put(Entry(n, "op", "calc", "one operation over figures already shown, by their ids"))
    return table


TABLE: dict[str, Entry] = _build()
TABLE_FILED_LINES: tuple[str, ...] = tuple(cm.SUPPORTED_METRICS)


def get(name: str) -> Entry | None:
    return TABLE.get(name)


def method_names(kinds: tuple[str, ...]) -> list[str]:
    """The measures of some subject kinds, in registry order."""
    return [m.name for m in registry.METHODS.values() if m.subject_kind in kinds]


def call(entry: Entry, subject: str | None = None, ref: str | None = None) -> str:
    """How the name is used: the verb that takes it, with the argument it goes in."""
    if entry.consumer == "metric":
        subj = subject or PLACEHOLDER[registry.METHODS[entry.name].subject_kind]
        return f"metric(name='{entry.name}', subject='{subj}')"
    if entry.consumer == "scenario":
        return f"scenario(book='{ref or '<a book>'}', {'sales' if entry.name.endswith('sell') else 'buys'}=[…])"
    if entry.kind == "op":
        return f"calc(op='{entry.name}', inputs=[<f_… ids>])"
    if entry.kind == "filed line":
        return f"filings_read(ticker='{subject or '<ticker>'}', line='{entry.name}')"
    if entry.kind == "filing item":
        return f"filings_section(ticker='{subject or '<ticker>'}', item='{entry.name}')"
    if entry.kind == "book table":
        return f"book_read(book='{ref or '<a book>'}', table='{entry.name}')"
    raise ValueError(entry.kind)


def route(name: str, subject: str | None = None, ref: str | None = None) -> dict | None:
    """'This is X, and this verb takes it' for a name the table knows; None otherwise."""
    e = TABLE.get(name)
    if e is None:
        return None
    return {"name": e.name, "is": e.kind, "call": call(e, subject, ref)}


def nearest(name: str, n: int = 5, subject: str | None = None) -> list[dict]:
    """The closest names across every kind, each with what it is and its verb."""
    close = difflib.get_close_matches(name, list(TABLE), n=n, cutoff=0.5)
    return [route(c, subject) for c in close]
