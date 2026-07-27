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
from exposure_workbench.analytics.limits import check_limits, AlertResult
from exposure_workbench.db.models import (
    ExposureMetrics, SectorExposure, IssuerExposure,
    FactorAttribution, RiskAlert, DailyReport,
)
from exposure_workbench.app_state.settings import get_settings
from exposure_workbench.providers.yfinance_market_data_provider import YFinanceMarketDataProvider
from exposure_workbench.services import (
    exposure_run_service,
    portfolio_service,
    workflow_event_service,
    market_data_service,
    market_data_ingestion_service,
)
from exposure_workbench.utils.ids import new_alert_id, new_id
from exposure_workbench.workflow.contracts import WorkflowInput, WorkflowOutput

logger = logging.getLogger(__name__)

_LOOKBACK_DAYS = 90   # calendar days of price history to load


class ExposureWorkflow:
    """Runs the full exposure pipeline for one run_id."""

    def __init__(self, configs_dir: str | Path = "/app/configs"):
        self.configs_dir = Path(configs_dir)
        self._risk_limits_config: dict | None = None
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

        self._risk_limits_config = _load("risk_limits.yaml")
        self._stress_config = _load("stress_scenarios.yaml")
        self._factor_config = _load("factor_config.yaml")

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
            ctx = _StepContext(db, run_id, "sync_prices", "Refreshing prices for held tickers")
            await ctx.__aenter__()
            try:
                positions, synced, unavailable = await self._sync_prices(db, portfolio_id, as_of_date)
                ctx.message = (
                    f"Refreshed prices for {synced} of {len(positions)} holdings"
                    + (f"; provider had no data for {', '.join(unavailable)}" if unavailable else "")
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
                positions_df, prices_df, factor_prices_df, db_limits = await self._load_inputs(
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
                self._validate_inputs(positions_df, prices_df, as_of_date)
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
                factor_tickers = [
                    cfg["ticker"]
                    for cfg in (self._factor_config or {}).get("factors", {}).values()
                    if "ticker" in cfg
                ]
                factor_returns_df = market_data_service.build_factor_returns_df(factor_prices_df)
                # Only keep factor tickers that exist in the df
                available_factors = [t for t in factor_tickers if t in factor_returns_df.columns]
                factor_returns_subset = factor_returns_df[available_factors] if available_factors else pd.DataFrame()

                factor_result: FactorAttributionResult = calc_factor_attribution(
                    portfolio_returns,
                    factor_returns_subset,
                    self._factor_config or {},
                    lookback=int((self._factor_config or {}).get("regression", {}).get("window_days", 60)),
                )
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
                sector_weights = {s: d["weight"] for s, d in exposure.sector_map.items()}
                issuer_weights = {t: d["weight"] for t, d in exposure.issuer_map.items()}
                stress: StressResult = calc_stress(
                    sector_weights,
                    issuer_weights,
                    exposure.portfolio_market_value,
                    self._stress_config or {},
                )
                await ctx.__aexit__(None, None, None)
                steps_completed.append("calculate_risk")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 8: Limit checks ───────────────────────────────────────────
            ctx = _StepContext(db, run_id, "check_limits", "Checking risk limits and generating alerts")
            await ctx.__aenter__()
            try:
                alerts: list[AlertResult] = check_limits(
                    risk_metrics_result=risk,
                    stress_result=stress,
                    exposure_result=exposure,
                    pnl_result=pnl,
                    limits_config=self._risk_limits_config or {},
                    db_limits=db_limits,
                )
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
                    exposure, pnl, factor_result, risk, stress, alerts,
                    prev_sector_weights,
                )
                await db.commit()
                await ctx.__aexit__(None, None, None)
                steps_completed.append("persist_outputs")
            except Exception as e:
                await ctx.__aexit__(type(e), e, None)
                raise

            # ── Step 11: Generate report (best-effort) ─────────────────────────
            ctx = _StepContext(db, run_id, "generate_report", "Generating LLM executive summary and report")
            await ctx.__aenter__()
            try:
                report_id = await self._generate_report(
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
                synced += 1 if counts.get(ticker) else 0
            except market_data_ingestion_service.MarketDataUnavailable:
                unavailable.append(ticker)
            except Exception:
                # A DB failure marks the transaction rollback-only, and the event
                # write in __aexit__ would then raise something that reads like
                # the cause. Leave the session clean before propagating.
                await db.rollback()
                raise
        await db.commit()
        return positions, synced, unavailable

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
        factor_tickers = [
            cfg["ticker"]
            for cfg in (self._factor_config or {}).get("factors", {}).values()
            if "ticker" in cfg
        ]
        factor_prices_df = await market_data_service.get_factor_prices_df(
            db, factor_tickers, start_date, as_of_date
        )

        # Load DB risk limits for the portfolio
        limits = await portfolio_service.get_risk_limits(db, portfolio_id)
        db_limits = [
            {
                "limit_type": lim.limit_type,
                "entity_type": lim.entity_type,
                "entity_id": lim.entity_id,
                "warning_level": float(lim.warning_level),
                "breach_level": float(lim.breach_level),
            }
            for lim in limits
        ]

        return positions_df, prices_df, factor_prices_df, db_limits

    # ── Validation ─────────────────────────────────────────────────────────────

    def _validate_inputs(
        self,
        positions_df: pd.DataFrame,
        prices_df: pd.DataFrame,
        as_of_date: date,
    ) -> None:
        """The single place a run decides its prices are good enough.

        Everything downstream may now assume every holding has a usable, recent
        price — which is what lets calc_exposure and calc_pnl drop their
        fallbacks. Before this existed, an unpriced holding was valued at $0 but
        left in the denominator, so the run went green while every OTHER name's
        weight was inflated: a two-name book with one bad ticker reported the
        survivor at 100% instead of 71%, which is enough to fabricate a
        concentration breach out of nothing.

        Both problems are reported as complete lists. Naming only the first
        turns one fix-and-rerun cycle into as many as there are bad tickers.
        """
        if positions_df.empty:
            raise ValueError("No positions found for the given portfolio and date")
        if prices_df.empty:
            raise ValueError("No market prices found — ensure seed data is loaded")

        held = set(positions_df["ticker"].astype(str))
        as_of_ts = pd.Timestamp(as_of_date)
        usable = prices_df[prices_df["price_date"] <= as_of_ts]
        newest = usable.groupby("ticker")["price_date"].max()

        missing = sorted(held - set(newest.index.astype(str)))
        max_age = get_settings().price_staleness_days
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
        if problems:
            raise ValueError(
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

        # RiskAlert rows
        for alert in alerts:
            db.add(RiskAlert(
                id=new_alert_id(),   # alert_<hex> — must match the evidence prefix (alert_)
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
    ) -> str | None:
        try:
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

            report_id = new_id("report")
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
            return report_id

        except Exception as e:
            logger.warning("Report generation failed: %s", e)
            return None


# ── Step context manager ───────────────────────────────────────────────────────

class _StepContext:
    """Logs workflow_event start and completion around a step."""

    def __init__(self, db: AsyncSession, run_id: str, step_name: str, message: str):
        self.db = db
        self.run_id = run_id
        self.step_name = step_name
        self.message = message
        self._start_ms = 0

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
        if exc_type is None:
            status = "completed"
            msg = self.message
        else:
            status = "failed"
            msg = f"{self.message} — ERROR: {exc_val}"
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

        await workflow_event_service.log_event(
            db=self.db,
            run_id=self.run_id,
            step_name=self.step_name,
            status=status,
            message=msg,
            duration_ms=duration_ms,
        )
        await self.db.commit()
        return False  # don't suppress exceptions
