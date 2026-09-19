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
from exposure_workbench.analytics import registry
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
    unit: str | None = None                       # RATIO | MONEY | COUNT | MULTIPLE | MONEY_PER_SHARE | MONEY_PER_DAY | COUNT_PER_DAY | None
    value: float | None = None                    # scalar
    points: tuple[tuple[str, float], ...] | None = None   # series: (period, value)
    text: str | None = None                       # passage text | absence statement | task state
    as_of: str | None = None
    window: dict | None = None                    # {"start","end"} | {"months"} | {"days"} | {"name"}
    params: dict = field(default_factory=dict)    # confidence, benchmark, rank, method params, episode dates
    standalone: bool = True                       # False: citable, may not stand alone (collinear coefficient)
    sources: tuple[str, ...] = ()                 # the rows it rests on — the drawer's path
    group: str = "other"                          # the M2 question key
    # V1: what the reading MEANS, in the registry's closed vocabulary — the
    # direction of an exposure, a check's status, a basis, a flag, an absence's
    # reason and way out. Only what the row cannot derive (analytics/registry).
    means: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"fact {self.id}: unknown kind {self.kind!r}")
        try:
            object.__setattr__(self, "means", registry.validate_means(self.means))
        except ValueError as exc:
            raise ValueError(f"fact {self.id} ({self.measure}): {exc}") from None
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
    d["means"] = dict(d.get("means") or {})       # a record from before V1 has none
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


# ── the row a reader is shown (V1) ────────────────────────────────────────────
#
# Eight fields, every one a thing a trained analyst reads without a legend, and
# one line made of them:
#
#     [f_…] what, of, when: value — means — from
#
# The analyst reads it, the ledger stores the row it is made from, the lead
# quotes it, the check resolves against it and the reader opens it: one row, and
# the line is a PURE FUNCTION of that stored row (tests pin it). Nothing here
# is stored twice — `what` is the measure's financial name, `when` the period
# the row actually has, `means` the registry's words (analytics/registry).
ROW_FIELDS = ("id", "kind", "what", "of", "when", "value", "means", "from")
_KIND_WORDS = {SCALAR: "reading", SERIES: "series", PASSAGE: "passage", ABSENCE: "absence", TASK: "task"}


def _record_of(f: "Fact | dict") -> dict:
    return for_record(f) if isinstance(f, Fact) else f


def when_of(rec: dict) -> str:
    """The period the row HAS, as words: a series' spacing and reach, a window's
    two dates, a flow's months up to its date, an instant."""
    if rec.get("kind") == SERIES and rec.get("points"):
        pts = rec["points"]
        spacing = spacing_of(pts)
        return ", ".join(x for x in (spacing, f"{pts[0][0]} to {pts[-1][0]}", f"{len(pts)} points") if x)
    as_of = rec.get("as_of") if rec.get("as_of") not in (None, "", "n/a") else None
    w = rec.get("window") or {}
    if w.get("start") and w.get("end"):
        return f"{w['start']} to {w['end']}"
    if w.get("instant"):
        return f"at {w['instant']}"
    for key, word in (("months", "months"), ("days", "sessions")):
        if isinstance(w.get(key), (int, float)) and not isinstance(w.get(key), bool):
            return f"{w[key]:g} {word}" + (f" to {as_of}" if as_of else "")
    if isinstance(w.get("name"), str) and w["name"]:
        return w["name"] + (f" to {as_of}" if as_of else "")
    return f"as of {as_of}" if as_of else ""


def value_of(rec: dict) -> str:
    """The value as displayed, unit in the writing (analytics/display_conventions)."""
    kind, unit = rec.get("kind"), rec.get("unit")
    if kind == SCALAR:
        v = rec.get("value")
        return dc.display(float(v), unit) if unit and isinstance(v, (int, float)) else str(v)
    if kind == SERIES:
        pts = _thin([(str(p[0]), float(p[1])) for p in rec.get("points") or []], SERIES_POINTS_INLINE)
        return "; ".join(f"{p} {dc.display(v, unit) if unit else v}" for p, v in pts)
    if kind == PASSAGE:
        text = str(rec.get("text") or "")
        return '"' + text[:PASSAGE_CHARS] + ('…"' if len(text) > PASSAGE_CHARS else '"')
    if kind == TASK:
        return str(rec.get("text") or "")
    return "—"


def from_of(rec: dict) -> str:
    """Where the row came from: the method or operation that made it, else the
    row it was read off."""
    params = rec.get("params") or {}
    if params.get("method"):
        return f"method {params['method']}"
    if params.get("op"):
        return f"op {params['op']}"
    sources = [s for s in rec.get("sources") or [] if isinstance(s, str)]
    if sources:
        return ", ".join(sources[:2])
    return str(rec.get("group") or "")


def model_row(f: "Fact | dict") -> dict:
    """The eight fields of one row, from the stored record."""
    rec = _record_of(f)
    return {"id": rec.get("id"), "kind": _KIND_WORDS.get(rec.get("kind"), rec.get("kind")),
            "what": registry.reads_as(rec.get("measure")), "of": rec.get("subject") or "",
            "when": when_of(rec), "value": value_of(rec), "means": registry.means_words(rec),
            "from": from_of(rec)}


def line(f: "Fact | dict") -> str:
    """One row as the line a reader is shown. No legend goes with it."""
    r = model_row(f)
    head = ", ".join(x for x in (r["what"], r["of"], r["when"]) if x)
    if r["kind"] == "absence":
        head = f"absent: {head}"
    tail = " — ".join(x for x in (r["value"], r["means"], r["from"]) if x)
    return f"[{r['id']}] {head}: {tail}"


def lines(facts: Sequence["Fact | dict"]) -> str:
    return "\n".join(line(f) for f in facts)


# ── caps ──────────────────────────────────────────────────────────────────────

def cap(facts: list[Fact], *, per_result: int = FACTS_PER_RESULT,
        char_limit: int = FACTS_CHAR_LIMIT) -> tuple[list[Fact], dict | None]:
    """The facts a result may show, and what was held back.

    Whole facts come off the tail; a fact is never cut. `held_back` names how
    many and which measures — the adapter that knows the tool adds WHICH call
    reads them by name (services/fact_adapters).

    A REFUSAL IS NEVER HELD BACK (V38/T2). The cap is a bound on how much a
    reader is given to read, and "this was not computed, and why" is not more
    of the same reading: it is the other half of what the result is. It was
    capped like a figure, and an absence is minted where its node stands — often
    after a whole table — so round C held back 72 of them; both analysts who
    tried to buy TLT never read that the buy was refused. Refusals are kept in
    place and not counted; the rest is capped as before.
    """
    rest = [f for f in facts if f.kind != ABSENCE]
    kept_rest = list(rest[:per_result])
    while kept_rest and len(json.dumps(block_for_model(kept_rest))) > char_limit:
        kept_rest.pop()
    if len(kept_rest) == len(rest):
        return list(facts), None
    keep = {f.id for f in kept_rest}
    kept = [f for f in facts if f.kind == ABSENCE or f.id in keep]
    dropped = rest[len(kept_rest):]
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


# ── how a series' own dates read (V37) ────────────────────────────────────────
#
# Five of round B's eleven false statements were one class: a sentence naming a
# period its evidence does not have — "the last twelve quarter readings" of a
# six-point ANNUAL series, with the six annual dates printed in the sentence's
# own brackets. The series carries its points, so the period it has is a lookup
# and not a judgement. Here because a Fact's points are a Fact's business, and
# because two readers need it: the answer check, and the digest that shows an
# analyst what it fetched.

_DAYS = {"daily": 1.0, "weekly": 7.0, "monthly": 30.44, "quarterly": 91.31, "annual": 365.25}
# The widest gap that still reads as each spacing, in days. A quarter is 90–92
# days and a fiscal year 363–371, so the bands are wide enough for a filer's own
# calendar and narrow enough to keep two spacings apart.
_BANDS = ((3.0, "daily"), (10.0, "weekly"), (45.0, "monthly"), (200.0, "quarterly"), (500.0, "annual"))


def _dates(points) -> list[str]:
    return sorted(str(p[0]) for p in (points or []) if p and str(p[0])[:4].isdigit())


def _ordinal(d: str) -> int | None:
    """A date as a day number, for a gap. `datetime` rather than a parse of our
    own: the points are ISO by construction (program_service writes them)."""
    from datetime import date
    try:
        return date.fromisoformat(d[:10]).toordinal()
    except ValueError:
        return None


def spacing_of(points) -> str | None:
    """`daily | weekly | monthly | quarterly | annual`, or None when the points
    cannot say — fewer than two of them, or gaps that are not one cadence.

    The MEDIAN gap, so one missing filing in eight quarters does not make a
    series annual; None rather than a guess, because a rule that fires on a
    guess refuses true sentences."""
    days = [d for d in (_ordinal(x) for x in _dates(points)) if d is not None]
    if len(days) < 2:
        return None
    gaps = sorted(b - a for a, b in zip(days, days[1:]))
    mid = gaps[len(gaps) // 2] if len(gaps) % 2 else (gaps[len(gaps) // 2 - 1] + gaps[len(gaps) // 2]) / 2
    return next((name for edge, name in _BANDS if mid <= edge), None)


def extent_in(points, unit: str) -> float | None:
    """How far the points reach, in `unit` (one of `_DAYS`). None when there is
    nothing to measure."""
    days = [d for d in (_ordinal(x) for x in _dates(points)) if d is not None]
    if len(days) < 2 or unit not in _DAYS:
        return None
    return (days[-1] - days[0]) / _DAYS[unit]
