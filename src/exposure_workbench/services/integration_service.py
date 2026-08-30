"""V14-A. One read that puts a run's two halves on the same page.

The battery's structural finding: a turn discussing what ten businesses do had
the factor loadings of all ten sitting unread in the same run, and a book-level
question spent eleven of fifteen calls finding out what the book holds. Both are
the same defect — the integration a reader wants costs more calls than a turn
has, so it never happens.

This service is that integration, done once, server-side, from rows that already
exist. It computes nothing the run did not already compute: the ranking is an
ORDER over stress_results, the net is a SUM over factor_attributions, the
headroom is a SUBTRACTION over limit_checks' own three columns. That is why one
ledger row can carry all of it — the derived quantities are the ordering's
consequences, and every input keeps its own id.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics import integration as ig
from exposure_workbench.db.models import (
    ExposureMetrics,
    ExposureRun,
    FactorAttribution,
    IssuerExposure,
    LimitCheck,
    StressResult,
)
from exposure_workbench.services import calc_service as cs
from exposure_workbench.tools.registry import current_session_id

OP_INTEGRATION = "portfolio.integration"

# The risks the factor model can speak to. Named here rather than derived from
# the config, because a risk this service can net is a risk _RISK_SENSE knows
# which way points — adding a factor to the YAML does not by itself make its
# direction knowable.
_RISKS = ("rates_up", "credit_spreads_widen", "equity_down")


def _f(v) -> float | None:
    return None if v is None else float(v)


async def get_portfolio_analysis(db: AsyncSession, run_id: str) -> dict:
    """A run's exposures, ordered, netted, and measured against its limits.

    Returns the whole set — every scenario, every leg, every check that ran. No
    top_k: an answer that names the three worst scenarios out of eight is an
    answer whose reader cannot tell whether the fourth was 0.1% or 7%.
    """
    run = (await db.execute(
        select(ExposureRun).where(ExposureRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return {"error": "unknown_run", "run_id": run_id,
                "message": f"no exposure run {run_id}"}
    if run.status != "completed":
        # A run still going has children that are half-written. Ordering them
        # would produce a ranking that changes under the reader.
        return {"error": "run_not_completed", "run_id": run_id, "status": run.status,
                "message": f"run {run_id} is {run.status}; its findings are not final"}

    metrics = (await db.execute(
        select(ExposureMetrics).where(ExposureMetrics.run_id == run_id))).scalar_one_or_none()
    scenarios = list((await db.execute(
        select(StressResult).where(StressResult.run_id == run_id)
        .order_by(StressResult.scenario))).scalars().all())
    factors = list((await db.execute(
        select(FactorAttribution).where(FactorAttribution.run_id == run_id)
        .order_by(FactorAttribution.factor_name))).scalars().all())
    positions = list((await db.execute(
        select(IssuerExposure).where(IssuerExposure.run_id == run_id)
        .order_by(IssuerExposure.ticker))).scalars().all())
    checks = list((await db.execute(
        select(LimitCheck).where(LimitCheck.run_id == run_id)
        .order_by(LimitCheck.limit_type))).scalars().all())

    collinear = (None if metrics is None or metrics.collinear is None
                 else bool(metrics.collinear))

    # ── ranked stress ────────────────────────────────────────────────────────
    # Only scenarios that were EVALUATED are ranked. An unevaluated one has no
    # loss to compare, and ranking it at zero would place "we could not measure
    # this" below every measured scenario as though it were the safest.
    ranked = ig.rank_by_magnitude([
        ig.RankedItem(name=s.scenario, value=float(s.loss_pct), unit_class="RATIO",
                      source_id=run_id, label=f"stress_results.{s.scenario}.loss_pct",
                      note=(f"holds {', '.join(s.factors_held_flat)} flat"
                            if s.factors_held_flat else None))
        for s in scenarios if s.loss_pct is not None
    ])
    unevaluated = [{"scenario": s.scenario, "reason": s.reason}
                   for s in scenarios if s.loss_pct is None]

    # ── netted factor exposure ───────────────────────────────────────────────
    factor_rows = [{"factor_name": f.factor_name, "factor_ticker": f.factor_ticker,
                    "beta": _f(f.beta), "source_id": run_id} for f in factors]
    nets = {}
    for risk in _RISKS:
        net = ig.net_factor_exposure(factor_rows, risk, collinear)
        if net is None:
            # Said, not omitted: a risk with no factor behind it is a hole in
            # the measurement, and a payload that simply lacks the key reads as
            # a book with no exposure to it.
            nets[risk] = {"measured": False,
                          "reason": "no factor in this run's regression measures this risk"}
            continue
        nets[risk] = {
            "measured": True,
            "direction": net.direction,
            "net_beta": net.net,
            "gross_beta": net.gross,
            "quotable_individually": net.quotable_individually,
            "legs": [{"factor_name": l.name, "beta": l.beta,
                      "signed_for_this_risk": l.signed_contribution, "cite": run_id}
                     for l in net.legs],
        }

    # ── headroom ─────────────────────────────────────────────────────────────
    room = ig.headroom([
        {"limit_type": c.limit_type, "entity_id": None,
         "current_value": _f(c.current_value), "warning_level": _f(c.warning_level),
         "breach_level": _f(c.breach_level), "evaluated": True, "source_id": run_id}
        for c in checks
    ])
    not_recorded = [c.limit_type for c in checks if c.current_value is None]

    # ── the matrix ───────────────────────────────────────────────────────────
    matrix = ig.integration_matrix([
        {"ticker": p.ticker, "sector": p.sector, "weight": _f(p.weight),
         "contribution": _f(p.contribution), "market_value": _f(p.market_value),
         "source_id": run_id}
        for p in positions
    ])

    out: dict = {
        "run_id": run_id,
        "portfolio_id": run.portfolio_id,
        "as_of": run.as_of_date.isoformat(),
        "stress_ranked": [
            {"scenario": r.name, "loss_pct": r.value, "rank": i + 1,
             "note": r.note, "cite": run_id}
            for i, r in enumerate(ranked)
        ],
        "stress_unevaluated": unevaluated,
        "net_exposures": nets,
        "headroom": [
            {"check": h.check, "current": h.current, "status": h.status,
             "warning_level": h.warning_level, "breach_level": h.breach_level,
             "room_to_warning": h.to_warning, "room_to_breach": h.to_breach,
             "cite": run_id}
            for h in room
        ],
        "headroom_not_recorded": not_recorded,
        "positions": [
            {"ticker": m.ticker, "sector": m.sector, "weight": m.weight,
             "contribution": m.contribution, "market_value": m.market_value,
             "cite": run_id}
            for m in matrix
        ],
        "reads_as": (
            "The scenarios are ordered by the size of the loss; the net exposures say which "
            "way the book moves if each risk materialises, with the legs that make up the net; "
            "the headroom is the distance from each measured value to its own thresholds."
        ),
        "not_a_forecast": True,
        "cite": run_id,
    }
    out["calc_id"] = await _record(db, run_id, out)
    return out


def identifying_params(run_id: str) -> dict:
    return {"run_id": run_id}


async def _record(db: AsyncSession, run_id: str, out: dict) -> str:
    """Mint the row for the quantities this read DERIVED.

    Only the derived ones. The stress losses, the betas and the limit levels are
    columns of the run's own children and already resolve through the run id;
    recording them again would build a second, weaker path to the same evidence
    (reconcile_service's rule, and the reason its docstring says so).

    What is genuinely new here is the netting and the distances: a net beta is a
    sum this read performed, and a room-to-breach is a subtraction it performed.
    Those are quotable because this row holds them.
    """
    # Labelled families, the shape _CALC_RESULT_KEYS declares for this op. The
    # label is the risk or the check, so a refusal can say WHICH net beta the
    # answer nearly matched rather than which position in a list.
    recorded: dict = {
        "net_beta": [{"label": risk, "value": n["net_beta"]}
                     for risk, n in out["net_exposures"].items() if n.get("measured")],
        "gross_beta": [{"label": risk, "value": n["gross_beta"]}
                       for risk, n in out["net_exposures"].items() if n.get("measured")],
        "room_to_warning": [{"label": h["check"], "value": h["room_to_warning"]}
                            for h in out["headroom"]],
        "room_to_breach": [{"label": h["check"], "value": h["room_to_breach"]}
                           for h in out["headroom"]],
    }

    return await cs._record(
        db, None, OP_INTEGRATION,
        identifying_params(run_id),
        recorded,
        [run_id],
        {"scenarios_ranked": len(out["stress_ranked"]),
         "scenarios_unevaluated": len(out["stress_unevaluated"]),
         "risks_unmeasured": sorted(r for r, n in out["net_exposures"].items()
                                    if not n.get("measured"))},
        current_session_id(),
    )
