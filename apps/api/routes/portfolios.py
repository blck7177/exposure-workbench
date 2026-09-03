"""Portfolio routes — list portfolios, get positions, limits, and dashboard."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, computed_field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth_deps import optional_user, require_user
from exposure_workbench.analytics import withheld as wh
from exposure_workbench.analytics.methods import METHODS
from exposure_workbench.auth.clerk import UserClaims
from exposure_workbench.auth.context import current_user_id
from exposure_workbench.db.session import get_db, get_session_factory
from exposure_workbench.analytics import drawdown as dd
from exposure_workbench.analytics.risk_metrics import _TRADING_DAYS_PER_YEAR
from exposure_workbench.services import (
    calc_service, drawdown_service, exposure_run_service, market_data_service,
    portfolio_csv, portfolio_service, run_reads_service, schedule_service,
    usage_service,
)

router = APIRouter()

# A 200-row CSV is ~4 KB. This bounds the request when nothing else does — the
# reverse proxy is the real guard, but the API must not depend on being behind
# one. Pydantic enforces it before any parsing work happens.
MAX_CSV_TEXT_BYTES = 256_000


def _problem_dicts(problems) -> list[dict]:
    # CsvProblem dataclasses -> JSON; upload_positions problems are already dicts
    return [p if isinstance(p, dict) else {"row": p.row, "ticker": p.ticker, "reason": p.reason}
            for p in problems]


# ─── Response models ──────────────────────────────────────────────────────────

class PortfolioOut(BaseModel):
    id: str
    name: str
    description: str | None
    currency: str
    base_nav: float | None
    benchmark: str | None
    manager: str | None
    is_active: bool
    # V7-U2. The list endpoint answers "mine plus public" (RLS, and
    # list_visible above it), and without this field the two are
    # indistinguishable on the wire: a stranger who owns nothing and a desk
    # whose only book happens to be the shared demo produced byte-identical
    # responses. The web needs to tell them apart to know when to offer a way
    # in at all — and owner_id is not the answer to that question, because it
    # would put another tenant's identifier in front of every anonymous
    # visitor to say something this boolean says without naming anyone.
    is_public: bool
    # Carried to answer is_own and EXCLUDED from the wire, for the reason the
    # comment above gives: a tenant identifier must not travel to every visitor.
    owner_id: str | None = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_own(self) -> bool:
        """Whether the caller owns this book — the same predicate the portfolio
        snapshot and the brief already answer (`owner_id == current_user_id()`),
        answered once here so all five routes returning this model agree.

        V7-Q. `is_public` was standing in for this, and the substitution was only
        ever true while public implied somebody else's: handing port_001 to a
        real account made it that account's book AND public, and the web then
        both refused to open it and told its owner the desk was empty. Ownership
        and publicness are independent facts and are now carried as two.

        Serialised inside the request, so the contextvar is set. Outside one it
        reads None and this is False — fail-closed, and the same shape as
        brief_service's.

        semantic, not security: this decides what the UI opens on and what it
        offers; RLS decides what the caller can see at all. A row that reached
        this model was already cleared by the database."""
        return self.owner_id is not None and self.owner_id == current_user_id()

    model_config = {"from_attributes": True}


class PositionOut(BaseModel):
    id: str
    ticker: str
    asset_class: str
    sector: str | None
    region: str | None
    currency: str
    quantity: float
    cost_basis: float | None
    price: float | None
    market_value: float | None
    as_of_date: date

    model_config = {"from_attributes": True}


class RiskLimitOut(BaseModel):
    id: str
    limit_type: str
    entity_type: str | None
    entity_id: str | None
    warning_level: float
    breach_level: float
    unit: str | None
    is_active: bool

    model_config = {"from_attributes": True}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/portfolios", response_model=list[PortfolioOut])
async def list_portfolios(
    user: UserClaims | None = Depends(optional_user),
    db: AsyncSession = Depends(get_db),
):
    # V2-B: public demo + the caller's own. App-level visibility until V2-C RLS
    # makes it belt-and-suspenders.
    return await portfolio_service.list_visible(db, user.user_id if user else None)


# ─── Portfolio creation / upload / clone (V2-B, authenticated) ────────────────

class CreatePortfolioRequest(BaseModel):
    name: str
    csv_text: str | None = Field(default=None, max_length=MAX_CSV_TEXT_BYTES)


class UploadRequest(BaseModel):
    csv_text: str = Field(max_length=MAX_CSV_TEXT_BYTES)


@router.post("/portfolios", response_model=PortfolioOut, status_code=201)
async def create_portfolio(
    body: CreatePortfolioRequest,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        p = await portfolio_service.create_portfolio(db, owner_id=user.user_id, name=body.name)
    except portfolio_service.TooManyPortfolios as e:
        raise HTTPException(429, {"error": "too_many_portfolios", "limit": e.limit}) from e
    except usage_service.QuotaExceeded as e:
        raise HTTPException(429, e.as_dict()) from e
    # Note both 429s: too_many_portfolios is a permanent ceiling, quota_exceeded
    # resets tomorrow. A client branching on the status alone conflates them.
    if body.csv_text:
        rows, problems = portfolio_csv.parse_csv(body.csv_text)
        if problems:
            await db.rollback()   # atomic: bad CSV => no portfolio either
            raise HTTPException(422, {"problems": _problem_dicts(problems)})
        try:
            await portfolio_service.upload_positions(db, p.id, rows)
        except portfolio_service.UploadError as e:
            await db.rollback()
            raise HTTPException(422, {"problems": _problem_dicts(e.problems)})
    await db.commit()
    return p


@router.post("/portfolios/clone-demo", response_model=PortfolioOut, status_code=201)
async def clone_demo(
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        p = await portfolio_service.clone_demo(db, owner_id=user.user_id)
    except portfolio_service.TooManyPortfolios as e:
        raise HTTPException(429, {"error": "too_many_portfolios", "limit": e.limit}) from e
    except usage_service.QuotaExceeded as e:
        raise HTTPException(429, e.as_dict()) from e
    await db.commit()
    return p


@router.post("/portfolios/{portfolio_id}/upload")
async def upload_positions(
    portfolio_id: str,
    body: UploadRequest,
    user: UserClaims = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    p = await portfolio_service.get_portfolio(db, portfolio_id)
    if p is None:
        raise HTTPException(404, "Portfolio not found")
    # semantic, not security: RLS already makes another tenant's portfolio
    # invisible; this only turns that into a clear 403 instead of a 404.
    if p.owner_id != user.user_id:
        raise HTTPException(403, "not your portfolio")
    rows, problems = portfolio_csv.parse_csv(body.csv_text)
    if problems:
        raise HTTPException(422, {"problems": _problem_dicts(problems)})

    # Ordering is 401 -> 404 -> 403 -> 422 parse -> 429 -> 422 upload, and the
    # gate sitting AFTER the parse is deliberate: parse_csv is free server-side
    # validation, so billing a malformed file is pure friction, while everything
    # past this point either reads the database or calls yfinance — up to ~400
    # provider requests for a 200-row file.
    #
    # A gate transaction, committed before the work starts, rather than sharing
    # the request's. get_db rolls back on any raise, and the no_price_data
    # rejection is decided AFTER _backfill_prices has already spent the provider
    # calls; a shared charge would refund every rejected upload and turn this
    # into a free retry loop. Safe on an independent session because
    # db/session.py stamps the RLS tenant at the start of every transaction.
    factory = get_session_factory()
    async with factory() as gate_db, gate_db.begin():
        try:
            await usage_service.charge(gate_db, user.user_id, "position_upload")
        except usage_service.QuotaExceeded as e:
            raise HTTPException(429, e.as_dict()) from e

    try:
        result = await portfolio_service.upload_positions(db, portfolio_id, rows)
    except portfolio_service.UploadError as e:
        raise HTTPException(422, {"problems": _problem_dicts(e.problems)})
    await db.commit()
    return result


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioOut,
            dependencies=[Depends(optional_user)])
async def get_portfolio(portfolio_id: str, db: AsyncSession = Depends(get_db)):
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


@router.get("/portfolios/{portfolio_id}/positions", response_model=list[PositionOut],
            dependencies=[Depends(optional_user)])
async def get_positions(
    portfolio_id: str,
    as_of_date: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await portfolio_service.get_positions(db, portfolio_id, as_of_date)


@router.get("/portfolios/{portfolio_id}/limits", response_model=list[RiskLimitOut],
            dependencies=[Depends(optional_user)])
async def get_risk_limits(
    portfolio_id: str,
    db: AsyncSession = Depends(get_db),
):
    rows = await portfolio_service.get_risk_limits(db, portfolio_id)
    # V20. A limit on a withheld measure is policy nothing evaluates; it is not
    # shown as in force (analytics/withheld.py).
    return [r for r in rows if r.limit_type not in wh.WITHHELD_CHECKS]


# ─── Dashboard endpoint ───────────────────────────────────────────────────────

class DashboardOut(BaseModel):
    portfolio: PortfolioOut
    positions: list[PositionOut]
    limits: list[RiskLimitOut]
    latest_run_id: str | None
    latest_run_status: str | None
    latest_run_date: date | None
    metrics: dict[str, Any] | None
    sector_exposures: list[dict[str, Any]]
    issuer_exposures: list[dict[str, Any]]
    factor_attributions: list[dict[str, Any]]
    risk_alerts: list[dict[str, Any]]
    report_summary: dict[str, Any] | None


class FreshnessOut(BaseModel):
    """How old what the reader is looking at actually is (V13-S1).

    The same two dates get_run_freshness keeps apart for the agent, on the page
    for the same reason: "the last run was Thursday" and "the market has traded
    seven times since" are different facts, and the top bar was showing neither.
    A visitor met an August 20 date with nothing saying whether that was the
    newest data there is or a week of silence.
    """

    portfolio_id: str
    latest_completed_run: str | None
    run_as_of: str | None
    latest_market_session: str | None
    sessions_behind: int | None
    runs_in_flight: int
    detail: str | None
    # V13 §9-④: when the next scheduled update fires, if one is armed. None on
    # a book with no active schedule — absent, not a promise.
    next_update: str | None = None


@router.get("/portfolios/{portfolio_id}/freshness", response_model=FreshnessOut,
            dependencies=[Depends(optional_user)])
async def get_portfolio_freshness(
    portfolio_id: str,
    db: AsyncSession = Depends(get_db),
):
    # A thin wrapper over the read the agent already has, deliberately: one
    # definition of "behind", so the sentence in the top bar and the sentence in
    # an answer cannot disagree about the same book on the same day.
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(404, {"error": "unknown_portfolio", "portfolio_id": portfolio_id})
    fresh = await run_reads_service.get_run_freshness(db, portfolio_id)
    nxt = await schedule_service.next_update_for(db, portfolio_id)
    return {**fresh, "next_update": nxt.isoformat() if nxt else None}


# How far back a history chart may look, by name. Not a free integer: a caller
# asking for 30 years would scan a price table for a book that has three years of
# it, and the answer to "how much history" is a product decision, not a query
# parameter.
_SPANS = {"1y": 365, "3y": 365 * 3, "5y": 365 * 5}


@router.get("/portfolios/{portfolio_id}/history", dependencies=[Depends(optional_user)])
async def get_portfolio_history(
    portfolio_id: str,
    span: str = "3y",
    benchmark: str = "SPY",
    db: AsyncSession = Depends(get_db),
):
    """The book's value, its drawdown, and the episodes worth naming (V13-S5).

    WHAT THIS IS, said plainly because the chart cannot say it: today's holdings
    valued at historical prices. `positions` keeps one snapshot per book and
    there is no holding history to replay, so this is not what the book was
    worth — it is what this book would have been worth. The same assumption
    build_portfolio_returns has always made, and get_drawdown_episodes states in
    its own return value; it is repeated here because a line chart is the most
    persuasive way there is to imply otherwise.

    Built on market_data_service.build_portfolio_values, which is the panel the
    return series is a percentage change OF — so the last point of the rolling
    volatility here equals the tile above it, rather than nearly equalling it.
    """
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(404, {"error": "unknown_portfolio", "portfolio_id": portfolio_id})
    if span not in _SPANS:
        raise HTTPException(422, {"error": "unknown_span", "span": span,
                                  "known": sorted(_SPANS)})

    positions = await portfolio_service.get_positions(db, portfolio_id)
    holdings = [{"ticker": p.ticker, "quantity": float(p.quantity)}
                for p in positions if p.quantity is not None]
    end = await market_data_service.latest_session_date(db)
    if not holdings or end is None:
        return {"portfolio_id": portfolio_id, "span": span, "points": [],
                "episodes": [], "detail": "no priced holdings for this book"}
    start = end - timedelta(days=_SPANS[span])

    positions_df = pd.DataFrame(holdings)
    prices_df = await market_data_service.get_prices_df(
        db, positions_df["ticker"].tolist(), start, end)
    values = market_data_service.build_portfolio_values(positions_df, prices_df)
    if len(values) < 2:
        return {"portfolio_id": portfolio_id, "span": span, "points": [],
                "episodes": [], "detail": "not enough price history for this book"}

    returns = values.pct_change()
    peak = values.cummax()
    drawdown = values / peak - 1.0
    # The same 30-session window and the same annualisation the run reports, so
    # the end of this line IS the number in the tile. calc_risk_metrics is the
    # authority on both; ddof=1 and 252 are read from it rather than retyped.
    vol30 = returns.rolling(30).std(ddof=1) * math.sqrt(_TRADING_DAYS_PER_YEAR)

    # price_points answers (points, store) and chooses the store by what the
    # ticker IS to this desk — SPY has 277 sessions in the holdings table and 825
    # in the factor table, and the difference decides whether a three-year chart
    # has a benchmark line at all (V10). Calling it rather than querying is how
    # this endpoint inherits that rule instead of re-deciding it.
    bench_points, _store = await market_data_service.price_points(db, benchmark, start, end)
    bench_by_date = {p.price_date.isoformat(): float(p.close) for p in bench_points}
    base_bench = next((bench_by_date[str(d.date())] for d in values.index
                       if str(d.date()) in bench_by_date), None)
    base_value = float(values.iloc[0])

    points = []
    for i, (ts, value) in enumerate(values.items()):
        day = str(ts.date())
        b = bench_by_date.get(day)
        points.append({
            "date": day,
            "value": round(float(value), 2),
            "drawdown": round(float(drawdown.iloc[i]), 6),
            "vol_30d": (None if pd.isna(vol30.iloc[i]) else round(float(vol30.iloc[i]), 6)),
            "return": (None if i == 0 or pd.isna(returns.iloc[i])
                       else round(float(returns.iloc[i]), 8)),
            # Indexed onto the book's own starting value so one axis carries
            # both. Two y-scales on one plot invent a correlation that is not in
            # the data; indexing to a common base is the honest way to put two
            # series of different size on one chart.
            "benchmark": (None if b is None or base_bench is None
                          else round(base_value * b / base_bench, 2)),
        })

    episodes = dd.find_episodes(returns.dropna())

    # The chart's series-level citation (V13 §9 判据 B). Each daily point is not
    # a ledger row and never will be — minting one per point would be fabricating
    # provenance — but the EPISODES are a recorded calculation, and this is its
    # id. Same reuse discipline as /reconcile: the identifying key includes the
    # window's end, because tomorrow's scan of the same span is a different
    # calculation; found → reuse, absent → mint once through the same recorder
    # the agent's tool uses, so the chart and an answer cite one row.
    clean = returns.dropna()
    existing = await calc_service.find_recorded(
        db, drawdown_service.OP_EPISODES,
        drawdown_service.identifying_params(portfolio_id, span, str(clean.index[-1].date())))
    if existing is not None:
        episodes_calc_id = existing.id
    else:
        episodes_calc_id = await drawdown_service.record_episodes(
            db, portfolio_id, span, clean, episodes, dd.deepest(clean))

    return {
        "portfolio_id": portfolio_id,
        "span": span,
        "benchmark": benchmark,
        "episodes_calc_id": episodes_calc_id,
        "window": {"from": points[0]["date"], "to": points[-1]["date"],
                   "sessions": len(points)},
        "points": points,
        "episodes": [
            {"peak": e.peak_date.isoformat(), "trough": e.trough_date.isoformat(),
             "recovery": e.recovery_date.isoformat() if e.recovery_date else None,
             "depth": round(e.depth, 6), "trough_days": e.trough_days,
             "recovery_days": e.recovery_days, "recovered": e.recovery_date is not None}
            for e in episodes
        ],
        "methods": dict(METHODS),   # V20: the ⓘ text beside each measure, from the code
        "valuation_assumption": (
            "quantities are held fixed at today's holdings for the whole span — "
            "the book has one position snapshot and no holding history to replay"
        ),
    }


@router.get("/portfolios/{portfolio_id}/dashboard", response_model=DashboardOut,
            dependencies=[Depends(optional_user)])
async def get_portfolio_dashboard(
    portfolio_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated portfolio dashboard data in a single request."""
    portfolio = await portfolio_service.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    positions = await portfolio_service.get_positions(db, portfolio_id)
    limits = await portfolio_service.get_risk_limits(db, portfolio_id)

    latest_run = await exposure_run_service.get_latest_completed_run(db, portfolio_id)

    metrics = None
    sector_exposures: list[dict] = []
    issuer_exposures: list[dict] = []
    factor_attributions: list[dict] = []
    risk_alerts: list[dict] = []
    report_summary = None
    latest_run_id = None
    latest_run_status = None
    latest_run_date = None

    if latest_run:
        latest_run_id = latest_run.id
        latest_run_status = latest_run.status
        latest_run_date = latest_run.as_of_date

        full_run = await exposure_run_service.get_run(db, latest_run.id)
        if full_run:
            if full_run.metrics:
                m = full_run.metrics
                metrics = {
                    "portfolio_market_value": m.portfolio_market_value,
                    "daily_pnl": m.daily_pnl,
                    "daily_return": m.daily_return,
                    "gross_exposure_pct": m.gross_exposure_pct,
                    "net_exposure_pct": m.net_exposure_pct,
                    "rolling_vol_30d": m.rolling_vol_30d,
                    "max_drawdown": m.max_drawdown,
                    # V20: VaR, ES and the stress losses are withheld
                    # (analytics/withheld.py) and not served here either.
                }

            sector_exposures = [
                {"sector": se.sector, "market_value": se.market_value,
                 "weight": se.weight, "weight_change": se.weight_change}
                for se in (full_run.sector_exposures or [])
            ]
            issuer_exposures = [
                {"ticker": ie.ticker, "sector": ie.sector,
                 "market_value": ie.market_value, "weight": ie.weight,
                 "daily_pnl": ie.daily_pnl, "daily_return": ie.daily_return}
                for ie in (full_run.issuer_exposures or [])
            ]
            factor_attributions = [
                {"factor_name": fa.factor_name, "factor_ticker": fa.factor_ticker,
                 "beta": fa.beta, "factor_return": fa.factor_return,
                 "contribution": fa.contribution, "r_squared": fa.r_squared}
                for fa in (full_run.factor_attributions or [])
            ]
            risk_alerts = [
                {"id": ra.id, "alert_type": ra.alert_type, "severity": ra.severity,
                 "entity_type": ra.entity_type, "entity_id": ra.entity_id,
                 "current_value": ra.current_value, "limit_value": ra.limit_value,
                 "utilization": ra.utilization, "message": ra.message}
                for ra in wh.published_alerts(full_run.risk_alerts or [])
            ]
            if full_run.daily_report:
                rpt = full_run.daily_report
                report_summary = {
                    "id": rpt.id,
                    "executive_summary": rpt.executive_summary,
                    "recommended_actions": rpt.recommended_actions,
                    "markdown_report": rpt.markdown_report,
                    "agent_mode": rpt.agent_mode,
                }

    return DashboardOut(
        portfolio=PortfolioOut.model_validate(portfolio),
        positions=[PositionOut.model_validate(p) for p in positions],
        limits=[RiskLimitOut.model_validate(lim) for lim in limits],
        latest_run_id=latest_run_id,
        latest_run_status=latest_run_status,
        latest_run_date=latest_run_date,
        metrics=metrics,
        sector_exposures=sector_exposures,
        issuer_exposures=issuer_exposures,
        factor_attributions=factor_attributions,
        risk_alerts=risk_alerts,
        report_summary=report_summary,
    )
