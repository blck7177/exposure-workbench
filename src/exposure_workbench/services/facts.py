"""The Fact (V24): a figure that carries its own identity, built once at the tool
boundary and never rebuilt.

WHY THIS EXISTS. Until V24 a tool returned a number in whatever shape its
service had, and its identity — name, unit, what it was about, as of when —
was reconstructed later by reading the storage row back (services/quantities),
once for the slice the model read and once for the table the gate checked.
Every new kind of row needed a new branch of that reconstruction, and every
branch it lacked was a small failure the batteries met one at a time
(IMPLEMENTATION_PLAN_V24 §2). A Fact is the same information decided ONCE, by
the adapter that knows the tool's payload (services/fact_adapters), and carried
as an object from there: to the model, onto the step, into the `facts` table,
through the gate, to the reader.

TWO FORMS, ONE OBJECT. `for_record` is the whole Fact, full precision — what
the `facts` table and the evidence drawer hold. The model form is compact: a
result's facts as one block with the columns declared once and one row per
fact, the value at reader precision (analytics/display_conventions), a series
thinned to SERIES_POINTS_INLINE points, a passage cut at PASSAGE_CHARS. The
gate loads what the step recorded — the model form — so the set the model
could point at and the set the gate holds are the same JSON, by construction.

WHAT A FACT IS NOT. It is not a storage row: `sources` names the rows it rests
on (fact_/calc_/chunk_/src_/run_/alert_/task_ ids), which is the drawer's path
down. It is not a name: the model points at the id, never spells the measure.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterable, Sequence

from exposure_workbench.analytics import display_conventions as dc
from exposure_workbench.utils.ids import new_id

# ── kinds ─────────────────────────────────────────────────────────────────────
SCALAR = "scalar"
SERIES = "series"
PASSAGE = "passage"
ABSENCE = "absence"
TASK = "task"
KINDS = (SCALAR, SERIES, PASSAGE, ABSENCE, TASK)

# ── the id ────────────────────────────────────────────────────────────────────
PREFIX = "f_"


def new_fact_id() -> str:
    return new_id(PREFIX)


def is_fact_id(s: Any) -> bool:
    return isinstance(s, str) and s.startswith(PREFIX) and len(s) > len(PREFIX)


# ── ceilings (IMPLEMENTATION_PLAN_V24 §9, measured 2026-09-05) ────────────────
FACTS_CHAR_LIMIT = 24_000      # the model form of one result's facts (§9: book.analysis is 146 facts)
FACTS_PER_RESULT = 200         # facts in one result before held_back
SERIES_POINTS_INLINE = 60      # points a series shows the model
PASSAGE_CHARS = 12_000         # text a passage shows the model


@dataclass(frozen=True)
class Fact:
    id: str
    kind: str
    measure: str                                  # what it is: net_margin | issuer_exposures.weight | "Item 7"
    subject: str | None = None                    # MSFT | port_… | run_… | None for the desk
    unit: str | None = None                       # RATIO | MONEY | COUNT | MULTIPLE | MONEY_PER_SHARE | None
    value: float | None = None                    # scalar
    points: tuple[tuple[str, float], ...] | None = None   # series: (period, value)
    text: str | None = None                       # passage text | absence statement | task state
    as_of: str | None = None
    window: dict | None = None                    # {"start","end"} | {"months"} | {"days"} | {"name"}
    params: dict = field(default_factory=dict)    # confidence, benchmark, rank, method params, episode dates
    standalone: bool = True                       # False: citable, may not stand alone (collinear coefficient)
    sources: tuple[str, ...] = ()                 # the rows it rests on — the drawer's path
    group: str = "other"                          # the M2 question key

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"fact {self.id}: unknown kind {self.kind!r}")
        if self.kind == SCALAR and self.value is None:
            raise ValueError(f"fact {self.id} ({self.measure}): a scalar has a value")
        if self.kind == SERIES and not self.points:
            raise ValueError(f"fact {self.id} ({self.measure}): a series has points")
        if self.kind in (PASSAGE, ABSENCE, TASK) and not self.text:
            raise ValueError(f"fact {self.id} ({self.measure}): a {self.kind} has text")


def fact(kind: str, measure: str, **fields) -> Fact:
    """A Fact with a fresh id."""
    return Fact(id=new_fact_id(), kind=kind, measure=measure, **fields)


# ── the record form ───────────────────────────────────────────────────────────

def for_record(f: Fact) -> dict:
    d = asdict(f)
    d["points"] = [list(p) for p in f.points] if f.points else None
    d["sources"] = list(f.sources)
    return d


def from_record(d: dict) -> Fact:
    d = dict(d)
    if d.get("points"):
        d["points"] = tuple((str(p[0]), float(p[1])) for p in d["points"])
    d["sources"] = tuple(d.get("sources") or ())
    d["params"] = dict(d.get("params") or {})
    return Fact(**d)


# ── the model form ────────────────────────────────────────────────────────────
# Columns declared once per result; one row per fact. Nothing is lifted to the
# result: the ledger loads rows on their own and a row must stand alone. What
# is compact is the absence of keys, not of fields.
COLUMNS = ("id", "kind", "subject", "measure", "unit", "value", "as_of", "window", "params", "sources")


def _thin(points: Sequence[tuple[str, float]], n: int) -> list:
    """First, last, min and max always; the rest evenly thinned."""
    if len(points) <= n:
        return [list(p) for p in points]
    vals = [v for _, v in points]
    must = {0, len(points) - 1, vals.index(min(vals)), vals.index(max(vals))}
    last = len(points) - 1
    even = [round(i * last / (n - 1)) for i in range(n)]
    keep = set(must)
    for k in even:                       # evenly spaced, until n are kept
        if len(keep) >= n:
            break
        keep.add(k)
    for k in range(len(points)):         # rounding collisions: fill from the left
        if len(keep) >= n:
            break
        keep.add(k)
    return [list(points[k]) for k in sorted(keep)]


def _model_value(f: Fact) -> Any:
    if f.kind == SCALAR:
        return dc.reader_value(f.value, f.unit) if f.unit else f.value
    if f.kind == SERIES:
        shown = _thin(f.points, SERIES_POINTS_INLINE)
        if f.unit:
            shown = [[p, dc.reader_value(v, f.unit)] for p, v in shown]
        out: dict = {"points": shown, "n": len(f.points)}
        if len(shown) < len(f.points):
            out["shown"] = f"{len(shown)} of {len(f.points)}; the record holds every point"
        return out
    text = f.text or ""
    if f.kind == PASSAGE and len(text) > PASSAGE_CHARS:
        return {"text": text[:PASSAGE_CHARS], "truncated": f"{len(text)} characters; the drawer holds the whole passage"}
    return text


def row_for_model(f: Fact) -> list:
    """One fact as the model reads it — the same object the ledger loads."""
    params = {**f.params, **({"standalone": False} if not f.standalone else {})}
    return [f.id, f.kind, f.subject, f.measure, f.unit, _model_value(f), f.as_of,
            f.window, params or None, list(f.sources)]


def block_for_model(facts: Sequence[Fact]) -> dict:
    """The result's facts as the model reads them. When every fact rests on the
    same sources (a run's 146 figures all rest on the run), the list is stated
    once on the block and the rows carry `[]` — measured 38 characters a row
    (§9). The record form never lifts anything."""
    rows = [row_for_model(f) for f in facts]
    shared = None
    if len(facts) > 1 and len({f.sources for f in facts}) == 1 and facts[0].sources:
        shared = list(facts[0].sources)
        for r in rows:
            r[-1] = []
    out = {"columns": list(COLUMNS), "rows": rows}
    if shared:
        out["sources"] = shared
    return out


def from_model_row(row: Sequence, shared_sources: Sequence[str] | None = None) -> dict:
    """The model-form row as a dict keyed by COLUMNS (what the ledger indexes)."""
    d = dict(zip(COLUMNS, row))
    if not d.get("sources") and shared_sources:
        d["sources"] = list(shared_sources)
    params = dict(d.get("params") or {})
    d["standalone"] = params.pop("standalone", True)
    d["params"] = params
    return d


# ── caps ──────────────────────────────────────────────────────────────────────

def cap(facts: list[Fact], *, per_result: int = FACTS_PER_RESULT,
        char_limit: int = FACTS_CHAR_LIMIT) -> tuple[list[Fact], dict | None]:
    """The facts a result may show, and what was held back.

    Whole facts come off the tail; a fact is never cut. `held_back` names how
    many and which measures — the adapter that knows the tool adds WHICH call
    reads them by name (services/fact_adapters).
    """
    kept = list(facts[:per_result])
    while kept and len(json.dumps(block_for_model(kept))) > char_limit:
        kept.pop()
    if len(kept) == len(facts):
        return kept, None
    dropped = facts[len(kept):]
    return kept, {"count": len(dropped),
                  "measures": sorted({f"{d.subject or ''}:{d.measure}".strip(":") for d in dropped})[:40]}


def json_size(facts: Sequence[Fact]) -> int:
    return len(json.dumps(block_for_model(facts)))


def with_sources(f: Fact, more: Iterable[str]) -> Fact:
    seen = list(f.sources)
    for s in more:
        if isinstance(s, str) and s and s not in seen:
            seen.append(s)
    return replace(f, sources=tuple(seen))
