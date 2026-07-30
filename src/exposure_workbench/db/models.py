"""SQLAlchemy ORM models — mirrors infra/init.sql schema."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint,
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
    daily_return: Mapped[float | None] = mapped_column(Numeric(12, 8))
    source: Mapped[str | None] = mapped_column(String(32), default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Risk Limits ──────────────────────────────────────────────────────────────

class RiskLimit(Base):
    __tablename__ = "risk_limits"
    __table_args__ = (UniqueConstraint("portfolio_id", "limit_type", "entity_id"),)

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
    error_message: Mapped[str | None] = mapped_column(Text)
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
    error_message: Mapped[str | None] = mapped_column(Text)
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


# ─── Runtime: Agent Messages ────────────────────────────────────────────────────

class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Runtime: Agent Steps (APPEND-ONLY audit trail) ─────────────────────────────

class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_sessions.id", ondelete="CASCADE"))
    message_id: Mapped[str | None] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(16), nullable=False)   # tool_call|think|delegation|respond
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
    confidence_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    llm_model: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
