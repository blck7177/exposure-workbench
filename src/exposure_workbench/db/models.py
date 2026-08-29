"""SQLAlchemy ORM models — mirrors infra/init.sql schema."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey,
    Index, Integer, Numeric, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from exposure_workbench.db.session import Base


# ─── Users (V2-A: identity from Clerk; local row for ownership FKs) ────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)   # Clerk user id
    email: Mapped[str | None] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ─── Security master (V2-D: the investable US universe; shared, no RLS) ─────────

class SecurityMaster(Base):
    __tablename__ = "security_master"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)   # listing form (BRK.A)
    name: Mapped[str | None] = mapped_column(String(255))
    exchange: Mapped[str | None] = mapped_column(String(32))
    is_etf: Mapped[bool] = mapped_column(Boolean, default=False)
    cik: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")   # active | delisted
    source: Mapped[str | None] = mapped_column(String(32))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ─── Portfolios ───────────────────────────────────────────────────────────────

class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    base_nav: Mapped[float | None] = mapped_column(Numeric(18, 2))
    benchmark: Mapped[str | None] = mapped_column(String(32))
    manager: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # V2-A tenancy: owner_id nullable now, backfilled + NOT NULL in V2-C.
    owner_id: Mapped[str | None] = mapped_column(String(255))
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    positions: Mapped[list["Position"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")
    risk_limits: Mapped[list["RiskLimit"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")
    exposure_runs: Mapped[list["ExposureRun"]] = relationship(back_populates="portfolio")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="portfolio")


# ─── Positions ────────────────────────────────────────────────────────────────

class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "as_of_date", "ticker"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), ForeignKey("portfolios.id", ondelete="CASCADE"))
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(32), default="equity")
    sector: Mapped[str | None] = mapped_column(String(64))
    region: Mapped[str | None] = mapped_column(String(32), default="US")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    cost_basis: Mapped[float | None] = mapped_column(Numeric(18, 4))
    price: Mapped[float | None] = mapped_column(Numeric(18, 4))
    market_value: Mapped[float | None] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    portfolio: Mapped["Portfolio"] = relationship(back_populates="positions")


# ─── Market Prices ────────────────────────────────────────────────────────────

class MarketPrice(Base):
    __tablename__ = "market_prices"
    __table_args__ = (UniqueConstraint("ticker", "price_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float | None] = mapped_column(Numeric(18, 4))
    high: Mapped[float | None] = mapped_column(Numeric(18, 4))
    low: Mapped[float | None] = mapped_column(Numeric(18, 4))
    close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    adj_close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str | None] = mapped_column(String(32), default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Factor Prices ────────────────────────────────────────────────────────────

class FactorPrice(Base):
    __tablename__ = "factor_prices"
    __table_args__ = (UniqueConstraint("ticker", "price_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    adj_close: Mapped[float | None] = mapped_column(Numeric(18, 4))
    daily_return: Mapped[float | None] = mapped_column(Numeric(12, 8))
    source: Mapped[str | None] = mapped_column(String(32), default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Risk Limits ──────────────────────────────────────────────────────────────

class RiskLimit(Base):
    """The table that is becoming the single runtime source of every threshold.

    Not yet: analytics/limits.py still reads its thresholds from the cfg()
    closure it is handed and still ignores the db_limits it is passed. The
    constraints below land before that switch, not after it — they are what has
    to replace the git review a YAML edit used to get once a row here is the
    number in force.

    The four constraints below mirror infra/init.sql exactly — character for
    character in their predicate text, which tests/test_risk_limits_parity.py
    compares against init.sql, and init.sql in turn against the ADDs in
    infra/migrations/v2_multiuser.sql. They are declared here as well because this
    class is what a reader consults to learn what a valid row looks like, and a
    rule that lives only in the DDL is a rule the next person writing an INSERT
    never sees. See the init.sql block for why each one exists.
    """

    __tablename__ = "risk_limits"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "limit_type", "entity_id"),
        # NULLS DISTINCT on PG 16 lets the UNIQUE above admit two contradictory
        # portfolio-wide defaults for one check; this forbids the second.
        Index("ux_risk_limits_default", "portfolio_id", "limit_type", unique=True,
              postgresql_where=text("entity_id IS NULL")),
        # Strict `>`: breach == warning kills the warning tier just as surely as
        # breach < warning does, because _check_one tests breach first. Excludes
        # the two mechanical own-goals only — it cannot tell whether a number is
        # sensible for its check, and nothing else does either.
        CheckConstraint("warning_level > 0 AND breach_level > warning_level",
                        name="ck_risk_limits_levels"),
        # `unit` is nullable and a CHECK whose predicate is NULL passes, so the
        # IS NOT NULL half is what stops an explicit unit=NULL row.
        CheckConstraint("unit IS NOT NULL AND unit = 'fraction'",
                        name="ck_risk_limits_unit"),
        CheckConstraint("is_active OR entity_id IS NOT NULL",
                        name="ck_risk_limits_default_active"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), ForeignKey("portfolios.id", ondelete="CASCADE"))
    limit_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    warning_level: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    breach_level: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(16), default="fraction")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    portfolio: Mapped["Portfolio"] = relationship(back_populates="risk_limits")


# ─── Exposure Runs ────────────────────────────────────────────────────────────

class ExposureRun(Base):
    __tablename__ = "exposure_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), ForeignKey("portfolios.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64))
    triggered_by: Mapped[str | None] = mapped_column(String(32), default="manual")
    # V13-S2, same three-part shape as ResearchRun: the sentence, the kind, and
    # the exception's own words. An exposure run's error_message is often
    # already the reader's sentence — "Cannot value this portfolio as of … —
    # newest price older than 10 days for: AAPL (30d old)" is written for them —
    # and RunRefused is how that case is told apart from a provider's JSON.
    error_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    portfolio: Mapped["Portfolio"] = relationship(back_populates="exposure_runs")
    metrics: Mapped["ExposureMetrics | None"] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    sector_exposures: Mapped[list["SectorExposure"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    issuer_exposures: Mapped[list["IssuerExposure"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    factor_attributions: Mapped[list["FactorAttribution"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    risk_alerts: Mapped[list["RiskAlert"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    daily_report: Mapped["DailyReport | None"] = relationship(back_populates="run", uselist=False, cascade="all, delete-orphan")
    workflow_events: Mapped[list["WorkflowEvent"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="WorkflowEvent.created_at")


# ─── Exposure Metrics ─────────────────────────────────────────────────────────

class ExposureMetrics(Base):
    __tablename__ = "exposure_metrics"
    __table_args__ = (UniqueConstraint("run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    portfolio_market_value: Mapped[float | None] = mapped_column(Numeric(18, 2))
    daily_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    daily_return: Mapped[float | None] = mapped_column(Numeric(12, 8))
    gross_exposure: Mapped[float | None] = mapped_column(Numeric(18, 2))
    net_exposure: Mapped[float | None] = mapped_column(Numeric(18, 2))
    gross_exposure_pct: Mapped[float | None] = mapped_column(Numeric(12, 6))
    net_exposure_pct: Mapped[float | None] = mapped_column(Numeric(12, 6))
    rolling_vol_30d: Mapped[float | None] = mapped_column(Numeric(12, 8))
    rolling_vol_60d: Mapped[float | None] = mapped_column(Numeric(12, 8))
    var_95_1d: Mapped[float | None] = mapped_column(Numeric(12, 8))
    expected_shortfall_95: Mapped[float | None] = mapped_column(Numeric(12, 8))
    max_drawdown: Mapped[float | None] = mapped_column(Numeric(12, 8))
    stress_loss_tech: Mapped[float | None] = mapped_column(Numeric(12, 8))
    stress_loss_rates: Mapped[float | None] = mapped_column(Numeric(12, 8))
    stress_loss_credit: Mapped[float | None] = mapped_column(Numeric(12, 8))
    stress_loss_market: Mapped[float | None] = mapped_column(Numeric(12, 8))
    # V8-P1: what the regression behind the betas actually was. Computed by
    # factor_model on every run and, until now, written only to
    # workflow_events.payload — which the evidence resolver does not read, so
    # the numbers that say how much of the day the factors explain could not be
    # stated by the agent at all. `residual` was worse: computed and persisted
    # nowhere, so "how much of this move do you not explain" survived one
    # function call. Columns here rather than a new table because this row is
    # already the run's one-per-run scalar record (UNIQUE(run_id)).
    # NOT daily_return: this one revalues the book at total-return prices, which
    # is what the betas were fitted against. `residual` closes against it, and
    # the gap to daily_return is a valuation convention with a name rather than
    # an unexplained remainder.
    attribution_portfolio_return: Mapped[float | None] = mapped_column(Numeric(12, 8))
    alpha: Mapped[float | None] = mapped_column(Numeric(12, 8))
    residual: Mapped[float | None] = mapped_column(Numeric(12, 8))
    model_r_squared: Mapped[float | None] = mapped_column(Numeric(12, 8))
    observations: Mapped[int | None] = mapped_column(Integer)
    regression_window_days: Mapped[int | None] = mapped_column(Integer)
    max_vif: Mapped[float | None] = mapped_column(Numeric(12, 6))
    # The caveat that belongs beside every individual beta on the page: SPY/QQQ/
    # IWM are ~0.9 correlated, so the fit is well determined as a whole and each
    # coefficient is not.
    collinear: Mapped[bool | None] = mapped_column(Boolean)
    attribution_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["ExposureRun"] = relationship(back_populates="metrics")


# ─── Sector Exposures ─────────────────────────────────────────────────────────

class SectorExposure(Base):
    __tablename__ = "sector_exposures"
    __table_args__ = (UniqueConstraint("run_id", "sector"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    sector: Mapped[str] = mapped_column(String(64), nullable=False)
    market_value: Mapped[float | None] = mapped_column(Numeric(18, 2))
    weight: Mapped[float | None] = mapped_column(Numeric(12, 8))
    weight_change: Mapped[float | None] = mapped_column(Numeric(12, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["ExposureRun"] = relationship(back_populates="sector_exposures")


# ─── Issuer Exposures ─────────────────────────────────────────────────────────

# ─── Stress results / limit checks (V8-P2, V8-P3) ─────────────────────────────

class StressResult(Base):
    """One scenario, evaluated or refused, as a row.

    `calc_stress` already produced everything here; all of it went into
    workflow_events.payload_summary, which the evidence resolver does not read
    and which has no id prefix — so the two most load-bearing facts a stress
    number carries could not be cited:

      * `factors_held_flat` — factors the model HAS a beta for and this scenario
        says nothing about. Zero is an assertion ("credit does not move in an
        equity crash"), not an absence of one. On the live book market_downside
        holds HYG flat while HYG carries the second-largest beta the book has.
      * the refusals — a scenario is evaluated only when EVERY factor it shocks
        has a beta, because dropping the unknown legs understates the loss, and
        understating a stress loss is the one direction that matters.

    The CHECK is what stops that refusal being undone at the last step: an
    unevaluated scenario stored with loss 0.0 reads as "this book is safe in a
    rates shock", which is exactly the sentence calc_stress refuses to produce.
    """

    __tablename__ = "stress_results"
    __table_args__ = (
        UniqueConstraint("run_id", "scenario"),
        CheckConstraint("status IN ('evaluated', 'unevaluated')", name="ck_stress_status"),
        CheckConstraint(
            "(status = 'evaluated' AND loss_pct IS NOT NULL AND reason IS NULL) OR "
            "(status = 'unevaluated' AND loss_pct IS NULL AND loss_usd IS NULL "
            " AND reason IS NOT NULL)",
            name="ck_stress_unevaluated_has_no_loss",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    scenario: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # The shocks that were APPLIED, carried from the computation rather than
    # re-read from config at write time — V8-P1's lesson about the regression
    # window, in its second instance.
    shocks: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    loss_pct: Mapped[float | None] = mapped_column(Numeric(12, 8))
    loss_usd: Mapped[float | None] = mapped_column(Numeric(18, 2))
    factors_held_flat: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LimitCheck(Base):
    """One limit that RAN, and whether it fired.

    `check_limits` has always returned `(alerts, evaluated)`. The alerts became
    rows; the evaluated list became nothing. So "three limits breached" was
    supportable and "and the other five were checked and clear" was not — the
    reassuring half of the answer was the unciteable half, which is the wrong
    half to lose.
    """

    __tablename__ = "limit_checks"
    __table_args__ = (UniqueConstraint("run_id", "limit_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    limit_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Not nullable: a check either fired or it did not, and a third state would
    # be the ambiguity this table exists to remove.
    fired: Mapped[bool] = mapped_column(Boolean, nullable=False)
    alert_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IssuerExposure(Base):
    __tablename__ = "issuer_exposures"
    __table_args__ = (UniqueConstraint("run_id", "ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(64))
    market_value: Mapped[float | None] = mapped_column(Numeric(18, 2))
    weight: Mapped[float | None] = mapped_column(Numeric(12, 8))
    weight_change: Mapped[float | None] = mapped_column(Numeric(12, 8))
    daily_pnl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    daily_return: Mapped[float | None] = mapped_column(Numeric(12, 8))
    # Share of the BOOK's return this position accounts for: yesterday's weight
    # times the position's return. calc_pnl has always computed it and this row
    # has never held it, so the one figure a "top contributors" sentence is made
    # of was the one figure nothing could check it against.
    contribution: Mapped[float | None] = mapped_column(Numeric(12, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["ExposureRun"] = relationship(back_populates="issuer_exposures")


# ─── Factor Attributions ──────────────────────────────────────────────────────

class FactorAttribution(Base):
    __tablename__ = "factor_attributions"
    __table_args__ = (UniqueConstraint("run_id", "factor_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    factor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    factor_ticker: Mapped[str | None] = mapped_column(String(16))
    beta: Mapped[float | None] = mapped_column(Numeric(12, 8))
    factor_return: Mapped[float | None] = mapped_column(Numeric(12, 8))
    contribution: Mapped[float | None] = mapped_column(Numeric(12, 8))
    r_squared: Mapped[float | None] = mapped_column(Numeric(12, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["ExposureRun"] = relationship(back_populates="factor_attributions")


# ─── Risk Alerts ──────────────────────────────────────────────────────────────

class RiskAlert(Base):
    __tablename__ = "risk_alerts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    current_value: Mapped[float | None] = mapped_column(Numeric(12, 8))
    limit_value: Mapped[float | None] = mapped_column(Numeric(12, 8))
    utilization: Mapped[float | None] = mapped_column(Numeric(12, 8))
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["ExposureRun"] = relationship(back_populates="risk_alerts")


# ─── Daily Reports ────────────────────────────────────────────────────────────

class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("run_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    portfolio_id: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    agent_mode: Mapped[str | None] = mapped_column(String(32), default="direct_llm")
    executive_summary: Mapped[str | None] = mapped_column(Text)
    key_movements: Mapped[str | None] = mapped_column(Text)
    factor_explanation: Mapped[str | None] = mapped_column(Text)
    risk_alert_explanation: Mapped[str | None] = mapped_column(Text)
    recommended_actions: Mapped[str | None] = mapped_column(Text)
    markdown_report: Mapped[str | None] = mapped_column(Text)
    confidence_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    llm_model: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["ExposureRun"] = relationship(back_populates="daily_report")


# ─── Tasks ────────────────────────────────────────────────────────────────────

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # V2-E1: set from SERVER time on claim; the reaper treats a past value as
    # "the worker holding this died". Cleared on requeue, complete and fail.
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    owner_user_id: Mapped[str | None] = mapped_column(String(255))   # V2-A: whose request enqueued it (worker sets tenant from this)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Daily usage counters (V2-E3) ─────────────────────────────────────────────

class UsageDaily(Base):
    """One row per (user, UTC day, action kind). Shared layer, NO RLS — see the
    note in infra/init.sql: the global backstop is the reserved row
    user_id='_global', and a tenant policy would silently make it count only the
    caller. Written exclusively through usage_service.charge's conditional
    upsert, never by ORM attribute assignment.

    `kind` is an unconstrained VARCHAR in all three schema files — no CHECK, no
    enum — so adding a pool is a change to usage_service.POOLS plus two settings
    and never a migration. The current set: chat_turn, research_run, readiness,
    exposure_run, market_sync, and (V2-H) portfolio_create, position_upload,
    agent_session."""

    __tablename__ = "usage_daily"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)


# ─── Schedules ────────────────────────────────────────────────────────────────

class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(64), ForeignKey("portfolios.id"))
    name: Mapped[str | None] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(64), default="exposure_update")
    cron_expression: Mapped[str | None] = mapped_column(String(64))
    timezone: Mapped[str | None] = mapped_column(String(64), default="America/New_York")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    portfolio: Mapped["Portfolio"] = relationship(back_populates="schedules")


# ─── Workflow Events ──────────────────────────────────────────────────────────

class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("exposure_runs.id", ondelete="CASCADE"))
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="running")
    message: Mapped[str | None] = mapped_column(Text)
    payload_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped["ExposureRun"] = relationship(back_populates="workflow_events")


# ═══════════════════════════════════════════════════════════════════════════════
# ISSUER INTELLIGENCE MODELS (mirrors infra/init.sql, v3)
#
# New models intentionally carry NO relationship() navigations — services query
# with explicit select()/where (matching market_data_service / portfolio_service),
# which keeps import-time mapper configuration risk at zero. FK columns still
# mirror the DB constraints. Evidence four-stores are append-only by discipline.
# ═══════════════════════════════════════════════════════════════════════════════


# ─── Raw: Companies ─────────────────────────────────────────────────────────────

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cik: Mapped[str | None] = mapped_column(String(16))
    exchange: Mapped[str | None] = mapped_column(String(32))
    sector: Mapped[str | None] = mapped_column(String(64))       # EDGAR/SIC view
    industry: Mapped[str | None] = mapped_column(String(128))
    is_investigable: Mapped[bool] = mapped_column(Boolean, default=True)
    resolved_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Raw: Filings ───────────────────────────────────────────────────────────────

class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(64), ForeignKey("companies.id", ondelete="CASCADE"))
    accession_number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    form_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[date | None] = mapped_column(Date)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text)
    is_amendment: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Raw: Filing Documents ──────────────────────────────────────────────────────

class FilingDocument(Base):
    __tablename__ = "filing_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filing_id: Mapped[str] = mapped_column(String(64), ForeignKey("filings.id", ondelete="CASCADE"))
    doc_type: Mapped[str | None] = mapped_column(String(32))
    raw_text: Mapped[str | None] = mapped_column(Text)
    char_count: Mapped[int | None] = mapped_column(Integer)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Normalized: Filing Sections ────────────────────────────────────────────────

class FilingSection(Base):
    __tablename__ = "filing_sections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filing_id: Mapped[str] = mapped_column(String(64), ForeignKey("filings.id", ondelete="CASCADE"))
    item_code: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(255))
    section_order: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)


# ─── Normalized: Filing Chunks (APPEND-ONLY) ────────────────────────────────────

class FilingChunk(Base):
    __tablename__ = "filing_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    section_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("filing_sections.id", ondelete="CASCADE"))
    filing_id: Mapped[str] = mapped_column(String(64), ForeignKey("filings.id", ondelete="CASCADE"))
    company_id: Mapped[str] = mapped_column(String(64), ForeignKey("companies.id", ondelete="CASCADE"))
    chunk_order: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    form_type: Mapped[str | None] = mapped_column(String(16))
    filing_date: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)


# ─── Normalized: Financial Facts (APPEND-ONLY) ──────────────────────────────────

class FinancialFact(Base):
    __tablename__ = "financial_facts"
    # source_accession is in the key on purpose — restatements must append a new
    # row rather than overwrite the original (see infra/init.sql for rationale).
    __table_args__ = (
        UniqueConstraint("company_id", "raw_concept", "period_end", "dimensions_hash", "source_accession"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filing_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("filings.id", ondelete="CASCADE"))
    company_id: Mapped[str] = mapped_column(String(64), ForeignKey("companies.id", ondelete="CASCADE"))
    raw_concept: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_metric: Mapped[str | None] = mapped_column(String(64))
    statement_type: Mapped[str | None] = mapped_column(String(32))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer)
    value: Mapped[float | None] = mapped_column(Numeric(24, 4))
    unit: Mapped[str | None] = mapped_column(String(16))
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dimensions_hash: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    mapping_version: Mapped[str | None] = mapped_column(String(16))
    source_accession: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Normalized: Research Sources (APPEND-ONLY) ─────────────────────────────────

class ResearchSource(Base):
    __tablename__ = "research_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    research_run_id: Mapped[str | None] = mapped_column(String(64))
    company_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("companies.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    publisher_domain: Mapped[str | None] = mapped_column(String(128))
    published_date: Mapped[date | None] = mapped_column(Date)
    search_query: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[float | None] = mapped_column(Numeric(6, 4))
    snippet: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Calc Ledger (APPEND-ONLY) ──────────────────────────────────────────────────

class CalcLedger(Base):
    __tablename__ = "calc_ledger"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str | None] = mapped_column(String(64))   # plain column (SPY etc. not in companies)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    input_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    primitive_version: Mapped[str] = mapped_column(String(16), nullable=False)
    invoked_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Runtime: Research Runs ─────────────────────────────────────────────────────

class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(64), ForeignKey("companies.id"))
    portfolio_id: Mapped[str | None] = mapped_column(String(64))
    owner_id: Mapped[str | None] = mapped_column(String(255))   # V2-A tenancy
    status: Mapped[str] = mapped_column(String(32), default="pending")
    task_id: Mapped[str | None] = mapped_column(String(64))
    agent_session_id: Mapped[str | None] = mapped_column(String(64))
    triggered_by: Mapped[str | None] = mapped_column(String(64), default="manual")
    # V13-S2. Three columns for one failure, because a failure has three parts.
    # error_message is the sentence a person is shown; error_code is which kind
    # of failure it was, from the closed set in exposure_workbench.errors, and is
    # what the UI keys its wording on; error_detail is the exception's own words
    # — a provider's JSON, an internal hostname — kept for the operator and read
    # only in the audit layer. NULL code on every row written before V13.
    error_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Runtime: Agent Sessions ────────────────────────────────────────────────────

class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), default="meta")   # 'meta' | 'research'
    owner_id: Mapped[str | None] = mapped_column(String(255))   # V2-A tenancy
    llm_model: Mapped[str | None] = mapped_column(String(64))
    tool_budget: Mapped[int | None] = mapped_column(Integer)
    tools_used: Mapped[int] = mapped_column(Integer, default=0)
    external_searches: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # V2-E2: one in-flight turn per session. Claimed by a conditional UPDATE
    # using SERVER time (never an ORM attribute set — that would be client time),
    # released in a finally. A stale value simply expires; nothing renews it.
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # V3-B0: observation only — last turn's prompt size, tool schemas included.
    last_prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    # V3-B2: per-turn tool budget, carried BY THE ROW. reserve() reads which
    # regime applies off the row instead of branching on kind, so the research
    # carve-out is data rather than a special case. NULL = lifetime budget only,
    # which is what research needs: it spends 25-32 calls inside one session and
    # never claims a turn, so nothing would ever zero a per-turn counter for it.
    turn_tools_used: Mapped[int] = mapped_column(Integer, default=0)
    turn_tool_budget: Mapped[int | None] = mapped_column(Integer)


# ─── Runtime: Agent Messages ────────────────────────────────────────────────────

class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # V3: out-of-band facts about the turn — the gate outcome (A0-2) and the
    # prompt size (B0). Deliberately not encoded in `role`, which _load_history
    # feeds verbatim into the provider's messages array.
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Runtime: Agent Steps (APPEND-ONLY audit trail) ─────────────────────────────

class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_sessions.id", ondelete="CASCADE"))
    message_id: Mapped[str | None] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(16), nullable=False)   # tool_call|think|delegation|respond|llm_call
    tool_name: Mapped[str | None] = mapped_column(String(64))
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result_summary: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16), default="completed")   # completed|rejected|error
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Artifact: Evidence Packs ───────────────────────────────────────────────────

class EvidencePack(Base):
    __tablename__ = "evidence_packs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    research_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64))
    pack: Mapped[list[Any]] = mapped_column(JSONB, default=list)   # refs list, not full snapshot
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Artifact: Issuer Briefs ────────────────────────────────────────────────────

class IssuerBrief(Base):
    __tablename__ = "issuer_briefs"
    __table_args__ = (UniqueConstraint("research_run_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    research_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    company_id: Mapped[str] = mapped_column(String(64), ForeignKey("companies.id", ondelete="CASCADE"))
    owner_id: Mapped[str | None] = mapped_column(String(255))   # V2-A tenancy
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    financial_summary: Mapped[str | None] = mapped_column(Text)
    key_changes: Mapped[str | None] = mapped_column(Text)
    management_explanation: Mapped[str | None] = mapped_column(Text)
    market_context: Mapped[str | None] = mapped_column(Text)
    portfolio_implications: Mapped[str | None] = mapped_column(Text)
    open_questions: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # V3-C1: {block_name: [ids]}. `citations` above is flattened with
    # sorted(set(...)) at submit time, so the block association only survives if
    # it is written separately. NULL on briefs written before V3.
    block_citations: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confidence_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # No llm_model/prompt_tokens/completion_tokens (V4-S2, dropped in
    # infra/migrations/v4_cost.sql). They were a fossil of the v2 shape where one
    # artifact was one completion — still true of daily_reports, which fills its
    # copies, and never true of a brief: a brief is what a 30-turn session ends
    # with. Nothing ever wrote them. The session's llm_call rows are the real
    # number, and llm_cost_by_research_run is where to ask for it.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
