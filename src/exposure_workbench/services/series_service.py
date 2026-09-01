"""V10-S2 — one operator over one series, from the ledger row it lives in.

`series_stat(series_id, op)` is the union of what `compute_change` (yoy, qoq,
pct, abs) and `compute_stat` (cagr, avg, min, max, std, sum, latest) did, minus
the part that made them two tools with twenty-one parameters between them:
each of those fetched its own series by (ticker, metric, period_type, last_n)
and computed on it in one breath, so "take" and "compute" could not be told
apart and every operator re-spelled the fetch. Here the series is an id — a
`flow.series`, a `balance.series`, or the output of another series operator —
and the operator is the only argument left.

The arithmetic is `analytics.series_ops`, untouched: `compute_change` matches
year-over-year BY DATE (positional lag on a sparse series once reported 2808%
growth by comparing points four years apart), and `compute_stat` refuses a
CAGR across a sign change. Neither knew about the ladder, which is why they
survive it.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import series_ops as so
from exposure_workbench.analytics import units
from exposure_workbench.db.models import CalcLedger
from exposure_workbench.services import calc_service as cs

CHANGE_OPS = tuple(so.CHANGE_MODES)
STAT_OPS = tuple(so.STAT_OPS)
OPS = CHANGE_OPS + STAT_OPS

# What a change is measured in. A yoy/qoq/pct change is a ratio whatever the
# series was; an abs change carries the series' own unit.
_RATIO_CHANGES = ("yoy", "qoq", "pct")
# Which stats keep the series' unit and which do not: a CAGR is a rate, the
# rest are one of the values (or their moment) and measure what they measured.
_RATIO_STATS = ("cagr",)


async def load_series(db: AsyncSession, series_id: str) -> tuple[list[so.SeriesPoint], dict] | dict:
    """The points of a ledgered series, and its recorded type.

    Any calc row whose result has `points` is a series; the row's
    `params.result_type` says what the points are. A row without one is a
    series from before types were recorded and cannot be operated on safely —
    its unit is unknown — so it is refused with the tool that would produce a
    typed one.
    """
    row = (await db.execute(select(CalcLedger).where(CalcLedger.id == series_id))).scalar_one_or_none()
    if row is None:
        return {"error": "unknown_series", "series_id": series_id,
                "detail": f"{series_id} is not a calculation this desk holds"}
    points = (row.result or {}).get("points")
    if not isinstance(points, list):
        return {"error": "not_a_series", "series_id": series_id,
                "detail": f"{series_id} ({row.operation}) holds one value, not a series; "
                          f"use calculate for scalars"}
    rtype = (row.params or {}).get("result_type")
    if not rtype:
        return {"error": "untyped_series", "series_id": series_id,
                "detail": f"{series_id} was recorded before series carried their type. "
                          f"Recompute it with get_flow(last_n=…) or get_balance_series."}
    out = []
    for p in points:
        # Writers use POINT_PERIOD_KEY and only that since V16; the other two
        # keys are the frozen legacy vocabulary of rows written before it.
        end = p.get(units.POINT_PERIOD_KEY) or p.get("end") or p.get("as_of")
        if end is None:
            continue
        out.append(so.SeriesPoint(period_end=date.fromisoformat(end), value=p.get("value"),
                                  input_fact_ids=list(p.get("fact_ids") or []),
                                  quality_flags=({"unreachable": p["unreachable"]}
                                                 if p.get("unreachable") else {})))
    return out, rtype


async def series_stat(db: AsyncSession, series_id: str, op: str,
                      invoked_by: str = "agent") -> dict:
    if op not in OPS:
        return {"error": "unsupported_op", "op": op, "supported": list(OPS)}
    loaded = await load_series(db, series_id)
    if isinstance(loaded, dict):
        return loaded
    points, rtype = loaded

    # The result is named for what it did to what — revenue.yoy — instead of
    # quantity=None with the real name hidden in derived_from, where no reader
    # of the row could act on it. Inherited units are inherited, not defaulted:
    # a typed series that lacks its unit is refused, never presumed money.
    base = rtype.get("quantity") or series_id
    inherited = rtype.get("unit_class")
    if inherited is None:
        return {"error": "untyped_series", "series_id": series_id,
                "detail": f"{series_id} recorded a result_type without a unit_class. "
                          f"Recompute it with get_flow(last_n=…) or get_balance_series."}

    if op in CHANGE_OPS:
        res = so.compute_change(points, op)
        unit = "ratio" if op in _RATIO_CHANGES else inherited
        result_type = {"unit_class": unit, "kind": "series", "quantity": f"{base}.{op}",
                       "derived_from": rtype.get("quantity")}
        out_points = [{units.POINT_PERIOD_KEY: p.period_end.isoformat(), "value": p.value,
                       "fact_ids": p.input_fact_ids, **({"flags": p.quality_flags} if p.quality_flags else {})}
                      for p in res.points]
        calc_id = await cs._record(
            db, None, res.operation, {"series": series_id, "op": op, "result_type": result_type},
            {"points": out_points}, [series_id], res.quality_flags, invoked_by)
        return {"calc_id": calc_id, "op": op, "series": series_id, "points": out_points,
                "unit_class": unit, "quality_flags": res.quality_flags,
                "basis": f"{op} over {series_id}; each point is matched to its prior by date, "
                         f"never by position"}

    res = so.compute_stat(points, op)
    unit = "ratio" if op in _RATIO_STATS else inherited
    result_type = {"unit_class": unit, "kind": "scalar", "quantity": f"{base}.{op}",
                   "derived_from": rtype.get("quantity"),
                   "basis": {"series": series_id, "points": len([p for p in points if p.value is not None])}}
    calc_id = await cs._record(
        db, None, res.operation, {"series": series_id, "op": op, "result_type": result_type},
        {"value": res.value}, [series_id], res.quality_flags, invoked_by)
    return {"calc_id": calc_id, "op": op, "series": series_id, "value": res.value,
            "unit_class": unit, "quality_flags": res.quality_flags,
            "basis": f"{op} over the {result_type['basis']['points']} valued points of {series_id}"}
