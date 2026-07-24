"""Period ladder (M3) — as-reported XBRL facts -> a clean, comparable series.

This is the ONLY place period logic lives. Every fundamentals metric consumes a
ladder, so quarter alignment, restatement selection and Q4 derivation are
written and tested once instead of being re-implemented per metric.

Grounded in measured EDGAR behaviour (see MODULE_NOTES M2):
  * fiscal_year / fiscal_quarter LABELS ARE NOT RELIABLE — the same period
    2025-01-27..2025-04-27 is tagged FY2027 by one filing and FY2026 by another.
    period_start / period_end are the authoritative key.
  * Q4 quarterly facts generally DO NOT EXIST (issuers report 3 quarters + a
    full year), so Q4 must be derived as annual - (Q1+Q2+Q3).
  * Half-year and nine-month CUMULATIVE facts exist and must never be mistaken
    for quarters.

Pure functions: no DB, no network, no LLM. Missing data yields fewer points plus
a quality flag — never an interpolated or carried-forward value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

# Duration buckets, in days, tolerant of 52/53-week fiscal calendars.
QUARTER_RANGE = (80, 100)
HALF_RANGE = (170, 200)
NINE_MONTH_RANGE = (260, 290)
ANNUAL_RANGE = (350, 380)

QUARTERLY = "quarterly"
ANNUAL = "annual"
INSTANT = "instant"
HALF = "half"
NINE_MONTH = "nine_month"
OTHER = "other"


@dataclass(frozen=True)
class FactPoint:
    """One as-reported fact (the service layer maps DB rows into this)."""

    fact_id: str
    period_end: date
    value: float
    period_start: date | None = None
    source_accession: str | None = None
    filing_date: date | None = None


@dataclass(frozen=True)
class LadderPoint:
    period_end: date
    value: float
    period_start: date | None
    period_type: str
    input_fact_ids: list[str] = field(default_factory=list)
    quality_flags: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Ladder:
    metric: str
    period_type: str
    points: list[LadderPoint] = field(default_factory=list)     # ascending by period_end
    quality_flags: dict = field(default_factory=dict)

    def values(self) -> list[float]:
        return [p.value for p in self.points]


def classify_duration(period_start: date | None, period_end: date) -> str:
    if period_start is None:
        return INSTANT
    days = (period_end - period_start).days
    if QUARTER_RANGE[0] <= days <= QUARTER_RANGE[1]:
        return QUARTERLY
    if HALF_RANGE[0] <= days <= HALF_RANGE[1]:
        return HALF
    if NINE_MONTH_RANGE[0] <= days <= NINE_MONTH_RANGE[1]:
        return NINE_MONTH
    if ANNUAL_RANGE[0] <= days <= ANNUAL_RANGE[1]:
        return ANNUAL
    return OTHER


def _pick_latest(candidates: list[FactPoint]) -> tuple[FactPoint, bool]:
    """Choose the most recently filed version of a period. Returns (point, was_restated).

    Ordering prefers filing_date, falling back to accession (which sorts
    chronologically within an issuer)."""
    if len(candidates) == 1:
        return candidates[0], False
    ordered = sorted(
        candidates,
        key=lambda f: (f.filing_date or date.min, f.source_accession or ""),
    )
    return ordered[-1], True


def build_ladder(
    facts: list[FactPoint],
    metric: str,
    period_type: str = QUARTERLY,
) -> Ladder:
    """Filter to one duration type, resolve restatements, sort ascending."""
    if period_type not in (QUARTERLY, ANNUAL, INSTANT):
        raise ValueError(f"unsupported period_type {period_type!r}")

    matching = [f for f in facts if classify_duration(f.period_start, f.period_end) == period_type]
    flags: dict = {}
    if not matching:
        flags["no_facts_for_period_type"] = True
        return Ladder(metric=metric, period_type=period_type, quality_flags=flags)

    by_period: dict[tuple[date | None, date], list[FactPoint]] = {}
    for f in matching:
        by_period.setdefault((f.period_start, f.period_end), []).append(f)

    points: list[LadderPoint] = []
    restated = 0
    for (p_start, p_end), group in sorted(by_period.items(), key=lambda kv: kv[0][1]):
        chosen, was_restated = _pick_latest(group)
        pf: dict = {}
        if was_restated:
            restated += 1
            pf["restated_superseded"] = len(group) - 1
        points.append(
            LadderPoint(
                period_end=p_end,
                value=chosen.value,
                period_start=p_start,
                period_type=period_type,
                input_fact_ids=[chosen.fact_id],
                quality_flags=pf,
            )
        )
    if restated:
        flags["restated_periods"] = restated
    return Ladder(metric=metric, period_type=period_type, points=points, quality_flags=flags)


def derive_q4(quarterly: Ladder, annual: Ladder) -> Ladder:
    """Add the missing Q4 point for each fiscal year: Q4 = annual - (Q1+Q2+Q3).

    Only fires when exactly three quarters fall inside the annual window and no
    quarter already ends on the annual period_end. Anything else is left alone —
    a partially covered year yields no Q4 rather than a wrong one.
    """
    if not annual.points or not quarterly.points:
        return quarterly

    points = list(quarterly.points)
    added = 0
    for a in annual.points:
        if a.period_start is None:
            continue
        window_start, window_end = a.period_start, a.period_end
        inside = [
            p for p in quarterly.points
            if p.period_start is not None
            and p.period_start >= window_start - timedelta(days=5)
            and p.period_end <= window_end + timedelta(days=5)
        ]
        if any(abs((p.period_end - window_end).days) <= 5 for p in inside):
            continue                      # a real Q4 already exists
        if len(inside) != 3:
            continue                      # incomplete year — do not guess
        q4_value = a.value - sum(p.value for p in inside)
        last_end = max(p.period_end for p in inside)
        points.append(
            LadderPoint(
                period_end=window_end,
                value=q4_value,
                period_start=last_end + timedelta(days=1),
                period_type=QUARTERLY,
                input_fact_ids=[fid for p in inside for fid in p.input_fact_ids] + a.input_fact_ids,
                quality_flags={"derived_q4": True},
            )
        )
        added += 1

    points.sort(key=lambda p: p.period_end)
    flags = dict(quarterly.quality_flags)
    if added:
        flags["derived_q4_periods"] = added
    return Ladder(metric=quarterly.metric, period_type=QUARTERLY, points=points, quality_flags=flags)
