"""Every measure this desk holds for an issuer, and what can be drawn of it (V25).

WHY THIS EXISTS. The issuer page could chart three numbers — gross, operating
and net margin — out of the thirty-seven measures it holds for Microsoft and
the sixteen rows its recipe computed. Everything else was a row in a table with
a period count beside it. The reader's question is "show me revenue", and the
answer was a ladder of window rectangles for whichever metric a dropdown was
left on.

So this is the picker: one read that says what exists, what its latest figure
is, how far back it goes, and — the part that keeps the decision on the server
— WHICH VIEWS each measure supports. A client that decided for itself whether a
measure has a year-on-year series would be guessing about the recipe's
contents; here the answer is derived from three things the desk already knows:

    the measure's kind          a flow covers a window, a balance is an instant
    the recipe's manifest       `<metric>_yoy` exists, or it does not
    recipe._MARGIN_NUMERATORS   which flows have a margin, i.e. a share of revenue

NOTHING IS COMPUTED AND NOTHING IS RECORDED. The latest window of a flow comes
from `interval_algebra.consecutive_windows` — the same call `/windows` makes,
in process, with no ledger row — and the latest balance is the newest filed
fact with restatements resolved by the one rule. A ratio's points are not
returned at all: the row carries its `calc_id`, and the chart fetches the
series from `/panel-series`, which serves the ledger row that already exists.

ONE QUERY PER KIND, not one per measure. Twenty-one flows fetched one at a time
would be twenty-one round trips to draw a list.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import display_names as dn
from exposure_workbench.analytics import interval_algebra as ia
from exposure_workbench.analytics import units
from exposure_workbench.db.models import CalcLedger, Company, Filing, FinancialFact
from exposure_workbench.services import calc_service as cs
from exposure_workbench.services.recipe import _MARGIN_NUMERATORS, OP_MANIFEST

# What a row's `views` may contain. The client renders a control per entry and
# never invents one: a view absent here is a view this measure cannot support.
LEVEL, YOY, SHARE, WINDOWS = "level", "yoy", "share", "windows"

# Which flow a margin is the share OF — the recipe's own table, read rather
# than restated, so a margin added there appears here without an edit.
SHARE_OF_REVENUE = {numerator: label for label, numerator in _MARGIN_NUMERATORS}


async def _flow_facts_by_metric(db: AsyncSession, company_id: str) -> dict[str, list[ia.FlowFact]]:
    """Every flow fact this issuer has filed, grouped by metric — one query.

    The same filter `fundamentals_service._flow_facts` applies for one metric:
    consolidated only (`dimensions_hash == ""`), a period, a value.
    """
    rows = (await db.execute(
        select(FinancialFact.normalized_metric, FinancialFact.id, FinancialFact.period_start,
               FinancialFact.period_end, FinancialFact.value, FinancialFact.source_accession,
               Filing.filing_date)
        .outerjoin(Filing, Filing.id == FinancialFact.filing_id)
        .where(FinancialFact.company_id == company_id,
               FinancialFact.normalized_metric.is_not(None),
               FinancialFact.dimensions_hash == "",
               FinancialFact.period_start.is_not(None),
               FinancialFact.value.is_not(None))
    )).all()
    out: dict[str, list[ia.FlowFact]] = {}
    for metric, fid, ps, pe, value, acc, filed in rows:
        out.setdefault(metric, []).append(
            ia.FlowFact(fact_id=fid, period_start=ps, period_end=pe, value=float(value),
                        source_accession=acc, filing_date=filed))
    return out


async def _latest_balances(db: AsyncSession, company_id: str) -> dict[str, dict]:
    """The newest reading of every balance line, restatements resolved — one query.

    The rule is `interval_algebra.restatement_key`, which is how
    `get_balance_series` resolves the same collision: most recently filed wins.
    Applying a second rule here is exactly the defect V9-A6 removed.
    """
    rows = (await db.execute(
        select(FinancialFact.normalized_metric, FinancialFact.period_end, FinancialFact.value,
               FinancialFact.id, FinancialFact.source_accession, Filing.filing_date)
        .outerjoin(Filing, Filing.id == FinancialFact.filing_id)
        .where(FinancialFact.company_id == company_id,
               FinancialFact.normalized_metric.is_not(None),
               FinancialFact.dimensions_hash == "",
               FinancialFact.period_start.is_(None),
               FinancialFact.value.is_not(None))
    )).all()
    best: dict[str, tuple[date, float, str, tuple]] = {}
    for metric, period_end, value, fid, acc, filed in rows:
        if period_end is None:
            continue
        key = ia.restatement_key(filed, acc)
        kept = best.get(metric)
        if kept is None or (period_end, key) > (kept[0], kept[3]):
            best[metric] = (period_end, float(value), fid, key)
    return {m: {"as_of": pe.isoformat(), "value": v, "fact_ids": [fid]}
            for m, (pe, v, fid, _key) in best.items()}


async def _manifest_rows(db: AsyncSession, ticker: str) -> tuple[dict[str, CalcLedger], dict]:
    """The recipe's latest manifest, as {label: ledger row}, plus its params.

    Read the same way routes/issuers.financials reads it — by the manifest row
    naming each label's calc_id, never by scanning the ledger for
    `invoked_by = 'recipe'`: a v2 yoy row's params carry the id of the series it
    was taken over, which is a different id on every run, so a scan has nothing
    stable to key on (V10-S3).
    """
    manifest = (await db.execute(
        select(CalcLedger).where(CalcLedger.company_id == ticker,
                                 CalcLedger.operation == OP_MANIFEST)
        .order_by(CalcLedger.created_at.desc()).limit(1))).scalar_one_or_none()
    if manifest is None:
        return {}, {}
    labels: dict = (manifest.result or {}).get("labels") or {}
    ids = [v for v in labels.values() if isinstance(v, str)]
    rows = {r.id: r for r in (await db.execute(
        select(CalcLedger).where(CalcLedger.id.in_(ids)))).scalars().all()} if ids else {}
    by_label = {label: rows[ref] for label, ref in labels.items()
                if isinstance(ref, str) and ref in rows}
    return by_label, (manifest.params or {})


def _row_points(row: CalcLedger) -> list | None:
    pts = ((row.result or {}).get("points"))
    return pts if isinstance(pts, list) else None


def _row_unit(row: CalcLedger) -> str:
    """What a recipe row's result IS, from the row's own declaration.

    `unit_class` is on the column since V15-S1 and in `params.result_type`
    since V16; both are the row saying what it computed, and neither is a guess
    made here from the operation's name — the guessing is the class of defect
    V24 removed from the gate.
    """
    declared = row.unit_class or ((row.params or {}).get("result_type") or {}).get("unit_class")
    return (declared or "").lower()


def _slot(window: ia.SeriesWindow) -> dict | None:
    """One derived window as the picker states it, or None when unreachable."""
    if not isinstance(window.window, ia.Derived):
        return None
    return {"start": window.start.isoformat(), "end": window.end.isoformat(),
            "value": window.window.value,
            "derived": len(window.window.terms) > 1,
            "fact_ids": list(window.window.fact_ids)}


def _latest_window(facts: list[ia.FlowFact], months: int) -> tuple[dict | None, str | None]:
    """The newest window of this length, or the reason there is none.

    Two ways there is none, and they are different facts about the issuer:

    * the engine reached a slot and could not derive it — its own sentence is
      returned, because "no held filing can reach this window" is a finding
      (V10 DP2) and not an absence of data;
    * the engine produced no slot at all, because the issuer files no pair of
      boundaries this far apart. NVDA holds two annual revenue facts and no
      quarterly boundary anywhere near them, so there is no quarter to reach
      for. The sentence says that, in terms of what IS held, and never
      substitutes the twelve-month figure for the missing quarter — the silent
      convention switch this whole engine exists to remove.
    """
    got = ia.consecutive_windows(facts, months=months, last_n=1)
    if got:
        slot = _slot(got[-1])
        if slot is not None:
            return slot, None
        window = got[-1].window
        return None, getattr(window, "reason", None)
    if not facts:
        return None, "this desk holds no filed period of this measure"
    ends = sorted({f.period_end for f in facts})
    return None, (f"this desk holds no pair of boundaries {months} months apart for this "
                  f"measure; the {len(facts)} periods it holds run "
                  f"{ends[0].isoformat()} to {ends[-1].isoformat()}")


async def list_measures(db: AsyncSession, ticker: str) -> dict[str, Any]:
    """The issuer's measures in three groups, each row saying what it can draw."""
    ticker = ticker.upper()
    company_id = (await db.execute(
        select(Company.id).where(Company.ticker == ticker))).scalar_one_or_none()
    if company_id is None:
        return {"error": "unknown_company", "ticker": ticker}

    catalogue = await cs.list_available_metrics(db, ticker)
    described = {m["metric"]: m for m in catalogue["metrics"]}
    flow_facts = await _flow_facts_by_metric(db, company_id)
    balances_latest = await _latest_balances(db, company_id)
    manifest, manifest_params = await _manifest_rows(db, ticker)

    flows: list[dict] = []
    ratios: list[dict] = []
    balances: list[dict] = []
    unavailable: list[dict] = []

    for metric, described_row in sorted(described.items(), key=lambda kv: dn.metric(kv[0])):
        label = dn.metric(metric)
        through = described_row.get("latest_period_end")
        if described_row.get("kind") == "flow":
            facts = flow_facts.get(metric, [])
            latest, why_no_quarter = _latest_window(facts, 3)
            latest_12m, why_no_year = _latest_window(facts, 12)
            # Which lengths the window control may offer. Derived from what the
            # engine could actually produce, not from what the issuer filed: an
            # issuer files 3- and 12-month revenue and may still have no
            # derivable latest quarter.
            available = ([w for w, got in (("3-month", latest), ("12-month", latest_12m)) if got])
            if not available:
                # Held, and not drawable at either length. Listed as unavailable
                # with the engine's reason rather than as a row that draws an
                # empty chart when a reader clicks it.
                unavailable.append({"metric": metric, "label": label,
                                    "detail": why_no_quarter or why_no_year or "no window can be derived"})
                continue
            yoy_metric = f"{metric}_yoy" if f"{metric}_yoy" in manifest else None
            share_metric = SHARE_OF_REVENUE.get(metric)
            if share_metric not in manifest:
                share_metric = None
            views = [LEVEL]
            if yoy_metric:
                views.append(YOY)
            if share_metric:
                views.append(SHARE)
            views.append(WINDOWS)
            flows.append({
                "metric": metric, "label": label, "source": "filed",
                "unit_class": units.MONEY.upper(),
                "periods": described_row.get("periods"), "through": through,
                "windows_filed": described_row.get("windows_filed"),
                "windows_available": available,
                "latest": latest,
                "latest_unreachable": why_no_quarter,
                "latest_12m": latest_12m,
                "latest_12m_unreachable": why_no_year,
                "views": views,
                "yoy_metric": yoy_metric,
                "share_metric": share_metric,
            })
        else:
            latest = balances_latest.get(metric)
            superseded = described_row.get("superseded_by")
            balances.append({
                "metric": metric, "label": label, "source": "filed",
                "unit_class": units.MONEY.upper(),
                "readings": described_row.get("periods"), "through": through,
                "latest": latest,
                "views": [LEVEL],
                "superseded_by": superseded,
            })
            if latest is None:
                unavailable.append({"metric": metric,
                                    "detail": f"no consolidated reading of {label.lower()} is held"})

    # The recipe's series. A yoy row is a flow's view and never a row of its
    # own; a return row belongs to the price chart, which states its own window.
    for label_key, row in sorted(manifest.items(), key=lambda kv: dn.label("recipe_row", kv[0])):
        if label_key.endswith("_yoy") or label_key.startswith("return_"):
            continue
        points = _row_points(row)
        if points is None:
            continue
        unit = _row_unit(row)
        entry = {
            "metric": label_key, "label": dn.label("recipe_row", label_key), "source": "recipe",
            "unit_class": unit.upper(), "calc_id": row.id, "operation": row.operation,
            "points": len(points),
            "latest": _recipe_latest(points),
            "views": [LEVEL],
        }
        # A recipe series denominated in money is a flow the desk computed —
        # free cash flow is operations less capital expenditure over a quarter —
        # and it belongs beside the filed flows a reader compares it with, not
        # under a heading that says ratio.
        (flows if unit == units.MONEY else ratios).append(entry)

    for label_key, ref in ((manifest_params.get("unavailable") or {}) or {}).items():
        unavailable.append({"metric": label_key, "detail": str(ref)})

    return {
        "ticker": ticker,
        # The recipe's own as-of, which the ratios are anchored to and the filed
        # flows are not: a filed figure is dated by its filing, a computed one by
        # the run that computed it, and one date over both would be wrong about
        # one of them.
        "as_of": manifest_params.get("as_of"),
        "recipe_version": manifest_params.get("recipe_version"),
        "flows": flows,
        "ratios": ratios,
        "balances": balances,
        "unavailable": unavailable,
    }


def _recipe_latest(points: list) -> dict | None:
    """The last point of a recipe series, in the shape the picker prints.

    Series points end on `end` (a window) or `as_of` (an instant); both spellings
    are in the ledger and the older `period_end` is in rows minted before the
    key moved (analytics/units.POINT_PERIOD_KEY).
    """
    if not points:
        return None
    last = points[-1]
    if not isinstance(last, dict):
        return None
    when = last.get("end") or last.get("as_of") or last.get(units.POINT_PERIOD_KEY)
    value = last.get("value")
    if when is None or not isinstance(value, (int, float)):
        return None
    return {"end": when, "value": float(value)}
