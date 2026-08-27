"""Calculation algebra (M3) — the closed primitive set.

Four orthogonal operations. Expressiveness comes from COMPOSING them, not from
adding more:
    margin        = combine(gross_profit, revenue, "divide")
    free cash flow= combine(ocf, capex, "sub")
    growth        = change(series, "yoy")
    CAGR          = stat(series, "cagr")
    event return  = window_return(prices, window)

Adding a primitive is an architecture decision, not a convenience. There is
deliberately no generic "eval expression" escape hatch: every number an agent
can quote must come from a named, replayable operation.

Pure functions. Missing inputs produce None plus a quality flag — never
interpolated, never carried forward, never zero-filled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

PRIMITIVE_VERSION = "v2"   # v2: yoy/qoq match by date, not list position

CHANGE_MODES = ("yoy", "qoq", "pct", "abs")
STAT_OPS = ("cagr", "avg", "min", "max", "std", "sum", "latest")


@dataclass(frozen=True)
class SeriesPoint:
    period_end: date
    value: float | None
    input_fact_ids: list[str] = field(default_factory=list)
    quality_flags: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SeriesResult:
    operation: str
    points: list[SeriesPoint] = field(default_factory=list)
    quality_flags: dict = field(default_factory=dict)
    primitive_version: str = PRIMITIVE_VERSION

    def input_fact_ids(self) -> list[str]:
        seen: list[str] = []
        for p in self.points:
            for fid in p.input_fact_ids:
                if fid not in seen:
                    seen.append(fid)
        return seen


@dataclass(frozen=True)
class ScalarResult:
    operation: str
    value: float | None
    input_fact_ids: list[str] = field(default_factory=list)
    quality_flags: dict = field(default_factory=dict)
    primitive_version: str = PRIMITIVE_VERSION


# ── change ─────────────────────────────────────────────────────────────────────

# yoy/qoq are matched BY DATE, not by list position. Financial series are often
# sparse or irregular — e.g. cash-flow metrics are filed cumulatively, so a
# company's "quarterly" operating-cash-flow series can contain only Q1 of each
# year. Positional lag then silently compares points four YEARS apart and
# reports it as year-over-year growth (measured: a bogus 2808%). Matching on
# dates makes an unmatched period visibly absent instead of quietly wrong.
YOY_DAYS, YOY_TOLERANCE = 365, 45
QOQ_DAYS, QOQ_TOLERANCE = 91, 25


def _nearest_prior(ordered: list[SeriesPoint], idx: int, back_days: int, tolerance: int):
    """The earlier point closest to (period_end - back_days), within tolerance."""
    target = ordered[idx].period_end - timedelta(days=back_days)
    best, best_gap = None, None
    for p in ordered[:idx]:
        gap = abs((p.period_end - target).days)
        if gap <= tolerance and (best_gap is None or gap < best_gap):
            best, best_gap = p, gap
    return best


def compute_change(series: list[SeriesPoint], mode: str) -> SeriesResult:
    """yoy / qoq match by date; pct / abs compare with the immediately prior point."""
    if mode not in CHANGE_MODES:
        raise ValueError(f"unsupported change mode {mode!r}")

    ordered = sorted(series, key=lambda p: p.period_end)
    points: list[SeriesPoint] = []
    zero_base = 0
    unmatched = 0

    for i in range(len(ordered)):
        cur = ordered[i]
        if mode == "yoy":
            prev = _nearest_prior(ordered, i, YOY_DAYS, YOY_TOLERANCE)
        elif mode == "qoq":
            prev = _nearest_prior(ordered, i, QOQ_DAYS, QOQ_TOLERANCE)
        else:
            prev = ordered[i - 1] if i >= 1 else None

        if prev is None:
            if i > 0 or mode in ("yoy", "qoq"):
                unmatched += 1
            continue

        ids = cur.input_fact_ids + prev.input_fact_ids
        if cur.value is None or prev.value is None:
            points.append(SeriesPoint(cur.period_end, None, ids, {"missing_input": True}))
            continue
        if mode == "abs":
            v = cur.value - prev.value
        else:
            if prev.value == 0:
                zero_base += 1
                points.append(SeriesPoint(cur.period_end, None, ids, {"zero_base": True}))
                continue
            v = (cur.value - prev.value) / abs(prev.value)
        points.append(SeriesPoint(cur.period_end, v, ids))

    flags: dict = {}
    if not points:
        flags["insufficient_history"] = {"mode": mode, "have": len(ordered)}
    if unmatched:
        flags["periods_without_comparable_prior"] = unmatched
    if zero_base:
        flags["zero_base_periods"] = zero_base
    return SeriesResult(operation=f"change.{mode}", points=points, quality_flags=flags)


# ── stat ───────────────────────────────────────────────────────────────────────

def compute_stat(series: list[SeriesPoint], op: str) -> ScalarResult:
    if op not in STAT_OPS:
        raise ValueError(f"unsupported stat op {op!r}")

    ordered = sorted(series, key=lambda p: p.period_end)
    vals = [(p.period_end, p.value, p.input_fact_ids) for p in ordered if p.value is not None]
    ids = [fid for _, _, fl in vals for fid in fl]
    flags: dict = {}
    dropped = len(ordered) - len(vals)
    if dropped:
        flags["skipped_missing_points"] = dropped
    if not vals:
        flags["no_values"] = True
        return ScalarResult(operation=f"stat.{op}", value=None, input_fact_ids=[], quality_flags=flags)

    nums = [v for _, v, _ in vals]
    if op == "avg":
        value = sum(nums) / len(nums)
    elif op == "min":
        value = min(nums)
    elif op == "max":
        value = max(nums)
    elif op == "sum":
        value = sum(nums)
    elif op == "latest":
        value = nums[-1]
    elif op == "std":
        if len(nums) < 2:
            flags["insufficient_history"] = {"needed": 2, "have": len(nums)}
            value = None
        else:
            mean = sum(nums) / len(nums)
            value = math.sqrt(sum((x - mean) ** 2 for x in nums) / (len(nums) - 1))
    else:  # cagr
        first_end, first_v, _ = vals[0]
        last_end, last_v, _ = vals[-1]
        years = (last_end - first_end).days / 365.25
        if years <= 0 or first_v is None or first_v <= 0 or last_v is None or last_v <= 0:
            # CAGR is undefined across a sign change or zero base — say so.
            flags["cagr_undefined"] = True
            value = None
        else:
            value = (last_v / first_v) ** (1 / years) - 1
    return ScalarResult(operation=f"stat.{op}", value=value, input_fact_ids=ids, quality_flags=flags)


# ── window return ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PricePoint:
    price_date: date
    close: float


def compute_window_return(
    prices: list[PricePoint],
    start: date,
    end: date,
    benchmark: list[PricePoint] | None = None,
) -> ScalarResult:
    """Return over [start, end], optionally relative to a benchmark.

    Uses the last close on/before each bound (markets are closed on many dates);
    if no price exists on/before a bound, the result is None + a flag.
    """
    def at(series: list[PricePoint], when: date) -> float | None:
        eligible = [p for p in sorted(series, key=lambda x: x.price_date) if p.price_date <= when]
        return eligible[-1].close if eligible else None

    flags: dict = {}
    p0, p1 = at(prices, start), at(prices, end)
    if p0 is None or p1 is None or p0 == 0:
        flags["no_price_for_window"] = True
        return ScalarResult(operation="window_return", value=None, quality_flags=flags)

    r = (p1 - p0) / p0
    op = "window_return"
    if benchmark:
        b0, b1 = at(benchmark, start), at(benchmark, end)
        if b0 is None or b1 is None or b0 == 0:
            flags["no_benchmark_for_window"] = True
        else:
            r -= (b1 - b0) / b0
            op = "window_return.relative"
    return ScalarResult(operation=op, value=r, quality_flags=flags)
