"""The book across its updates — the axis every panel was missing (V25).

WHY THIS EXISTS. A run is a photograph, and this desk keeps thirty-three of
them for the demo book. Every panel on the book page reads exactly one. The
value chart is not a counter-example: it is a price history of today's
holdings, not a history of what this book MEASURED, so "is this concentration
new, or has it been there since June" — the question a mandate warning actually
raises — was answerable by the database and by nothing on the page. The only
comparison anywhere was a single chip saying a sector weight moved "vs the
previous run".

This service is that axis, and it computes nothing to provide it. Every figure
below was written by the run that measured it. The one piece of arithmetic is a
subtraction between two such figures (`weight_change_vs_prev`), performed here,
once, beside both of the numbers it is the difference of — rather than in a
browser, where it would be a measure computed on the client (the rule
apps/web/app/components/book/panels.tsx states and this batch keeps).

TWO RULES DECIDE THE SHAPE.

**A day is one point.** The demo book has five completed runs dated
2026-09-03 — re-runs after a deploy, each a full measurement of the same close.
A chart with five points stacked on one date says the book moved five times
that day. `collapse_by_date` keeps the run with the latest `completed_at` per
`as_of_date` and reports how many it stood for, so the collapsing is on the
wire rather than silently done.

**A delta is against the previous DATED update.** Not the previous row: two
runs of the same close differ by zero and would draw a book that never moves.
This is also why `issuer_exposures.weight_change` is not what the page reads —
the workflow writes NULL into it on every row it has ever written
(exposure_workflow.py, the IssuerExposure block), and correcting that is a
change to a step with thirty-three runs of history behind it.

WHAT IS NOT HERE. No VaR, no expected shortfall, no stress row: checks the
desk withholds are filtered by `analytics.withheld.published_checks`, the same
one filter `/limit-book` passes its rows through, so a measure cannot reach a
reader through the series that is refused on the panel.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_names as dn
from exposure_workbench.analytics import withheld as wh
from exposure_workbench.db.models import (
    ExposureMetrics, ExposureRun, IssuerExposure, LimitCheck, RiskAlert, SectorExposure,
)

# How far back a reader may ask, as days of history. Named windows for the same
# reason /history and /price-index have them: an arbitrary day count invites
# "the last 37 updates", which is a window chosen after seeing the answer.
# `all` exists because a book with twelve updates has no long history to bound
# and hiding two of them behind a span would be arithmetic about nothing.
SPANS: dict[str, int | None] = {"1y": 366, "3y": 1096, "all": None}
DEFAULT_SPAN = "1y"


def _f(v) -> float | None:
    """A Numeric column as a float, or None — never zero. The same helper the
    chart reads in routes/exposure_runs.py use, for the same reason: a check
    that recorded nothing and a check that measured zero are different facts."""
    return None if v is None else float(v)


def collapse_by_date(runs: list[ExposureRun]) -> list[tuple[ExposureRun, int]]:
    """One run per `as_of_date` — the latest completed — with how many it stands for.

    Pure, and separate from the query, because this is the rule worth pinning by
    a test rather than by a `DISTINCT ON` nobody can read back. "Latest" is
    `completed_at`, falling back to `created_at` for a row whose completion time
    was never written: both are times the same run existed, and the ordering is
    what matters, not the instant.
    """
    latest: dict[date, tuple[ExposureRun, int]] = {}
    for run in runs:
        kept = latest.get(run.as_of_date)
        if kept is None:
            latest[run.as_of_date] = (run, 1)
            continue
        prior, seen = kept
        newer = (run.completed_at or run.created_at) > (prior.completed_at or prior.created_at)
        latest[run.as_of_date] = ((run, seen + 1) if newer else (prior, seen + 1))
    return [latest[d] for d in sorted(latest)]


def _delta(current: float | None, previous: float | None) -> float | None:
    """The move since the previous dated update, or None.

    None on the first update and on a name the book did not hold then, and
    those are the same answer for the reader: there is no move to state. A zero
    would say the weight held steady, which is a claim about a comparison that
    was never made.
    """
    if current is None or previous is None:
        return None
    return current - previous


async def get_run_series(
    db: AsyncSession, portfolio_id: str, span: str = DEFAULT_SPAN,
) -> dict[str, Any]:
    """Every dated update of a book, with what each one measured.

    Five reads, not one per run: the children are loaded for the whole set of
    collapsed run ids at once. A page that opened one query per update would
    make twelve round trips to draw a line.
    """
    if span not in SPANS:
        return {"error": "unknown_span", "span": span, "known": sorted(SPANS)}

    q = (select(ExposureRun)
         .where(ExposureRun.portfolio_id == portfolio_id, ExposureRun.status == "completed")
         .order_by(ExposureRun.as_of_date, ExposureRun.completed_at))
    window = SPANS[span]
    if window is not None:
        # Bounded against the newest update this book has, not against today: a
        # book last updated in June still has a year of its own history, and
        # anchoring on the clock would empty the chart rather than scroll it.
        newest = (await db.execute(
            select(ExposureRun.as_of_date)
            .where(ExposureRun.portfolio_id == portfolio_id, ExposureRun.status == "completed")
            .order_by(ExposureRun.as_of_date.desc()).limit(1))).scalar_one_or_none()
        if newest is None:
            return {"portfolio_id": portfolio_id, "span": span, "updates": [],
                    "labels": {"checks": {}, "sectors": {}},
                    "detail": "this book has no completed update yet"}
        q = q.where(ExposureRun.as_of_date >= newest - timedelta(days=window))

    collapsed = collapse_by_date(list((await db.execute(q)).scalars().all()))
    if not collapsed:
        return {"portfolio_id": portfolio_id, "span": span, "updates": [],
                "labels": {"checks": {}, "sectors": {}},
                "detail": "this book has no completed update in this window"}

    run_ids = [run.id for run, _ in collapsed]
    metrics = {m.run_id: m for m in (await db.execute(
        select(ExposureMetrics).where(ExposureMetrics.run_id.in_(run_ids)))).scalars().all()}
    issuers: dict[str, list[IssuerExposure]] = {}
    for row in (await db.execute(
            select(IssuerExposure).where(IssuerExposure.run_id.in_(run_ids))
            .order_by(IssuerExposure.ticker))).scalars().all():
        issuers.setdefault(row.run_id, []).append(row)
    sectors: dict[str, list[SectorExposure]] = {}
    for row in (await db.execute(
            select(SectorExposure).where(SectorExposure.run_id.in_(run_ids))
            .order_by(SectorExposure.sector))).scalars().all():
        sectors.setdefault(row.run_id, []).append(row)
    checks: dict[str, list[LimitCheck]] = {}
    for row in wh.published_checks((await db.execute(
            select(LimitCheck).where(LimitCheck.run_id.in_(run_ids))
            .order_by(LimitCheck.limit_type))).scalars().all()):
        checks.setdefault(row.run_id, []).append(row)
    alerts: dict[str, int] = {}
    for row in wh.published_alerts((await db.execute(
            select(RiskAlert).where(RiskAlert.run_id.in_(run_ids)))).scalars().all()):
        alerts[row.run_id] = alerts.get(row.run_id, 0) + 1

    updates: list[dict] = []
    prev_issuer: dict[str, float | None] = {}
    prev_sector: dict[str, float | None] = {}
    unrecorded_levels = 0
    for run, ran_that_day in collapsed:
        m = metrics.get(run.id)
        rows_i = issuers.get(run.id, [])
        rows_s = sectors.get(run.id, [])
        rows_c = checks.get(run.id, [])
        unrecorded_levels += sum(1 for c in rows_c if c.current_value is None)
        updates.append({
            "as_of": run.as_of_date.isoformat(),
            "run_id": run.id,
            "runs_that_day": ran_that_day,
            "metrics": None if m is None else {
                "market_value": _f(m.portfolio_market_value),
                "daily_pnl": _f(m.daily_pnl),
                "daily_return": _f(m.daily_return),
                "vol_30d": _f(m.rolling_vol_30d),
                "vol_60d": _f(m.rolling_vol_60d),
                "max_drawdown": _f(m.max_drawdown),
                "alerts": alerts.get(run.id, 0),
            },
            "issuers": [{
                "ticker": r.ticker,
                "sector": r.sector,
                "weight": _f(r.weight),
                "market_value": _f(r.market_value),
                "contribution": _f(r.contribution),
                "daily_pnl": _f(r.daily_pnl),
                "daily_return": _f(r.daily_return),
                "weight_change_vs_prev": _delta(_f(r.weight), prev_issuer.get(r.ticker)),
            } for r in rows_i],
            "sectors": [{
                "sector": r.sector,
                "weight": _f(r.weight),
                "market_value": _f(r.market_value),
                "weight_change_vs_prev": _delta(_f(r.weight), prev_sector.get(r.sector)),
            } for r in rows_s],
            "checks": [{
                "key": c.limit_type,
                "current": _f(c.current_value),
                "warning": _f(c.warning_level),
                "breach": _f(c.breach_level),
                "status": c.status,
                "fired": c.fired,
            } for c in rows_c],
        })
        # The comparison basis for the NEXT update, replaced wholesale: a name
        # sold between updates must not keep comparing against the weight it
        # had when it was held.
        prev_issuer = {r.ticker: _f(r.weight) for r in rows_i}
        prev_sector = {r.sector: _f(r.weight) for r in rows_s}

    return {
        "portfolio_id": portfolio_id,
        "span": span,
        "updates": updates,
        # The server's own names for what the series are OF, built once for the
        # response rather than repeated on every update: a key is how a check is
        # spelled, not how it is read, and the page must not transform one into
        # the other (the rule /limit-book already keeps).
        "labels": {
            "checks": {c["key"]: _check_label(c["key"])
                       for u in updates for c in u["checks"]},
            "sectors": {s["sector"]: dn.label("sector", s["sector"])
                        for u in updates for s in u["sectors"]},
        },
        "detail": (None if not unrecorded_levels else
                   f"{unrecorded_levels} check readings across these updates were made "
                   "before this desk recorded what each check measured, so those points "
                   "have no level"),
    }


def _check_label(key: str) -> str:
    """`issuer_concentration:MSFT` → `MSFT · issuer weight`.

    The same composition /limit-book performs, and deliberately the same words:
    the meters and the series beside them are two views of one check and must
    not name it two things.
    """
    limit_type, _, entity = key.partition(":")
    name = dn.label("limit", limit_type)
    if not entity:
        return name
    if limit_type == "stress_loss":
        return dn.label("scenario", entity)
    entity_label = (dn.label("sector", entity) if limit_type == "sector_concentration"
                    else entity)
    return f"{entity_label} · {name.lower()}"
