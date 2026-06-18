-- Exposure Workbench — PostgreSQL Schema
-- Auto-executed on first postgres container start.

-- ─── Extensions ──────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── Portfolios ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolios (
    id              VARCHAR(64) PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    currency        VARCHAR(8) NOT NULL DEFAULT 'USD',
    base_nav        NUMERIC(18, 2),
    benchmark       VARCHAR(32),
    manager         VARCHAR(128),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Positions ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS positions (
    id              VARCHAR(64) PRIMARY KEY,
    portfolio_id    VARCHAR(64) NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    as_of_date      DATE NOT NULL,
    ticker          VARCHAR(16) NOT NULL,
    asset_class     VARCHAR(32) NOT NULL DEFAULT 'equity',
    sector          VARCHAR(64),
    region          VARCHAR(32) DEFAULT 'US',
    currency        VARCHAR(8) NOT NULL DEFAULT 'USD',
    quantity        NUMERIC(18, 4) NOT NULL,
    cost_basis      NUMERIC(18, 4),
    price           NUMERIC(18, 4),
    market_value    NUMERIC(18, 2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (portfolio_id, as_of_date, ticker)
);

-- ─── Market Prices ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_prices (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(16) NOT NULL,
    price_date      DATE NOT NULL,
    open            NUMERIC(18, 4),
    high            NUMERIC(18, 4),
    low             NUMERIC(18, 4),
    close           NUMERIC(18, 4) NOT NULL,
    adj_close       NUMERIC(18, 4),
    volume          BIGINT,
    source          VARCHAR(32) DEFAULT 'seed',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, price_date)
);

-- ─── Factor Prices ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS factor_prices (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(16) NOT NULL,
    price_date      DATE NOT NULL,
    close           NUMERIC(18, 4) NOT NULL,
    daily_return    NUMERIC(12, 8),
    source          VARCHAR(32) DEFAULT 'seed',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, price_date)
);

-- ─── Risk Limits ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_limits (
    id              VARCHAR(64) PRIMARY KEY,
    portfolio_id    VARCHAR(64) NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    limit_type      VARCHAR(64) NOT NULL,
    entity_type     VARCHAR(32),     -- 'portfolio' | 'sector' | 'issuer'
    entity_id       VARCHAR(64),     -- ticker or sector name (NULL = applies to all)
    warning_level   NUMERIC(12, 6) NOT NULL,
    breach_level    NUMERIC(12, 6) NOT NULL,
    unit            VARCHAR(16) DEFAULT 'fraction',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (portfolio_id, limit_type, entity_id)
);

-- ─── Exposure Runs ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS exposure_runs (
    id              VARCHAR(64) PRIMARY KEY,
    portfolio_id    VARCHAR(64) NOT NULL REFERENCES portfolios(id),
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed
    as_of_date      DATE NOT NULL,
    task_id         VARCHAR(64),
    triggered_by    VARCHAR(32) DEFAULT 'manual',  -- manual|scheduled|api
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exposure_runs_portfolio ON exposure_runs(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_exposure_runs_status ON exposure_runs(status);
CREATE INDEX IF NOT EXISTS idx_exposure_runs_as_of_date ON exposure_runs(as_of_date);

-- ─── Exposure Metrics ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS exposure_metrics (
    id                      SERIAL PRIMARY KEY,
    run_id                  VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    portfolio_market_value  NUMERIC(18, 2),
    daily_pnl               NUMERIC(18, 2),
    daily_return            NUMERIC(12, 8),
    gross_exposure          NUMERIC(18, 2),
    net_exposure            NUMERIC(18, 2),
    gross_exposure_pct      NUMERIC(12, 6),
    net_exposure_pct        NUMERIC(12, 6),
    rolling_vol_30d         NUMERIC(12, 8),
    rolling_vol_60d         NUMERIC(12, 8),
    var_95_1d               NUMERIC(12, 8),
    expected_shortfall_95   NUMERIC(12, 8),
    max_drawdown            NUMERIC(12, 8),
    stress_loss_tech        NUMERIC(12, 8),
    stress_loss_rates       NUMERIC(12, 8),
    stress_loss_credit      NUMERIC(12, 8),
    stress_loss_market      NUMERIC(12, 8),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id)
);

-- ─── Sector Exposures ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sector_exposures (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    sector          VARCHAR(64) NOT NULL,
    market_value    NUMERIC(18, 2),
    weight          NUMERIC(12, 8),
    weight_change   NUMERIC(12, 8),  -- vs previous run
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, sector)
);

-- ─── Issuer Exposures ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS issuer_exposures (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    ticker          VARCHAR(16) NOT NULL,
    sector          VARCHAR(64),
    market_value    NUMERIC(18, 2),
    weight          NUMERIC(12, 8),
    weight_change   NUMERIC(12, 8),  -- vs previous run
    daily_pnl       NUMERIC(18, 2),
    daily_return    NUMERIC(12, 8),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, ticker)
);

-- ─── Factor Attributions ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS factor_attributions (
    id                  SERIAL PRIMARY KEY,
    run_id              VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    factor_name         VARCHAR(64) NOT NULL,
    factor_ticker       VARCHAR(16),
    beta                NUMERIC(12, 8),
    factor_return       NUMERIC(12, 8),
    contribution        NUMERIC(12, 8),  -- beta × factor_return
    r_squared           NUMERIC(12, 8),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, factor_name)
);

CREATE TABLE IF NOT EXISTS factor_residuals (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    explained_return NUMERIC(12, 8),
    residual_return  NUMERIC(12, 8),
    r_squared       NUMERIC(12, 8),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id)
);

-- ─── Risk Alerts ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_alerts (
    id              VARCHAR(64) PRIMARY KEY,
    run_id          VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    alert_type      VARCHAR(64) NOT NULL,
    severity        VARCHAR(16) NOT NULL DEFAULT 'warning',  -- warning|breach|info
    entity_type     VARCHAR(32),   -- 'portfolio' | 'sector' | 'issuer'
    entity_id       VARCHAR(64),
    current_value   NUMERIC(12, 8),
    limit_value     NUMERIC(12, 8),
    utilization     NUMERIC(12, 8),
    message         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_alerts_run ON risk_alerts(run_id);
CREATE INDEX IF NOT EXISTS idx_risk_alerts_severity ON risk_alerts(severity);

-- ─── Daily Reports ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_reports (
    id                      VARCHAR(64) PRIMARY KEY,
    run_id                  VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    portfolio_id            VARCHAR(64) NOT NULL,
    as_of_date              DATE NOT NULL,
    agent_mode              VARCHAR(32) DEFAULT 'direct_llm',
    executive_summary       TEXT,
    key_movements           TEXT,
    factor_explanation      TEXT,
    risk_alert_explanation  TEXT,
    recommended_actions     TEXT,
    markdown_report         TEXT,
    confidence_flags        JSONB DEFAULT '{}',
    llm_model               VARCHAR(64),
    prompt_tokens           INTEGER,
    completion_tokens       INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id)
);

-- ─── Tasks ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id              VARCHAR(64) PRIMARY KEY,
    type            VARCHAR(64) NOT NULL,  -- exposure_update|market_data_sync|scheduled_update
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed
    payload         JSONB DEFAULT '{}',
    worker_id       VARCHAR(64),
    claimed_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type);

-- ─── Schedules ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schedules (
    id              VARCHAR(64) PRIMARY KEY,
    portfolio_id    VARCHAR(64) NOT NULL REFERENCES portfolios(id),
    name            VARCHAR(128),
    task_type       VARCHAR(64) NOT NULL DEFAULT 'exposure_update',
    cron_expression VARCHAR(64),     -- e.g. "0 8 * * 1-5"
    run_time        TIME,            -- e.g. 08:00 (if daily)
    timezone        VARCHAR(64) DEFAULT 'America/New_York',
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Workflow Events ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_events (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    step_name       VARCHAR(64) NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'running',  -- running|completed|failed|skipped
    message         TEXT,
    payload_summary JSONB DEFAULT '{}',
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_events_run ON workflow_events(run_id);
CREATE INDEX IF NOT EXISTS idx_workflow_events_step ON workflow_events(step_name);
