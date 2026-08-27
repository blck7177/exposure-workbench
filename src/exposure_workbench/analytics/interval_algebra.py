"""Any window from the intervals an issuer actually reported. Pure.

A flow fact covers a half-open interval `(period_start − 1 day, period_end]`.
Put every reported interval on a line and its two ends are BOUNDARIES; the fact
is an edge between them carrying a value. Flows add across adjacent intervals
(V9 axiom R1), so an edge may be walked forwards (+) or backwards (−), and the
value of any window is the signed sum along a path between its two boundaries.

That single idea replaces a pile of special cases:

    Q4  = FY − 9M                 (period_ladder.derive_q4, as a path)
    Q2  = H1 − Q1
    TTM = FY − H1(prior) + H1     (AAPL: 111.482 − 53.887 + 82.627 = 140.222)

and it needs no rule about which issuer files what. AAPL reports cash flow
cumulatively from the year's start, MSFT reports discrete quarters; the search
finds a path in both without being told, because the difference between them is
a fact about their filings, not about accounting.

Shortest path wins. Every edge is an input that could be restated or misread, so
a two-term derivation is preferred to a five-term one for the same window.

What this module will NOT do: bridge a genuine hole. A boundary tolerance exists
only for 52/53-week fiscal calendars, where one period's end and the next one's
start miss each other by a day or two and are plainly the same seam. Anything
wider is a gap, and a gap makes a window unreachable rather than approximate.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import date, timedelta

from exposure_workbench.analytics.period_ladder import restatement_key

# 52/53-week filers move their year end by up to a week; two boundaries this
# close are the same seam. Wider than a week would start swallowing real gaps —
# the shortest real reporting period here is a quarter.
BOUNDARY_TOLERANCE_DAYS = 6
# What "a month" is worth when snapping a requested window to real boundaries.
_DAYS_PER_MONTH = 30.44
# A requested window may land this far from a reported boundary and still be
# considered that boundary: a quarter's worth of slack would let a request for
# twelve months be answered with nine.
WINDOW_SNAP_DAYS = 20


@dataclass(frozen=True)
class FlowFact:
    """One as-reported flow. `period_start`/`period_end` are inclusive dates, as
    stored; the interval it covers is `(period_start − 1 day, period_end]`."""

    fact_id: str
    period_start: date
    period_end: date
    value: float
    # Carried so a restatement can be resolved the same way the ladder resolves
    # one. Without it the graph holds every version of a period as a separate
    # edge and the search takes whichever it reaches first — measured: 7 of 290
    # derived Q4 values came out different from the ladder's, including a sign
    # flip on NVDA.
    filing_date: date | None = None
    source_accession: str | None = None

    @property
    def lo(self) -> date:
        return self.period_start - timedelta(days=1)

    @property
    def hi(self) -> date:
        return self.period_end


@dataclass(frozen=True)
class Derived:
    """A window, and the signed facts it was built from."""

    value: float
    start: date                                   # first day covered
    end: date                                     # last day covered
    terms: tuple[tuple[str, int], ...]            # (fact_id, +1 | -1)
    formula: str                                  # human-readable path
    fact_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Unreachable:
    """No signed path spans the requested window. Carries no value: a window
    that could not be derived must not be reported as a shorter one."""

    reason: str
    nearest_start: date | None = None
    nearest_end: date | None = None


Window = Derived | Unreachable


# ── boundaries ────────────────────────────────────────────────────────────────

def _clusters(dates: list[date]) -> list[list[date]]:
    """Single-linkage grouping of boundary dates within the tolerance."""
    out: list[list[date]] = []
    for d in sorted(set(dates)):
        if out and (d - out[-1][-1]).days <= BOUNDARY_TOLERANCE_DAYS:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def _boundary_map(facts: list[FlowFact]) -> dict[date, date]:
    """Every boundary date -> the canonical date of its cluster."""
    groups = _clusters([b for f in facts for b in (f.lo, f.hi)])
    return {d: g[0] for g in groups for d in g}


def _snap(target: date, canon: dict[date, date], *, tolerance: int) -> date | None:
    best, best_gap = None, tolerance + 1
    for raw, c in canon.items():
        gap = abs((raw - target).days)
        if gap < best_gap:
            best, best_gap = c, gap
    return best


def _describe(facts_by_id: dict[str, FlowFact], terms: tuple[tuple[str, int], ...]) -> str:
    parts = []
    for i, (fid, sign) in enumerate(terms):
        f = facts_by_id[fid]
        span = f"{f.period_start.isoformat()}..{f.period_end.isoformat()}"
        if i == 0:
            parts.append(span if sign > 0 else f"−{span}")
        else:
            parts.append(f"{'+' if sign > 0 else '−'} {span}")
    return " ".join(parts)


# ── the search ────────────────────────────────────────────────────────────────

def derive(facts: list[FlowFact], start: date, end: date) -> Window:
    """The value over `[start, end]`, or why it cannot be had.

    `start` and `end` are inclusive days: the interval is (start − 1 day, end].
    """
    usable = [f for f in facts if f.value is not None and f.period_start is not None]
    if not usable:
        return Unreachable(reason="no flow facts for this metric")

    canon = _boundary_map(usable)
    src = _snap(start - timedelta(days=1), canon, tolerance=BOUNDARY_TOLERANCE_DAYS)
    dst = _snap(end, canon, tolerance=BOUNDARY_TOLERANCE_DAYS)
    known = sorted({c for c in canon.values()})
    if src is None or dst is None:
        missing = start.isoformat() if src is None else end.isoformat()
        return Unreachable(
            reason=(f"no reported period boundary near {missing}; the data spans "
                    f"{known[0].isoformat()}..{known[-1].isoformat()}"),
            nearest_start=known[0], nearest_end=known[-1],
        )
    if src == dst:
        return Unreachable(reason="the requested window is empty")

    # One edge per interval. An interval reported more than once is a
    # restatement, and the most recently filed version is the one that counts —
    # the same rule build_ladder applies, imported rather than rewritten. Left
    # as parallel edges, the search would pick between two versions of the same
    # period by fact id, which is to say arbitrarily.
    chosen: dict[tuple[date, date], FlowFact] = {}
    for f in usable:
        key = (canon[f.lo], canon[f.hi])
        prev = chosen.get(key)
        if prev is None or restatement_key(f.filing_date, f.source_accession) > \
                restatement_key(prev.filing_date, prev.source_accession):
            chosen[key] = f

    facts_by_id = {f.fact_id: f for f in chosen.values()}
    adj: dict[date, list[tuple[date, str, int]]] = {}
    for (a, b), f in chosen.items():
        if a == b:
            continue                      # a zero-length interval carries nothing
        adj.setdefault(a, []).append((b, f.fact_id, +1))
        adj.setdefault(b, []).append((a, f.fact_id, -1))

    # Dijkstra on edge count. Ties broken by the fact ids so the same corpus
    # always yields the same derivation — a number whose formula changes between
    # identical runs cannot be checked by a reader.
    seen: set[date] = set()
    queue: list[tuple[int, list[tuple[str, int]], date]] = [(0, [], src)]
    while queue:
        cost, path, node = heapq.heappop(queue)
        if node in seen:
            continue
        seen.add(node)
        if node == dst:
            terms = tuple(path)
            value = sum(facts_by_id[fid].value * sign for fid, sign in terms)
            return Derived(
                value=value,
                start=start, end=end,
                terms=terms,
                formula=_describe(facts_by_id, terms),
                fact_ids=tuple(fid for fid, _s in terms),
            )
        used = {fid for fid, _s in path}
        for nxt, fid, sign in sorted(adj.get(node, []), key=lambda e: e[1]):
            if nxt in seen or fid in used:
                continue
            heapq.heappush(queue, (cost + 1, path + [(fid, sign)], nxt))

    return Unreachable(
        reason=(f"no path of reported periods spans {start.isoformat()}..{end.isoformat()}; "
                f"there is a gap the filings do not cover"),
        nearest_start=known[0], nearest_end=known[-1],
    )


def latest_window(facts: list[FlowFact], months: int = 12) -> Window:
    """The most recent `months`-long window this issuer's filings can support.

    Deliberately not "TTM, or a fiscal year if that fails". A shorter period
    served under a twelve-month name is the silent convention switch this design
    exists to remove; the window that comes back is the window that was derived,
    with both its dates.
    """
    usable = [f for f in facts if f.value is not None and f.period_start is not None]
    if not usable:
        return Unreachable(reason="no flow facts for this metric")

    canon = _boundary_map(usable)
    ends = sorted({c for c in canon.values()}, reverse=True)
    span = timedelta(days=round(months * _DAYS_PER_MONTH))
    attempts: list[str] = []
    for end in ends:
        src = _snap(end - span, canon, tolerance=WINDOW_SNAP_DAYS)
        if src is None or src >= end:
            continue
        got = derive(usable, src + timedelta(days=1), end)
        if isinstance(got, Derived):
            return got
        attempts.append(f"{end.isoformat()}: {got.reason}")
    return Unreachable(
        reason=(f"no {months}-month window can be derived from the reported periods"
                + (f" (tried {len(attempts)} end dates)" if attempts else "")),
        nearest_end=ends[0] if ends else None,
    )
