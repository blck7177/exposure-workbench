"""V8-A — the run's own findings, readable (M17).

Everything here already existed as rows. The gate has been able to resolve a
`run_` citation through `factor_attributions` and `issuer_exposures` since V3;
V8-P added the regression metadata, the stress scenarios and the limit checks.
What none of it had was a way for an agent to READ it. The evidence resolver
answers "does this number appear in the run", and the model was left to guess
which numbers to write — so "why did the book move" was answered by fetching
filings, at fifteen tool calls, about a day whose attribution was sitting in a
table the whole time.

Two shapes are deliberate and both have tests asserting the absence rather than
the presence:

  * **No top_k, no limit.** A `top_k` argument is the mechanism by which an
    answer names two positions and implies the rest do not matter. The full set
    is small (ten positions, eight factors) and comes back whole. If it ever
    stops being small the answer is pagination with a stated total, not a
    silent truncation the model chooses the size of.
  * **No judgement fields.** Nothing here is `healthy`, `risky`, `concerning` or
    `acceptable`. `quotable_individually` looks like an exception and is not: it
    is a statement about the ESTIMATE's determinacy (VIF over threshold), which
    the regression computed, not about whether a number is good news.

`quotable_individually` deserves its own note. factor_model's docstring has
argued since V6 that under collinearity the SUM over the factor set is well
determined while each coefficient is not — and that argument lived in a
docstring, where the model that writes the answer cannot read it. Here it is a
field on each beta.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.db.models import (
    ExposureMetrics,
    ExposureRun,
    FactorAttribution,
    IssuerExposure,
    LimitCheck,
    MarketPrice,
    RiskAlert,
    RiskLimit,
    SectorExposure,
    StressResult,
)


def _f(v) -> float | None:
    return None if v is None else float(v)


async def _run_or_error(db: AsyncSession, run_id: str) -> ExposureRun | dict:
    row = (await db.execute(select(ExposureRun).where(ExposureRun.id == run_id))).scalar_one_or_none()
    if row is None:
        # Not "not found" alone: under RLS a run belonging to another tenant is
        # indistinguishable from one that never existed, and saying so plainly
        # is better than a bare miss the model retries.
        return {"error": "unknown_run", "run_id": run_id,
                "detail": "no run with this id is visible to you; call get_portfolio_snapshot "
                          "for the runs on your own books"}
    return row


# ── A1: attribution ───────────────────────────────────────────────────────────

async def get_attribution(db: AsyncSession, run_id: str) -> dict:
    """The whole of one run's one-day attribution: every factor, every position.

    `metadata` is None for a run written before V8-P1 rather than back-filled.
    A regression's window and observation count cannot be asserted after the
    fact from anything that survives, and inventing them is the failure mode
    this codebase has spent three batches removing.
    """
    run = await _run_or_error(db, run_id)
    if isinstance(run, dict):
        return run

    metrics = (await db.execute(
        select(ExposureMetrics).where(ExposureMetrics.run_id == run_id))).scalar_one_or_none()
    factors = list((await db.execute(
        select(FactorAttribution).where(FactorAttribution.run_id == run_id)
        .order_by(FactorAttribution.factor_name))).scalars().all())
    positions = list((await db.execute(
        select(IssuerExposure).where(IssuerExposure.run_id == run_id)
        .order_by(IssuerExposure.ticker))).scalars().all())

    collinear = bool(metrics.collinear) if metrics is not None and metrics.collinear is not None else None
    meta = None
    if metrics is not None and metrics.observations is not None:
        meta = {
            "alpha": _f(metrics.alpha),
            "residual": _f(metrics.residual),
            "model_r_squared": _f(metrics.model_r_squared),
            "observations": int(metrics.observations),
            "regression_window_days": (None if metrics.regression_window_days is None
                                       else int(metrics.regression_window_days)),
            "max_vif": _f(metrics.max_vif),
            "collinear": collinear,
            "attribution_date": (metrics.attribution_date.isoformat()
                                 if metrics.attribution_date else None),
        }

    return {
        "run_id": run_id,
        "portfolio_id": run.portfolio_id,
        "as_of": run.as_of_date.isoformat(),
        # The return the ATTRIBUTION explains, which is not pnl's daily_return.
        # Both are carried, named apart, because a reader who sees one number
        # called "the return" and a residual that does not close against it has
        # no way to discover that two valuation conventions are in play.
        "attribution_portfolio_return": None if metrics is None else _f(metrics.attribution_portfolio_return),
        "daily_return": None if metrics is None else _f(metrics.daily_return),
        "daily_pnl": None if metrics is None else _f(metrics.daily_pnl),
        "factors": [
            {
                "factor_name": f.factor_name,
                "factor_ticker": f.factor_ticker,
                "beta": _f(f.beta),
                "factor_return": _f(f.factor_return),
                "contribution": _f(f.contribution),
                "r_squared": _f(f.r_squared),
                # The docstring argument, as a field. None when the run recorded
                # no VIF: unknown is not the same as fine.
                "quotable_individually": (None if collinear is None else not collinear),
            }
            for f in factors
        ],
        "factor_note": (
            None if not collinear else
            "These factors are collinear (max VIF above 5). Their SUM is well determined; "
            "no single beta is. Quote the total factor contribution, not one coefficient."
        ),
        "positions": [
            {"ticker": p.ticker, "sector": p.sector, "weight": _f(p.weight),
             "daily_return": _f(p.daily_return), "contribution": _f(p.contribution),
             "market_value": _f(p.market_value), "daily_pnl": _f(p.daily_pnl)}
            for p in positions
        ],
        "metadata": meta,
        "metadata_note": (None if meta is not None else
                          "this run predates the regression record; its window and observation "
                          "count were never written and cannot be reconstructed"),
        "cite": run_id,
    }


# ── A2: risk state ────────────────────────────────────────────────────────────

# The tail measures, and what each one is a statement about. A bare "VaR of
# 2.3%" is not a fact until it says at what confidence, over what horizon, from
# how many observations — and the payload used to let one be written by handing
# over a naked column. Packing them means the model cannot quote the number
# without the qualifiers travelling beside it.
_TAIL = {
    "var_95_1d": {"measure": "value_at_risk", "confidence": 0.95, "horizon_days": 1},
    "expected_shortfall_95": {"measure": "expected_shortfall", "confidence": 0.95, "horizon_days": 1},
}
_PLAIN_METRICS = (
    "portfolio_market_value", "daily_pnl", "daily_return", "gross_exposure", "net_exposure",
    "gross_exposure_pct", "net_exposure_pct", "rolling_vol_30d", "rolling_vol_60d",
    "max_drawdown", "stress_loss_tech", "stress_loss_rates", "stress_loss_credit",
    "stress_loss_market",
)


async def get_risk_state(db: AsyncSession, run_id: str) -> dict:
    """One run's measured risk state: metrics, scenarios, alerts.

    Every number here describes the book on `as_of` under the shocks named. None
    of it is a forecast, and `not_a_forecast` says so in the payload rather than
    in a prompt, because the payload is what the model reads last.
    """
    run = await _run_or_error(db, run_id)
    if isinstance(run, dict):
        return run

    m = (await db.execute(
        select(ExposureMetrics).where(ExposureMetrics.run_id == run_id))).scalar_one_or_none()
    scenarios = list((await db.execute(
        select(StressResult).where(StressResult.run_id == run_id)
        .order_by(StressResult.scenario))).scalars().all())
    alerts = list((await db.execute(
        select(RiskAlert).where(RiskAlert.run_id == run_id)
        .order_by(RiskAlert.alert_type))).scalars().all())
    checks = list((await db.execute(
        select(LimitCheck).where(LimitCheck.run_id == run_id)
        .order_by(LimitCheck.limit_type))).scalars().all())

    metrics = None
    if m is not None:
        metrics = {k: _f(getattr(m, k)) for k in _PLAIN_METRICS}
        for col, spec in _TAIL.items():
            v = _f(getattr(m, col))
            metrics[col] = None if v is None else {
                **spec, "value": v,
                "observations": None if m.observations is None else int(m.observations),
                "lookback_days": (None if m.regression_window_days is None
                                  else int(m.regression_window_days)),
            }

    return {
        "run_id": run_id,
        "portfolio_id": run.portfolio_id,
        "as_of": run.as_of_date.isoformat(),
        "status": run.status,
        "metrics": metrics,
        "scenarios": [
            {"scenario": s.scenario, "description": s.description, "status": s.status,
             "loss_pct": _f(s.loss_pct), "loss_usd": _f(s.loss_usd),
             "shocks": s.shocks, "factors_held_flat": s.factors_held_flat,
             "reason": s.reason}
            for s in scenarios
        ],
        # The half of the limit story that was never citable: the checks that ran
        # and stayed quiet. Counts, because the sentence that wants them is
        # "twenty-four of twenty-seven were clear".
        "limit_checks": {
            "evaluated": len(checks),
            "fired": sum(1 for c in checks if c.fired),
            "clear": sum(1 for c in checks if not c.fired),
            "types_clear": [c.limit_type for c in checks if not c.fired],
        },
        "alerts": [_alert_row(a) for a in alerts],
        "not_a_forecast": True,
        "cite": run_id,
    }


# ── A3: alerts and limits ─────────────────────────────────────────────────────

def _alert_row(a: RiskAlert) -> dict:
    """One alert, whole, with the sentence its three numbers make.

    V3's corpus contains the reason for `reads_as`: an alert row holds 0.158,
    0.15 and 0.792 at once, the gate checks that a written number is HELD by the
    cited evidence, and it cannot check which of the three a sentence is
    attributing to what. "AAPL is 79.2% concentrated" passes. So the sentence is
    composed here, by code that knows which number is which.

    Which number is which had to be read out of `_check_one`, and the V8 plan's
    own example sentence — "15.8% vs limit 15.0%, utilisation is current/limit"
    — turns out to be wrong about this codebase. Two levels exist per check:

        limit_value  = the level CROSSED (breach_level if breached, else warning_level)
        utilization  = current_value / breach_level, ALWAYS

    So on a warning-severity alert the denominator of utilisation is a level this
    row does not carry, and a sentence reading "76.5% of the limit of 0.12" is
    false by a factor of the gap between the two tiers — measured live: LLY at
    0.1377 crossed a warning of 0.12 with utilisation 0.765, which is against a
    breach level of 0.18. Writing that sentence from the plan's assumption would
    have built the misattribution INTO the thing that exists to prevent it.
    """
    cur, lim, util = _f(a.current_value), _f(a.limit_value), _f(a.utilization)
    who = a.entity_id or a.alert_type
    reads_as = None
    if cur is not None and lim is not None:
        head = f"{who}: {cur:.4g} against the {a.severity} level of {lim:.4g}"
        if util is None:
            reads_as = head
        elif a.severity == "breach":
            # Here and only here the two coincide, by _check_one's construction.
            reads_as = (f"{head} — {util:.1%} of that level is used. "
                        f"{util:.1%} is a share of a limit, never a level in itself.")
        else:
            reads_as = (f"{head} — utilisation {util:.1%} is measured against the higher BREACH "
                        f"level, which this alert does not carry, NOT against {lim:.4g}. "
                        f"{util:.1%} is a share of a limit, never a level in itself.")
    return {
        "id": a.id, "alert_type": a.alert_type, "severity": a.severity,
        "entity_type": a.entity_type, "entity_id": a.entity_id,
        "current_value": cur, "limit_value": lim, "utilization": util,
        "message": a.message, "reads_as": reads_as,
    }


async def list_run_alerts(db: AsyncSession, run_id: str) -> dict:
    run = await _run_or_error(db, run_id)
    if isinstance(run, dict):
        return run
    alerts = list((await db.execute(
        select(RiskAlert).where(RiskAlert.run_id == run_id)
        .order_by(RiskAlert.severity, RiskAlert.alert_type))).scalars().all())
    checks = list((await db.execute(
        select(LimitCheck).where(LimitCheck.run_id == run_id))).scalars().all())
    return {
        "run_id": run_id, "as_of": run.as_of_date.isoformat(),
        "alerts": [_alert_row(a) for a in alerts],
        "checks_run": len(checks),
        "checks_clear": sum(1 for c in checks if not c.fired),
        "cite": run_id,
    }


async def list_risk_limits(db: AsyncSession, portfolio_id: str) -> dict:
    """The thresholds in force for a book — the policy, not a measurement.

    These rows are the runtime source of every threshold since V2-H4. They carry
    no evidence id because they are not evidence about the world: they are what
    this desk decided. A claim about a limit LEVEL is supported by the alert that
    cites it, and an alert is a run child.
    """
    rows = list((await db.execute(
        select(RiskLimit).where(RiskLimit.portfolio_id == portfolio_id)
        .order_by(RiskLimit.limit_type, RiskLimit.entity_id))).scalars().all())
    if not rows:
        return {"error": "no_limits", "portfolio_id": portfolio_id,
                "detail": "this portfolio has no limit rows; it may not be yours or may not exist"}
    return {
        "portfolio_id": portfolio_id,
        "limits": [
            {"limit_type": r.limit_type, "entity_type": r.entity_type, "entity_id": r.entity_id,
             "warning_level": _f(r.warning_level), "breach_level": _f(r.breach_level),
             "unit": r.unit, "is_active": r.is_active}
            for r in rows
        ],
        "note": "policy this desk set, not a measurement — these are not citable evidence",
    }


# ── A4: freshness ─────────────────────────────────────────────────────────────

async def get_run_freshness(db: AsyncSession, portfolio_id: str) -> dict:
    """How old the newest completed run is, in sessions rather than in days.

    Two dates, kept apart, for the reason positions_with_weights already
    demonstrates: "the last run was Thursday" and "the market has traded twice
    since" are different facts, and collapsing them into "2 days old" over a
    weekend produces a number that is wrong in both directions.
    """
    latest = (await db.execute(
        select(ExposureRun).where(ExposureRun.portfolio_id == portfolio_id,
                                  ExposureRun.status == "completed")
        # Two runs can share an as_of_date — a re-run of the same session is the
        # normal case, not an edge one — and `latest` then depended on the plan
        # order. Break the tie on when the run finished, which is what "latest"
        # means when the reporting dates are equal.
        .order_by(ExposureRun.as_of_date.desc(),
                  ExposureRun.completed_at.desc().nullslast(),
                  ExposureRun.created_at.desc()).limit(1))).scalar_one_or_none()
    in_flight = (await db.execute(
        select(func.count()).select_from(ExposureRun)
        .where(ExposureRun.portfolio_id == portfolio_id,
               ExposureRun.status.in_(("pending", "running"))))).scalar_one()
    latest_session: date | None = (await db.execute(
        select(func.max(MarketPrice.price_date)))).scalar_one_or_none()

    sessions_behind = None
    if latest is not None and latest_session is not None:
        sessions_behind = (await db.execute(
            select(func.count(func.distinct(MarketPrice.price_date)))
            .where(MarketPrice.price_date > latest.as_of_date))).scalar_one()

    return {
        "portfolio_id": portfolio_id,
        "latest_completed_run": None if latest is None else latest.id,
        "run_as_of": None if latest is None else latest.as_of_date.isoformat(),
        "latest_market_session": None if latest_session is None else latest_session.isoformat(),
        "sessions_behind": sessions_behind,
        "runs_in_flight": int(in_flight),
        "detail": ("no completed run for this portfolio yet" if latest is None else None),
    }
