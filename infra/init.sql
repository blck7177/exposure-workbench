-- Exposure Workbench — PostgreSQL Schema
-- Auto-executed on first postgres container start.

-- ─── Extensions ──────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector: filing_chunks.embedding (Issuer Intelligence)

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
    -- NO FK on run_id: shared by exposure_runs AND research_runs (Issuer Intelligence).
    -- run_id is a free string; the owning run table is inferred by the reader.
    run_id          VARCHAR(64) NOT NULL,
    step_name       VARCHAR(64) NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'running',  -- running|completed|failed|skipped
    message         TEXT,
    payload_summary JSONB DEFAULT '{}',
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_events_run ON workflow_events(run_id);
CREATE INDEX IF NOT EXISTS idx_workflow_events_step ON workflow_events(step_name);


-- ═════════════════════════════════════════════════════════════════════════════
-- ISSUER INTELLIGENCE (Portfolio Exposure Analytics + Issuer Intelligence, v3)
-- Layers: Raw / Normalized evidence / Calc ledger / Runtime / Artifact.
-- Evidence four-stores (financial_facts, filing_chunks, calc_ledger,
-- research_sources) are APPEND-ONLY by discipline (no UPDATE/DELETE in code).
-- ═════════════════════════════════════════════════════════════════════════════

-- ─── Raw: Companies ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id               VARCHAR(64) PRIMARY KEY,
    ticker           VARCHAR(16) NOT NULL UNIQUE,
    name             VARCHAR(255) NOT NULL,
    cik              VARCHAR(16),
    exchange         VARCHAR(32),
    sector           VARCHAR(64),      -- EDGAR/SIC view (NOT merged with positions.sector)
    industry         VARCHAR(128),
    is_investigable  BOOLEAN NOT NULL DEFAULT TRUE,   -- ETFs (TLT/HYG) = FALSE
    resolved_by      VARCHAR(32),      -- 'seed' | 'edgartools'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Raw: Filings ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filings (
    id                VARCHAR(64) PRIMARY KEY,
    company_id        VARCHAR(64) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    accession_number  VARCHAR(32) NOT NULL UNIQUE,     -- idempotency key
    form_type         VARCHAR(16) NOT NULL,            -- '10-K' | '10-Q'
    filing_date       DATE NOT NULL,
    accepted_at       TIMESTAMPTZ,
    period_end        DATE,
    fiscal_year       INTEGER,
    fiscal_quarter    INTEGER,
    source_url        TEXT,
    is_amendment      BOOLEAN NOT NULL DEFAULT FALSE,
    provider          VARCHAR(32) NOT NULL,            -- 'edgartools'
    retrieved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_filings_company ON filings(company_id);

-- ─── Raw: Filing Documents ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filing_documents (
    id            VARCHAR(64) PRIMARY KEY,
    filing_id     VARCHAR(64) NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    doc_type      VARCHAR(32),
    raw_text      TEXT,
    char_count    INTEGER,
    retrieved_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_filing_documents_filing ON filing_documents(filing_id);

-- ─── Normalized: Filing Sections ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filing_sections (
    id            VARCHAR(64) PRIMARY KEY,
    filing_id     VARCHAR(64) NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    item_code     VARCHAR(16),        -- 'Item 1A' / 'Item 7' ...
    title         VARCHAR(255),
    section_order INTEGER,
    text          TEXT
);
CREATE INDEX IF NOT EXISTS idx_filing_sections_filing ON filing_sections(filing_id);

-- ─── Normalized: Filing Chunks (APPEND-ONLY) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS filing_chunks (
    id               VARCHAR(64) PRIMARY KEY,
    section_id       VARCHAR(64) REFERENCES filing_sections(id) ON DELETE CASCADE,
    filing_id        VARCHAR(64) NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    company_id       VARCHAR(64) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    chunk_order      INTEGER,
    text             TEXT NOT NULL,
    char_start       INTEGER,
    char_end         INTEGER,
    embedding        vector(1536),
    embedding_model  VARCHAR(64),
    -- retrieval filter columns (denormalized to avoid joins at query time):
    form_type        VARCHAR(16),
    filing_date      DATE,
    period_end       DATE
);
CREATE INDEX IF NOT EXISTS idx_filing_chunks_company ON filing_chunks(company_id);
CREATE INDEX IF NOT EXISTS idx_filing_chunks_filing ON filing_chunks(filing_id);
-- Vector index deferred: 8 companies × 2 filings — exact search is ample for MVP.
-- Add HNSW past the data-volume threshold (see TARGET_ARCHITECTURE §12).

-- ─── Normalized: Financial Facts (APPEND-ONLY) ───────────────────────────────
CREATE TABLE IF NOT EXISTS financial_facts (
    id                 VARCHAR(64) PRIMARY KEY,
    filing_id          VARCHAR(64) REFERENCES filings(id) ON DELETE CASCADE,
    company_id         VARCHAR(64) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    raw_concept        VARCHAR(255) NOT NULL,   -- original XBRL tag (traceability)
    normalized_metric  VARCHAR(64),             -- NULL when unmapped (still persisted)
    statement_type     VARCHAR(32),             -- 'income' | 'balance' | 'cashflow'
    period_start       DATE,
    period_end         DATE,
    fiscal_year        INTEGER,
    fiscal_quarter     INTEGER,
    value              NUMERIC(24, 4),
    unit               VARCHAR(16),
    dimensions         JSONB NOT NULL DEFAULT '{}',
    dimensions_hash    VARCHAR(64) NOT NULL DEFAULT '',
    provider           VARCHAR(32) NOT NULL,
    quality_flags      JSONB NOT NULL DEFAULT '{}',
    mapping_version    VARCHAR(16),
    -- Originating filing accession. Kept even when that filing is not itself
    -- ingested into `filings` (company-facts spans years of filings, while MVP
    -- only ingests the latest 10-K/10-Q) — so every fact stays traceable.
    source_accession   VARCHAR(32),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- source_accession is part of the key ON PURPOSE: the same (concept, period)
    -- restated in a later filing must land as a NEW row, not overwrite the
    -- original. Collapsing them would destroy restatement history (measured: 45%
    -- of NVDA facts) and leave M3's period_ladder nothing to pick "latest" from.
    UNIQUE (company_id, raw_concept, period_end, dimensions_hash, source_accession)
);
CREATE INDEX IF NOT EXISTS idx_financial_facts_company ON financial_facts(company_id);
CREATE INDEX IF NOT EXISTS idx_financial_facts_metric ON financial_facts(company_id, normalized_metric);

-- ─── Normalized: Research Sources (APPEND-ONLY) ──────────────────────────────
CREATE TABLE IF NOT EXISTS research_sources (
    id                VARCHAR(64) PRIMARY KEY,
    research_run_id   VARCHAR(64),
    company_id        VARCHAR(64) REFERENCES companies(id) ON DELETE CASCADE,
    title             TEXT,
    url               TEXT NOT NULL,
    publisher_domain  VARCHAR(128),
    published_date    DATE,
    search_query      TEXT,
    relevance_score   NUMERIC(6, 4),
    snippet           TEXT,
    provider          VARCHAR(32) NOT NULL,       -- 'tavily'
    retrieved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_research_sources_company ON research_sources(company_id);
CREATE INDEX IF NOT EXISTS idx_research_sources_run ON research_sources(research_run_id);

-- ─── Calc Ledger (APPEND-ONLY) ───────────────────────────────────────────────
-- Every calculation primitive invocation writes one row. Agents may reference
-- numbers only via calc_id / fact_id. company_id is a plain indexed column
-- (no FK) because benchmarks like SPY are not issuers in `companies`.
CREATE TABLE IF NOT EXISTS calc_ledger (
    id                 VARCHAR(64) PRIMARY KEY,
    company_id         VARCHAR(64),
    operation          VARCHAR(64) NOT NULL,   -- 'combine.divide' | 'change.yoy' | 'stat.cagr' | 'window_return'
    params             JSONB NOT NULL DEFAULT '{}',
    result             JSONB NOT NULL DEFAULT '{}',
    input_refs         JSONB NOT NULL DEFAULT '[]',   -- [fact_/calc_/price refs] feeding this
    primitive_version  VARCHAR(16) NOT NULL,
    invoked_by         VARCHAR(64),            -- session_id | 'recipe'
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_calc_ledger_company ON calc_ledger(company_id);
CREATE INDEX IF NOT EXISTS idx_calc_ledger_invoked ON calc_ledger(invoked_by);

-- ─── Runtime: Research Runs ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS research_runs (
    id                VARCHAR(64) PRIMARY KEY,
    company_id        VARCHAR(64) NOT NULL REFERENCES companies(id),
    portfolio_id      VARCHAR(64),
    status            VARCHAR(32) NOT NULL DEFAULT 'pending',   -- pending|running|completed|failed
    task_id           VARCHAR(64),
    agent_session_id  VARCHAR(64),          -- link to the analysis subagent session
    triggered_by      VARCHAR(64) DEFAULT 'manual',   -- 'manual' | 'agent:<session_id>'
    error_message     TEXT,
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_research_runs_company ON research_runs(company_id);
CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs(status);

-- ─── Runtime: Agent Sessions ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_sessions (
    id                VARCHAR(64) PRIMARY KEY,
    kind              VARCHAR(32) NOT NULL DEFAULT 'meta',   -- 'meta' | 'research'
    llm_model         VARCHAR(64),
    tool_budget       INTEGER,          -- snapshot of session_tool_budget at creation
    tools_used        INTEGER NOT NULL DEFAULT 0,
    external_searches INTEGER NOT NULL DEFAULT 0,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at          TIMESTAMPTZ
);

-- ─── Runtime: Agent Messages ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_messages (
    id          VARCHAR(64) PRIMARY KEY,
    session_id  VARCHAR(64) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    role        VARCHAR(16) NOT NULL,           -- 'user' | 'assistant'
    content     TEXT,
    citations   JSONB NOT NULL DEFAULT '[]',    -- assistant evidence refs
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id, created_at);

-- ─── Runtime: Agent Steps (APPEND-ONLY audit trail) ──────────────────────────
CREATE TABLE IF NOT EXISTS agent_steps (
    id                 VARCHAR(64) PRIMARY KEY,
    session_id         VARCHAR(64) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    message_id         VARCHAR(64),
    seq                INTEGER NOT NULL,
    step_type          VARCHAR(16) NOT NULL,          -- 'tool_call' | 'think' | 'delegation' | 'respond'
    tool_name          VARCHAR(64),
    args               JSONB NOT NULL DEFAULT '{}',   -- redacted (key-class fields stripped)
    result_summary     TEXT,
    evidence_refs      JSONB NOT NULL DEFAULT '[]',   -- [{type, id}] into the four stores
    status             VARCHAR(16) NOT NULL DEFAULT 'completed',   -- completed|rejected|error
    duration_ms        INTEGER,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_steps_session ON agent_steps(session_id, seq);

-- ─── Artifact: Evidence Packs ────────────────────────────────────────────────
-- pack is a refs LIST (not a full JSON snapshot): consistency guaranteed by the
-- append-only immutability of the four evidence stores.
CREATE TABLE IF NOT EXISTS evidence_packs (
    id                VARCHAR(64) PRIMARY KEY,
    research_run_id   VARCHAR(64) NOT NULL,
    session_id        VARCHAR(64),
    pack              JSONB NOT NULL DEFAULT '[]',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_evidence_packs_run ON evidence_packs(research_run_id);

-- ─── Artifact: Issuer Briefs ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS issuer_briefs (
    id                      VARCHAR(64) PRIMARY KEY,
    research_run_id         VARCHAR(64) NOT NULL UNIQUE,
    company_id              VARCHAR(64) NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    financial_summary       TEXT,
    key_changes             TEXT,
    management_explanation  TEXT,
    market_context          TEXT,
    portfolio_implications  TEXT,
    open_questions          TEXT,
    citations               JSONB NOT NULL DEFAULT '[]',
    confidence_flags        JSONB NOT NULL DEFAULT '{}',
    llm_model               VARCHAR(64),
    prompt_tokens           INTEGER,
    completion_tokens       INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_issuer_briefs_company ON issuer_briefs(company_id);
