"""
ExposureWorkflow — orchestrates the full deterministic portfolio risk pipeline.

Each step is wrapped with workflow_event logging so the UI can show a live timeline.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from exposure_workbench.analytics.exposure import calc_exposure, ExposureResult
from exposure_workbench.analytics.pnl import calc_pnl, PnlResult
from exposure_workbench.analytics.factor_model import calc_factor_attribution, FactorAttributionResult
from exposure_workbench.analytics.risk_metrics import calc_risk_metrics, RiskResult
from exposure_workbench.analytics.stress import calc_stress, StressResult
from exposure_workbench.analytics.limits import AlertResult, CheckRecord, LimitBook, check_limits
from exposure_workbench.db.models import (
    ExposureMetrics, SectorExposure, IssuerExposure,
    FactorAttribution, RiskAlert, DailyReport, LimitCheck,
    # Aliased: this module already has a `StressResult` — the analytics
    # dataclass the workflow computes with. Two names for two different things
    # is how one of them silently becomes the other.
    StressResult as StressResultRow,
)
from exposure_workbench.errors import RunRefused, classify, detail_of, speaks_for_itself
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider
from exposure_workbench.services import (
    exposure_run_service,
    portfolio_service,
    workflow_event_service,
    market_data_service,
    market_data_ingestion_service,
    report_verification,
)
from exposure_workbench.utils.ids import new_alert_id, new_id
from exposure_workbench.workflow.contracts import WorkflowInput, WorkflowOutput

logger = logging.getLogger(__name__)

# Calendar days of price history to load. Three years, because that is where the
# numbers stop moving. Measured on port_001 by rolling the window forward one day
# at a time, sixty times, and reading the spread of stress_loss_market:
#
#     observations   roll range / mean   swing from 2 more obs   VaR tail obs
#         60             61.7%                 17.7%                  3
#        125             25.7%                  5.9%                  6
#        250             14.0%                  1.5%                 12
#        500              6.2%                  1.0%                 25
#        750              3.7%                  0.7%                 37
#
# The 56% jump that V5 recorded between two runs was not an anomaly — 60
# observations is simply a window whose answer moves that much. At 750 the same
# measurement is 0.05pp, which is a number that can be quoted.
#
# What this does NOT fix, measured the same way: max VIF never falls below 5 at
# ANY window length and RISES with it (14.6 at 60 obs, 18.8 at 750), because
# corr(SPY, QQQ) goes from 0.920 to 0.948 over longer samples. Individual betas
# stay unquotable; only shrinkage or a smaller factor set touches that.
#
# 1200 calendar days and not 1095, which is the three years the table above is
# about. The regression asks for the last 750 observations, and three years of
# calendar supplies about 756 — six to spare, which is not a margin. A market
# closure, or one holding missing a bar, comes off the top of the panel and the
# regression would start quietly running on less than it asked for. That is the
# state V5 shipped: 90 calendar days yielded 61 observations against a window of
# 60, and nobody noticed the two numbers were coupled. The extra three months
# buys ~10% slack; tests/test_factor_and_stress.py holds the pair to it.
_LOOKBACK_DAYS = 1200


class ExposureWorkflow:
    """Runs the full exposure pipeline for one run_id."""

    def __init__(self, configs_dir: str | Path = "/app/configs"):
        self.configs_dir = Path(configs_dir)
        # There is no risk-limits config. Thresholds come from the portfolio's
        # own risk_limits rows and from nowhere else — see analytics.LimitBook.
        # A YAML here would be a second source, and this loader's "file missing →
        # warn and return {}" is what promoted check_limits' 16 hardcoded
        # defaults to the live thresholds in a container that has no /app/configs.
        self._stress_config: dict | None = None
        self._factor_config: dict | None = None

    # ── Config loaders ─────────────────────────────────────────────────────────

    def _load_configs(self) -> None:
        def _load(name: str) -> dict:
            p = self.configs_dir / name
            if p.exists():
                with open(p) as f:
                    return yaml.safe_load(f) or {}
            logger.warning("Config file not found: %s", p)
            return {}

        self._stress_config = _load("stress_scenarios.yaml")
        self._factor_config = _load("factor_config.yaml")

    def _factor_tickers(self) -> list[str]:
        """The factor set, resolved in ONE place.

        Three call sites used to inline the same comprehension over the config —
        the price load, the regression, and the ticker list handed to the
        provider — so a factor could be loaded and not regressed, or regressed
        and not refreshed, without anything disagreeing out loud.
        """
        return [
            cfg["ticker"]
            for cfg in (self._factor_config or {}).get("factors", {}).values()
            if "ticker" in cfg
        ]

    # ── Step helpers ───────────────────────────────────────────────────────────

    async def _step(
        self,
        db: AsyncSession,
        run_id: str,
        step_name: str,
        message: str,
    ):
        """Context manager: logs step start and completion, measures duration."""
        return _StepContext(db, run_id, step_name, message)

    # ── Main entry point ───────────────────────────────────────────────────────

    async def run(self, db: AsyncSession, workflow_input: WorkflowInput) -> WorkflowOutput:
        run_id = workflow_input.run_id
        portfolio_id = workflow_input.portfolio_id
        as_of_date = workflow_input.as_of_date

        self._load_configs()
        steps_completed: list[str] = []

        try:
            # ── Step 1: Sync prices ────────────────────────────────────────────
            # Lives in the workflow, not the handler, so it shows up on the run's
            # timeline. The window is the RUN's own [as_of - lookback, as_of] —
            # using date.today() here would refresh a stretch the rest of the run
            # never reads, which looks like a fix and is not one.
            ctx = _StepContext(db, run_id, "sync_prices", "Refreshing prices for held tickers and factors")
            await ctx.__aenter__()
            try:
                positions, synced, unavailable = await self._sync_prices(db, portfolio_id, as_of_date)
                factors_synced, factors_unavailable = await self._sync_factor_prices(db, as_of_date)
                ctx.message = (
                    f"Refreshed prices for {synced} of {len(positions)} holdings"
                    f" and {factors_synced} of {len(self._factor_tickers())} factors"
                    + (f"; provider had no data for {', '.join(unavailable + factors_unavailable)}"
                       if (unavailable or factors_unavailable) else "")
                )
                await ctx.__aexit__(None, None, None)
                steps_completed.append("sync_prices")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 2: Load inputs ────────────────────────────────────────────
            ctx = _StepContext(db, run_id, "load_inputs", "Loading portfolio positions and market data")
            await ctx.__aenter__()
            try:
                positions_df, prices_df, factor_prices_df, limit_book = await self._load_inputs(
                    db, portfolio_id, as_of_date, positions=positions
                )
                await ctx.__aexit__(None, None, None)
                steps_completed.append("load_inputs")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 3: Validate inputs ────────────────────────────────────────
            ctx = _StepContext(db, run_id, "validate_inputs", "Validating prices and position data")
            await ctx.__aenter__()
            try:
                self._validate_inputs(
                    positions_df, prices_df, as_of_date, limit_book,
                    factor_prices_df, self._factor_tickers(),
                )
                await ctx.__aexit__(None, None, None)
                steps_completed.append("validate_inputs")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 4: Exposure ───────────────────────────────────────────────
            ctx = _StepContext(db, run_id, "calculate_exposure", "Calculating market values and sector exposure")
            await ctx.__aenter__()
            try:
                exposure: ExposureResult = calc_exposure(positions_df, prices_df, as_of_date)
                await ctx.__aexit__(None, None, None)
                steps_completed.append("calculate_exposure")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 5: P&L ────────────────────────────────────────────────────
            ctx = _StepContext(db, run_id, "calculate_pnl", "Computing daily P&L and return attribution")
            await ctx.__aenter__()
            try:
                pnl: PnlResult = calc_pnl(positions_df, prices_df, as_of_date)
                await ctx.__aexit__(None, None, None)
                steps_completed.append("calculate_pnl")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 6: Factor attribution ─────────────────────────────────────
            ctx = _StepContext(db, run_id, "calculate_attribution", "Running factor regression and attribution")
            await ctx.__aenter__()
            try:
                portfolio_returns = market_data_service.build_portfolio_returns(
                    positions_df, prices_df
                )
                factor_returns_df = market_data_service.build_factor_returns_df(factor_prices_df)
                # No "keep whatever happens to be present" filter here any more.
                # Step 3 has already refused the run unless every configured
                # factor has a fresh price, so the columns ARE the factor set —
                # and if they somehow are not, that is a fact worth raising over
                # rather than quietly regressing a smaller model.
                factor_returns_subset = factor_returns_df[self._factor_tickers()]

                regression_cfg = (self._factor_config or {}).get("regression", {})
                factor_result: FactorAttributionResult = calc_factor_attribution(
                    portfolio_returns,
                    factor_returns_subset,
                    self._factor_config or {},
                    lookback=int(regression_cfg.get("window_days", 60)),
                    min_observations=int(regression_cfg.get("min_observations", 30)),
                    include_intercept=bool(regression_cfg.get("include_intercept", True)),
                )
                # What the regression actually was, in a form a query can read.
                # `collinear` is the honest caveat on every individual beta on
                # the page: SPY/QQQ/IWM are ~0.9 correlated, so the fit is
                # well-determined as a whole and each coefficient is not.
                ctx.payload = {
                    "observations": factor_result.observations,
                    "r_squared": factor_result.r_squared,
                    "alpha": factor_result.alpha,
                    "max_vif": factor_result.max_vif,
                    "collinear": factor_result.collinear,
                    "attribution_date": (
                        factor_result.as_of.isoformat() if factor_result.as_of else None
                    ),
                }
                await ctx.__aexit__(None, None, None)
                steps_completed.append("calculate_attribution")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 7: Risk metrics ───────────────────────────────────────────
            ctx = _StepContext(db, run_id, "calculate_risk", "Computing VaR, volatility and stress scenarios")
            await ctx.__aenter__()
            try:
                risk: RiskResult = calc_risk_metrics(portfolio_returns)
                # Scenarios reach the book through the betas estimated in step 6
                # and through nothing else — see analytics/stress.py for what
                # matching shocks against sector labels used to produce.
                stress: StressResult = calc_stress(
                    exposure.portfolio_market_value,
                    self._stress_config or {},
                    factor_result.betas(),
                )
                # A scenario that could not be propagated is NOT a scenario with
                # zero loss, and the limit engine only sees the ones that were.
                # observations is what VaR, ES and max drawdown were computed
                # over — the whole panel, not a tail of it. It is recorded
                # because those three change MEANING with the window: at 61
                # observations max_drawdown was "the worst fall in three months"
                # and at 752 it is "the worst fall in three years", measured on
                # this book as 5.9% against 17.7%. Same column, same name,
                # different question, and only this number says which.
                ctx.payload = {
                    "observations": int(len(portfolio_returns)),
                    "lookback_days": _LOOKBACK_DAYS,
                    "scenarios_evaluated": {
                        s.name: {"factors_held_flat": s.factors_held_flat}
                        for s in stress.scenarios
                    },
                    "scenarios_unevaluated": [
                        {"name": u.name, "reason": u.reason} for u in stress.unevaluated
                    ],
                }
                await ctx.__aexit__(None, None, None)
                steps_completed.append("calculate_risk")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 8: Limit checks ───────────────────────────────────────────
            ctx = _StepContext(db, run_id, "check_limits", "Checking risk limits and generating alerts")
            await ctx.__aenter__()
            try:
                alerts: list[AlertResult]
                alerts, evaluated, limit_checks = check_limits(
                    risk_metrics_result=risk,
                    stress_result=stress,
                    exposure_result=exposure,
                    pnl_result=pnl,
                    limits=limit_book,
                )
                # What this step ACTUALLY did, in a form a query can read. The
                # message says how many alerts; it cannot say that three of the
                # eight checks never ran because the book has too little price
                # history for a VaR. `inert_overrides` is the other half: a
                # threshold the desk set on a name the book does not hold.
                ctx.payload = {
                    "evaluated": evaluated,
                    "inert_overrides": limit_book.inert_overrides(),
                }
                await ctx.__aexit__(None, None, None)
                steps_completed.append("check_limits")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 9: Compare previous run ──────────────────────────────────
            ctx = _StepContext(db, run_id, "compare_previous_run", "Comparing with previous run")
            await ctx.__aenter__()
            try:
                prev_run_stub = await exposure_run_service.get_latest_completed_run(
                    db, portfolio_id, before_run_id=run_id
                )
                prev_sector_weights: dict[str, float] = {}
                if prev_run_stub:
                    # Use get_run to ensure sector_exposures are eager-loaded
                    prev_run_full = await exposure_run_service.get_run(db, prev_run_stub.id)
                    if prev_run_full and prev_run_full.sector_exposures:
                        prev_sector_weights = {
                            se.sector: float(se.weight or 0)
                            for se in prev_run_full.sector_exposures
                        }
                await ctx.__aexit__(None, None, None)
                steps_completed.append("compare_previous_run")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                prev_sector_weights = {}

            # ── Step 10: Persist outputs ────────────────────────────────────────
            ctx = _StepContext(db, run_id, "persist_outputs", "Persisting results to database")
            await ctx.__aenter__()
            try:
                await self._persist_outputs(
                    db, run_id, portfolio_id, as_of_date,
                    exposure, pnl, factor_result, risk, stress, alerts, evaluated,
                    limit_checks, prev_sector_weights,
                )
                await db.commit()
                await ctx.__aexit__(None, None, None)
                steps_completed.append("persist_outputs")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 11: Generate report (best-effort) ─────────────────────────
            # Best-effort means the RUN survives a refused report, not that the
            # refusal is quiet: __aexit__ writes the exception into the step's
            # message, so "3 of 45 numbers in the report are not supported by
            # this run: ..." is on the timeline. The one thing that must never
            # happen here is a persisted report nobody can tell from a checked
            # one — which is what the two nested `except Exception` handlers
            # this replaced were doing, 9 times in 19.
            ctx = _StepContext(db, run_id, "generate_report", "Generating LLM executive summary and report")
            await ctx.__aenter__()
            try:
                report_id, ctx.payload = await self._generate_report(
                    db, run_id, portfolio_id, as_of_date,
                    exposure, pnl, factor_result, risk, stress, alerts,
                )
                await db.commit()
                await ctx.__aexit__(None, None, None)
                steps_completed.append("generate_report")
            except Exception as e:
                logger.warning("Report generation failed (non-fatal): %s", e)
                await ctx.__aexit__(type(e), e, None)
                report_id = None

            return WorkflowOutput(
                run_id=run_id,
                status="completed",
                steps_completed=steps_completed,
                report_id=report_id,
            )

        except Exception as e:
            logger.error("Workflow failed for run %s: %s", run_id, e, exc_info=True)
            return WorkflowOutput(
                run_id=run_id,
                status="failed",
                steps_completed=steps_completed,
                error=str(e),
                error_code=classify(e),
            )

    # ── Load inputs ────────────────────────────────────────────────────────────

    @staticmethod
    async def _positions_for(db: AsyncSession, portfolio_id: str, as_of_date: date) -> list:
        """The run's holdings, resolved the one way the whole workflow agrees on.

        get_positions filters as_of_date by EXACT equality, while uploads date a
        snapshot by max(price_date) and a run's as_of defaults to today — so the
        two normally differ and the fallback is the branch that actually fires.
        Shared rather than duplicated because a copy that skipped the fallback
        would return nothing and turn its step into a permanently green no-op.
        """
        positions = await portfolio_service.get_positions(db, portfolio_id, as_of_date)
        if not positions:
            positions = await portfolio_service.get_positions_latest(db, portfolio_id)
        return positions

    async def _sync_prices(
        self,
        db: AsyncSession,
        portfolio_id: str,
        as_of_date: date,
    ) -> tuple[list, int, list[str]]:
        """Pull fresh bars for every held ticker over the run's own window.

        Per ticker, and swallowing only "the provider has nothing for this
        symbol": ingest_market_prices raises on the FIRST empty result, which
        would hide every other missing name behind whichever one sorted first.
        Whether a gap is fatal is not decided here — step 3 is the single place
        that judges, so it can name all of them at once.
        """
        positions = await self._positions_for(db, portfolio_id, as_of_date)
        tickers = sorted({p.ticker for p in positions})
        if not tickers:
            return positions, 0, []

        provider = YFinanceMarketDataProvider()
        start_date = as_of_date - timedelta(days=_LOOKBACK_DAYS)
        synced, unavailable = 0, []
        for ticker in tickers:
            try:
                counts = await market_data_ingestion_service.ingest_market_prices(
                    db, [ticker], start_date, as_of_date, provider, commit=False,
                )
                # Commit per ticker rather than once at the end. market_prices is
                # shared and every write is an upsert, so there is nothing to make
                # atomic across tickers — while holding one transaction open would
                # keep each ticker's row locks for the whole remaining loop, i.e.
                # across every subsequent provider network call. Two runs sharing
                # a holding would then block each other for seconds at a time.
                await db.commit()
                synced += 1 if counts.get(ticker) else 0
            except market_data_ingestion_service.MarketDataUnavailable:
                unavailable.append(ticker)
            except Exception:
                # A DB failure marks the transaction rollback-only, and the event
                # write in __aexit__ would then raise something that reads like
                # the cause. Leave the session clean before propagating.
                await db.rollback()
                raise
        return positions, synced, unavailable

    async def _sync_factor_prices(
        self,
        db: AsyncSession,
        as_of_date: date,
    ) -> tuple[int, list[str]]:
        """Refresh the factor panel over the run's own window.

        Nothing refreshed factor_prices before this. The table was populated once
        by scripts/seed_demo_db.py and never again, so the "most recent day
        factor return" that every 1-day attribution is built from was whatever
        day the seed last saw — measured on the live database, four days older
        than the newest holding price, and drifting further with every day the
        seed was not re-run. The regression is an inner join on date, so the
        whole attribution silently described an older session than the run it was
        filed under. Step 3 judges the result; this only fetches.
        """
        tickers = self._factor_tickers()
        if not tickers:
            return 0, []

        provider = YFinanceMarketDataProvider()
        start_date = as_of_date - timedelta(days=_LOOKBACK_DAYS)
        synced, unavailable = 0, []
        for ticker in tickers:
            try:
                counts = await market_data_ingestion_service.ingest_factor_prices(
                    db, [ticker], start_date, as_of_date, provider,
                )
                synced += 1 if counts.get(ticker) else 0
            except market_data_ingestion_service.MarketDataUnavailable:
                unavailable.append(ticker)
            except Exception:
                await db.rollback()
                raise
        return synced, unavailable

    async def _load_inputs(
        self,
        db: AsyncSession,
        portfolio_id: str,
        as_of_date: date,
        positions: list | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict]]:
        """Load positions, prices, factor prices, and limits from DB."""

        if positions is None:
            positions = await self._positions_for(db, portfolio_id, as_of_date)

        positions_df = pd.DataFrame([
            {
                "ticker": p.ticker,
                "quantity": float(p.quantity),
                "sector": p.sector or "Unknown",
                "asset_class": p.asset_class or "equity",
                "cost_basis": float(p.cost_basis) if p.cost_basis else None,
                "price": float(p.price) if p.price else None,
                "market_value": float(p.market_value) if p.market_value else None,
            }
            for p in positions
        ]) if positions else pd.DataFrame(columns=["ticker", "quantity", "sector", "asset_class"])

        tickers = positions_df["ticker"].tolist() if not positions_df.empty else []
        start_date = as_of_date - timedelta(days=_LOOKBACK_DAYS)

        prices_df = await market_data_service.get_prices_df(
            db, tickers, start_date, as_of_date
        )

        # Load factor prices
        factor_prices_df = await market_data_service.get_factor_prices_df(
            db, self._factor_tickers(), start_date, as_of_date
        )

        # Every threshold this run will use. active_only=False on purpose: the
        # LimitBook drops inactive rows from the thresholds itself, but it also
        # has to see them to report a limit_type the engine cannot evaluate.
        # Filtering here instead would make `is_active = false` the way to hide
        # a typo'd limit_type from the completeness check.
        rows = await portfolio_service.get_risk_limits(db, portfolio_id, active_only=False)
        limit_book = LimitBook([
            {
                "id": lim.id,
                "limit_type": lim.limit_type,
                "entity_id": lim.entity_id,
                "warning_level": lim.warning_level,
                "breach_level": lim.breach_level,
                "unit": lim.unit,
                "is_active": lim.is_active,
            }
            for lim in rows
        ])

        return positions_df, prices_df, factor_prices_df, limit_book

    # ── Validation ─────────────────────────────────────────────────────────────

    @staticmethod
    def _newest_by_ticker(prices_df: pd.DataFrame, as_of_ts: pd.Timestamp) -> pd.Series:
        usable = prices_df[prices_df["price_date"] <= as_of_ts]
        return usable.groupby("ticker")["price_date"].max()

    @staticmethod
    def _unadjusted_rows(prices_df: pd.DataFrame, as_of_ts: pd.Timestamp) -> list[str]:
        """Tickers holding bars with no adjusted close, and how many.

        A bar without adj_close is invisible to every return series — the panel
        drops the date and says nothing. That is how a window can be three years
        long and produce sixty observations: V5 added factor_prices.adj_close and
        deliberately did not backfill it, so 233 of 295 rows were null the day
        this window was widened. Step 1 refills them from the provider before
        this runs, so reaching here means the refill did not happen, and the
        alternative to refusing is a run that reports the sample size it wishes
        it had.
        """
        if prices_df.empty or "adj_close" not in prices_df.columns:
            return []
        usable = prices_df[prices_df["price_date"] <= as_of_ts]
        holes = usable[usable["adj_close"].isna()]
        if holes.empty:
            return []
        counts = holes.groupby("ticker").size()
        return sorted(f"{ticker} ({n})" for ticker, n in counts.items())

    def _validate_inputs(
        self,
        positions_df: pd.DataFrame,
        prices_df: pd.DataFrame,
        as_of_date: date,
        limits: LimitBook,
        factor_prices_df: pd.DataFrame,
        factor_tickers: list[str],
    ) -> None:
        """The single place a run decides its inputs are good enough.

        Everything downstream may now assume every holding has a usable, recent
        price — which is what lets calc_exposure and calc_pnl drop their
        fallbacks. Before this existed, an unpriced holding was valued at $0 but
        left in the denominator, so the run went green while every OTHER name's
        weight was inflated: a two-name book with one bad ticker reported the
        survivor at 100% instead of 71%, which is enough to fabricate a
        concentration breach out of nothing.

        Since V2-H4 it judges the portfolio's LIMITS by the same standard, in the
        same raise. A missing threshold is an input problem exactly as a missing
        price is: check_limits has no default to fall back on, so the run would
        die at step 8 having already paid for a price sync, a factor regression
        and a stress pass before learning its policy was incomplete. And a book
        with both a stale price and a missing limit should cost one
        fix-and-rerun cycle, not two.

        All problems are reported as complete lists. Naming only the first turns
        one fix-and-rerun cycle into as many as there are bad tickers.

        Since V5 the FACTOR panel is judged by the same rule as the holdings.
        Nothing judged it before, and nothing refreshed it either, so a factor
        whose newest bar was months old passed straight into the regression and
        the stress propagation built on it — and a factor missing entirely was
        dropped from the regression by a silent `if t in df.columns` filter,
        leaving a smaller model that reported itself with the same confidence.
        The two failures are the same shape as a stale holding price, so they get
        the same answer: name them all, refuse the run, let step 1's refresh fix
        it on the re-run.

        This method stays PURE — no DB, no clock. The LimitBook is built in
        _load_inputs and handed in, with no default: a default parameter here
        would be a threshold source of its own.
        """
        if positions_df.empty:
            raise RunRefused("No positions found for the given portfolio and date")
        if prices_df.empty:
            raise RunRefused("No market prices found — ensure seed data is loaded")

        held = set(positions_df["ticker"].astype(str))
        as_of_ts = pd.Timestamp(as_of_date)
        max_age = get_settings().price_staleness_days
        newest = self._newest_by_ticker(prices_df, as_of_ts)

        missing = sorted(held - set(newest.index.astype(str)))
        stale = sorted(
            f"{ticker} ({(as_of_ts - newest[ticker]).days}d old)"
            for ticker in held & set(newest.index.astype(str))
            if (as_of_ts - newest[ticker]).days > max_age
        )

        problems = []
        if missing:
            problems.append(f"no price on or before {as_of_date} for: {', '.join(missing)}")
        if stale:
            problems.append(f"newest price older than {max_age} days for: {', '.join(stale)}")

        unadjusted = self._unadjusted_rows(prices_df, as_of_ts)
        if unadjusted:
            problems.append(
                "bars with no adjusted close (they are invisible to every return "
                "series, so the window would silently shrink) for: "
                + ", ".join(unadjusted)
            )

        wanted_factors = set(factor_tickers)
        if wanted_factors:
            factor_newest = (
                self._newest_by_ticker(factor_prices_df, as_of_ts)
                if not factor_prices_df.empty
                else pd.Series(dtype="datetime64[ns]")
            )
            have = set(factor_newest.index.astype(str))
            factors_missing = sorted(wanted_factors - have)
            factors_stale = sorted(
                f"{ticker} ({(as_of_ts - factor_newest[ticker]).days}d old)"
                for ticker in wanted_factors & have
                if (as_of_ts - factor_newest[ticker]).days > max_age
            )
            if factors_missing:
                problems.append(
                    f"no factor price on or before {as_of_date} for: "
                    + ", ".join(factors_missing)
                )
            if factors_stale:
                problems.append(
                    f"newest factor price older than {max_age} days for: "
                    + ", ".join(factors_stale)
                )
            factors_unadjusted = self._unadjusted_rows(factor_prices_df, as_of_ts)
            if factors_unadjusted:
                problems.append(
                    "factor bars with no adjusted close for: "
                    + ", ".join(factors_unadjusted)
                )

        missing_limits = limits.missing_required()
        if missing_limits:
            problems.append(
                "no active risk-limit row for: " + ", ".join(missing_limits)
                + " (each limit type needs one row with entity_id NULL;"
                  " per-entity rows are overrides, not substitutes)"
            )
        # Reported from ALL rows, active or not — see _load_inputs. A row naming
        # a check the engine cannot run is the stress_loss_tech failure: served
        # to the user as policy in force, looked up by nothing.
        if limits.unknown_types:
            problems.append(
                "risk-limit rows name checks that do not exist: "
                + ", ".join(limits.unknown_types)
            )

        if problems:
            # RunRefused, not ValueError, and the difference is what the reader
            # sees. This sentence names the date, the holdings and the way out —
            # it was written for them. The class is how the UI knows to show it
            # rather than substitute a code's generic wording (V13-S2).
            raise RunRefused(
                "Cannot value this portfolio as of "
                f"{as_of_date} — " + "; ".join(problems)
                + ". Re-run once the data is available, or remove the holdings."
            )

    # ── Persist outputs ────────────────────────────────────────────────────────

    async def _persist_outputs(
        self,
        db: AsyncSession,
        run_id: str,
        portfolio_id: str,
        as_of_date: date,
        exposure: ExposureResult,
        pnl: PnlResult,
        factor_result: FactorAttributionResult,
        risk: RiskResult,
        stress: StressResult,
        alerts: list[AlertResult],
        evaluated: list[str],
        limit_checks: list[CheckRecord],
        prev_sector_weights: dict[str, float],
    ) -> None:
        # ExposureMetrics (one row per run)
        worst_stress = stress.scenarios[0] if stress.scenarios else None
        metrics = ExposureMetrics(
            run_id=run_id,
            portfolio_market_value=exposure.portfolio_market_value,
            daily_pnl=pnl.daily_pnl,
            daily_return=pnl.daily_return,
            gross_exposure=exposure.gross_exposure,
            net_exposure=exposure.net_exposure,
            gross_exposure_pct=exposure.gross_exposure / exposure.portfolio_market_value
                if exposure.portfolio_market_value > 0 else None,
            net_exposure_pct=exposure.net_exposure / exposure.portfolio_market_value
                if exposure.portfolio_market_value > 0 else None,
            rolling_vol_30d=risk.vol_30d,
            rolling_vol_60d=risk.vol_60d,
            var_95_1d=risk.var_95_1d,
            expected_shortfall_95=risk.es_95,
            max_drawdown=risk.max_drawdown,
            stress_loss_tech=next(
                (s.estimated_loss_pct for s in stress.scenarios if s.name == "tech_selloff"), None
            ),
            stress_loss_rates=next(
                (s.estimated_loss_pct for s in stress.scenarios if s.name == "rates_shock_up"), None
            ),
            stress_loss_credit=next(
                (s.estimated_loss_pct for s in stress.scenarios if s.name == "credit_spread_widening"), None
            ),
            # V8-P1. The same eight numbers the step already logs to its event
            # payload — but as columns, where the evidence resolver can reach
            # them. Read off `factor_result` and from nowhere else, so what is
            # recorded is what was fitted.
            attribution_portfolio_return=factor_result.portfolio_return,
            alpha=factor_result.alpha,
            residual=factor_result.residual,
            model_r_squared=factor_result.r_squared,
            observations=factor_result.observations,
            regression_window_days=factor_result.window_days,
            max_vif=factor_result.max_vif,
            collinear=factor_result.collinear,
            attribution_date=factor_result.as_of,
            stress_loss_market=next(
                (s.estimated_loss_pct for s in stress.scenarios if s.name == "market_downside"), None
            ),
        )
        db.add(metrics)

        # SectorExposure rows
        for sector, data in exposure.sector_map.items():
            weight_change = data["weight"] - prev_sector_weights.get(sector, data["weight"])
            db.add(SectorExposure(
                run_id=run_id,
                sector=sector,
                market_value=data["market_value"],
                weight=data["weight"],
                weight_change=weight_change,
            ))

        # IssuerExposure rows
        for pos in exposure.positions:
            pos_pnl = next((p for p in pnl.position_pnl if p.ticker == pos.ticker), None)
            db.add(IssuerExposure(
                run_id=run_id,
                ticker=pos.ticker,
                sector=pos.sector,
                market_value=pos.market_value,
                weight=pos.weight,
                weight_change=None,
                daily_pnl=pos_pnl.daily_pnl if pos_pnl else None,
                daily_return=pos_pnl.daily_return if pos_pnl else None,
                contribution=pos_pnl.contribution if pos_pnl else None,
            ))

        # FactorAttribution rows
        for fr in factor_result.factors:
            db.add(FactorAttribution(
                run_id=run_id,
                factor_name=fr.factor_name,
                factor_ticker=fr.factor_ticker,
                beta=fr.beta,
                factor_return=fr.factor_return,
                contribution=fr.contribution,
                r_squared=fr.r_squared,
            ))

        # RiskAlert rows. The id is kept rather than discarded so the limit
        # check below can name the alert it produced — otherwise "this check
        # fired" and "here is what it said" are two facts with nothing joining
        # them.
        # Keyed by CHECK, not by alert_type: one alert_type covers many checks
        # (issuer_concentration runs once per holding), so keying by type would
        # attach the first LLY alert to every issuer check that fired.
        alert_ids: dict[str, str] = {}
        for alert in alerts:
            aid = new_alert_id()
            alert_ids[alert.check_key] = aid
            db.add(RiskAlert(
                id=aid,   # alert_<hex> — must match the evidence prefix (alert_)
                run_id=run_id,
                alert_type=alert.alert_type,
                severity=alert.severity,
                entity_type=alert.entity_type,
                entity_id=alert.entity_id,
                current_value=alert.current_value,
                limit_value=alert.limit_value,
                utilization=alert.utilization,
                message=alert.message,
            ))

        # StressResult rows (V8-P2). Every scenario the step considered, in both
        # outcomes — the refusals included, and carrying WHY. An unevaluated
        # scenario cannot hold a loss here (CHECK constraint), because storing
        # it as 0.0 would turn calc_stress's refusal back into "this book is
        # safe in a rates shock" at the last possible step.
        for sc in stress.scenarios:
            db.add(StressResultRow(
                run_id=run_id,
                scenario=sc.name,
                description=sc.description,
                shocks=dict(sc.shocks),
                loss_pct=sc.estimated_loss_pct,
                loss_usd=sc.estimated_loss_usd,
                factors_held_flat=list(sc.factors_held_flat),
                status="evaluated",
                reason=None,
            ))
        for un in stress.unevaluated:
            db.add(StressResultRow(
                run_id=run_id,
                scenario=un.name,
                description=None,
                shocks={},
                loss_pct=None,
                loss_usd=None,
                factors_held_flat=[],
                status="unevaluated",
                reason=un.reason,
            ))

        # LimitCheck rows (V8-P3). The affirmative negative: every check that
        # RAN, and whether it fired. check_limits has always returned this list
        # and nothing has ever stored it, so "the other five were checked and
        # clear" was the half of the answer that could not be supported.
        # Joined on the key the CHECKER produced (AlertResult.check_key), never
        # on one rebuilt here: the entity belongs in the key only for per-entity
        # checks, while an alert's entity_id comes from LIMIT_SPECS and reads
        # "portfolio" for a book-wide one. Rebuilding it recorded 27 checks as
        # clear on a book that was alerting on three of them.
        # The numbers each check ran on, keyed the same way `evaluated` is. Built
        # from the records check_limits returned rather than re-derived here:
        # rebuilding the key is precisely what recorded 27 checks as clear on a
        # book that was alerting on three (the comment above), and re-deriving
        # the VALUES would be the same mistake with worse consequences.
        seen = {c.check_key: c for c in limit_checks}
        for limit_type in evaluated:
            record = seen.get(limit_type)
            db.add(LimitCheck(
                run_id=run_id,
                limit_type=limit_type,
                fired=limit_type in alert_ids,
                alert_id=alert_ids.get(limit_type),
                current_value=None if record is None else record.current_value,
                warning_level=None if record is None else record.warning_level,
                breach_level=None if record is None else record.breach_level,
                status=None if record is None else record.status,
            ))

        await db.flush()

    # ── Report generation ──────────────────────────────────────────────────────

    async def _generate_report(
        self,
        db: AsyncSession,
        run_id: str,
        portfolio_id: str,
        as_of_date: date,
        exposure: ExposureResult,
        pnl: PnlResult,
        factor_result: FactorAttributionResult,
        risk: RiskResult,
        stress: StressResult,
        alerts: list[AlertResult],
    ) -> tuple[str, dict]:
        """The report, or a raise naming why there is none.

        It no longer swallows. There used to be two nested `except Exception`
        handlers around this — one here returning None, one at the call site —
        and between them any reason a report failed became a log line. The step
        context already writes the exception into the timeline's message, so the
        call site's handler is the ONE place a refusal is recorded, and this
        method's job is to make sure the refusal has a sentence in it.
        """
        from exposure_workbench.agents.direct_llm_agent import ReportUnavailable
        from exposure_workbench.agents.report_agent import get_report_agent
        from exposure_workbench.agents.schemas import ReportInput

        report_input = ReportInput(
            portfolio_id=portfolio_id,
            as_of_date=str(as_of_date),
            portfolio_market_value=exposure.portfolio_market_value,
            daily_pnl=pnl.daily_pnl,
            daily_return=pnl.daily_return,
            top_contributors=[
                {"ticker": p.ticker, "contribution": p.contribution, "daily_return": p.daily_return}
                for p in pnl.top_contributors
            ],
            top_detractors=[
                {"ticker": p.ticker, "contribution": p.contribution, "daily_return": p.daily_return}
                for p in pnl.top_detractors
            ],
            sector_exposures={s: d["weight"] for s, d in exposure.sector_map.items()},
            var_95_1d=risk.var_95_1d,
            vol_30d=risk.vol_30d,
            max_drawdown=risk.max_drawdown,
            factor_attributions=[
                {
                    "factor_name": fr.factor_name,
                    "beta": fr.beta,
                    "factor_return": fr.factor_return,
                    "contribution": fr.contribution,
                }
                for fr in factor_result.factors[:5]
            ],
            stress_scenarios=[
                {
                    "name": s.name,
                    "description": s.description,
                    "loss_pct": s.estimated_loss_pct,
                }
                for s in stress.scenarios
            ],
            alerts=[
                {
                    "type": a.alert_type,
                    "severity": a.severity,
                    "entity": a.entity_id,
                    "message": a.message,
                }
                for a in alerts
            ],
        )

        agent = get_report_agent()
        report_output = await agent.generate(report_input)

        # THE GATE. Every number the report states has to be a value of a
        # deterministic row of this same run. Nothing is persisted unless all
        # of them are, because the alternative — storing a report that is
        # known to contain a figure the run does not support — is the thing
        # this whole path was rebuilt to stop. There is no retry: a report is
        # one completion, which is the premise of this module's exemption
        # from the llm_session rule, and daily_reports' three cost columns
        # are scalar (see services/report_verification.py).
        verdict = await report_verification.verify_report(db, run_id, report_output)
        if not verdict.accepted:
            raise ReportUnavailable(
                f"{len(verdict.problems)} of {verdict.checked} numbers in the "
                "report are not supported by this run: "
                + "; ".join(
                    f"{p.get('number')} (nearest: "
                    f"{(p.get('nearest') or {}).get('label', 'nothing comparable')})"
                    for p in verdict.problems[:5]
                )
            )

        report_id = new_id("report_")
        from exposure_workbench.app_state.settings import get_settings
        settings = get_settings()

        db.add(DailyReport(
            id=report_id,
            run_id=run_id,
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            agent_mode=settings.report_agent_mode,
            executive_summary=report_output.executive_summary,
            key_movements=report_output.key_movements,
            factor_explanation=report_output.factor_explanation,
            risk_alert_explanation=report_output.risk_alert_explanation,
            recommended_actions=report_output.recommended_actions,
            markdown_report=report_output.markdown_report,
            confidence_flags=report_output.confidence_flags or {},
            llm_model=report_output.llm_model,
            prompt_tokens=report_output.prompt_tokens,
            completion_tokens=report_output.completion_tokens,
        ))
        await db.flush()
        return report_id, verdict.as_payload()


# ── Step context manager ───────────────────────────────────────────────────────

class _StepContext:
    """Logs workflow_event start and completion around a step."""

    def __init__(self, db: AsyncSession, run_id: str, step_name: str, message: str):
        self.db = db
        self.run_id = run_id
        self.step_name = step_name
        self.message = message
        self._start_ms = 0
        # A step's message is prose for a human reading the timeline; it cannot
        # be queried, and "All limits within bounds" is exactly the sentence
        # that hid the real defect — check_limits skips a check whenever its
        # input is None, so a green run says nothing about which of the eight
        # checks actually executed. `payload` is where a step records that in
        # machine-readable form: the step body assigns or mutates it, and
        # __aexit__ writes it to workflow_events.payload_summary. Empty here so
        # a step that records nothing writes the same '{}' the column already
        # defaults to.
        self.payload: dict[str, Any] = {}

    async def __aenter__(self):
        self._start_ms = int(time.monotonic() * 1000)
        await workflow_event_service.log_event(
            db=self.db,
            run_id=self.run_id,
            step_name=self.step_name,
            status="running",
            message=self.message,
        )
        await self.db.commit()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int(time.monotonic() * 1000) - self._start_ms
        payload = self.payload
        if exc_type is None:
            # A body that left something other than a dict here — usually None,
            # from a helper that returned early — recorded nothing readable, and
            # log_event's `payload_summary or {}` would quietly turn that into
            # the same '{}' a step that recorded nothing writes. Two events that
            # cannot be told apart for "recorded nothing" and "lost what it
            # recorded" is the failure this attribute exists to end, so the
            # assignment fails here instead of being normalised. {} stays legal:
            # "recorded nothing" is a real state, not an error. Raising means
            # this step lands no completed event; every call site in run() wraps
            # the exit in try/except and re-enters __aexit__ with the exception,
            # so what the timeline gets instead is a 'failed' event naming the
            # malformation.
            # step_context.step.__aexit__ carries this same check, deliberately
            # identical; the parametrised tests in tests/test_step_payload.py
            # run both wrappers through it so the two cannot drift.
            if not isinstance(payload, dict):
                raise TypeError(
                    f"step '{self.step_name}' left a non-dict payload "
                    f"({payload!r}); ctx.payload must be a dict, and {{}} is how "
                    f"a step says it recorded nothing"
                )
            status = "completed"
            msg = self.message
        else:
            status = "failed"
            # Two registers, exactly as step_context.step does it and for the
            # same reason (V13-S2): the reader gets the step's own sentence, the
            # exception's words go into the payload under a code, and a refusal
            # that was written for the reader — a run that cannot value the book
            # because prices are stale — keeps its own words, because that
            # sentence names the holdings and the way out.
            code = classify(exc_val)
            msg = (f"{self.message} — {exc_val}" if speaks_for_itself(code)
                   else f"{self.message} — stopped")
            # A step that failed part-way through its own DML leaves the
            # transaction marked rollback-only, and the event write below would
            # then raise PendingRollbackError. That is not merely noisy: it
            # replaces the real cause in the timeline AND leaves the caller's
            # session poisoned, so update_run_status() fails too and the run row
            # sits at 'running' forever. The partial work is being abandoned
            # regardless; recording WHY is the entire job of this write.
            # (No step had uncommitted DML at its failure point until
            # sync_prices, which is why this never bit before.)
            await self.db.rollback()
            # The non-dict payload above is the same defect, but NOT raised
            # here: the body already has an exception in flight, and raising
            # during its handling would replace the real cause with a complaint
            # about the evidence field — the same substitution the rollback just
            # above exists to prevent, and the bigger loss of the two. It is
            # recorded instead, so the event still cannot be confused with one
            # from a step that recorded nothing.
            if not isinstance(payload, dict):
                logger.error(
                    "step '%s' left a non-dict payload (%r) while failing; "
                    "recording the malformation instead of the evidence",
                    self.step_name, payload,
                )
                payload = {"payload_error": repr(payload)}
            payload = {**payload, "error": {"code": code, "detail": detail_of(exc_val)}}

        # The payload goes out on the failure path too, for the same reason the
        # message does: this event is the run's only record of a step that died
        # part-way, and what the step managed to record before dying is the
        # first thing a reader needs — "which checks had run when it blew up" is
        # a different diagnosis from "it blew up before doing anything".
        # Dropping it here would be a silent deletion of evidence at exactly the
        # moment evidence is scarce. It cannot be mistaken for a certification:
        # the same row carries status='failed'. Note also that self.payload is
        # in-process state, so the rollback above does not touch it.
        await workflow_event_service.log_event(
            db=self.db,
            run_id=self.run_id,
            step_name=self.step_name,
            status=status,
            message=msg,
            payload_summary=payload,
            duration_ms=duration_ms,
        )
        await self.db.commit()
        return False  # don't suppress exceptions
