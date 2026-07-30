-- Exposure Workbench — PostgreSQL Schema
-- Auto-executed on first postgres container start.

-- ─── Extensions ──────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector: filing_chunks.embedding (Issuer Intelligence)

-- ─── Users (V2-A: identity from Clerk; local row for ownership FKs) ────────────
CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(255) PRIMARY KEY,   -- Clerk user id
    email           VARCHAR(320),
    display_name    VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ
);

-- ─── Security master (V2-D: investable US universe; shared, no RLS) ────────────
CREATE TABLE IF NOT EXISTS security_master (
    ticker      VARCHAR(20) PRIMARY KEY,   -- listing form, dot preserved (BRK.A)
    name        VARCHAR(255),
    exchange    VARCHAR(32),
    is_etf      BOOLEAN NOT NULL DEFAULT FALSE,
    cik         VARCHAR(16),
    status      VARCHAR(16) NOT NULL DEFAULT 'active',   -- active | delisted
    source      VARCHAR(32),
    fetched_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_security_master_name ON security_master(name);

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
    owner_id        VARCHAR(255),                        -- V2-A tenancy (NOT NULL in V2-C)
    is_public       BOOLEAN NOT NULL DEFAULT FALSE,
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
    type            VARCHAR(64) NOT NULL,  -- exposure_update|market_data_sync|company_readiness|issuer_research
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed
    payload         JSONB DEFAULT '{}',
    worker_id       VARCHAR(64),
    claimed_at      TIMESTAMPTZ,
    -- V2-E1: SERVER-time deadline stamped at claim. Past value + status='running'
    -- means the worker holding it died, and the reaper decides requeue vs fail by
    -- task type (see task_service.REQUEUEABLE_TYPES). Never renewed.
    lease_until     TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    owner_user_id   VARCHAR(255),   -- V2-A: whose request enqueued it (worker sets tenant from this)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(type);
-- V2-E1: the reaper runs on every worker poll (every WORKER_POLL_INTERVAL on an
-- idle queue), so give it a partial index rather than a scan of every task ever.
CREATE INDEX IF NOT EXISTS idx_tasks_lease ON tasks(lease_until) WHERE status = 'running';

-- ─── Daily usage counters (V2-E3) ────────────────────────────────────────────
-- The unit is a USER ACTION, not a token or a tool call. Deliberately in the
-- SHARED layer with NO RLS, like tasks: the global backstop pool has to count
-- across tenants, and any `user_id = current_setting(...)` policy would silently
-- reduce it to counting only the caller — a fail-OPEN backstop, which is worse
-- than none. The global pool is just the reserved row user_id = '_global', so a
-- single primitive covers both levels. Read routes filter by user for meaning,
-- not for safety, and say so at the call site.
CREATE TABLE IF NOT EXISTS usage_daily (
    user_id     VARCHAR(255) NOT NULL,   -- Clerk user id, or the reserved '_global'
    day         DATE NOT NULL,           -- UTC; resets at 00:00 UTC
    -- Deliberately unconstrained: no CHECK, no enum. Adding a pool is a change
    -- to usage_service.POOLS and two settings, never a migration. This comment
    -- is therefore the ONLY thing that can drift — keep it level with POOLS.
    kind        VARCHAR(32) NOT NULL,    -- chat_turn|research_run|readiness|exposure_run|market_sync
                                         -- |portfolio_create|position_upload|agent_session  (V2-H)
    used        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, kind)
);

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
    owner_id          VARCHAR(255),   -- V2-A tenancy
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
    owner_id          VARCHAR(255),   -- V2-A tenancy
    llm_model         VARCHAR(64),
    tool_budget       INTEGER,          -- snapshot of session_tool_budget at creation
    tools_used        INTEGER NOT NULL DEFAULT 0,
    external_searches INTEGER NOT NULL DEFAULT 0,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at          TIMESTAMPTZ,
    -- V2-E2: non-NULL and recent => a turn is in flight. Set from SERVER time.
    turn_started_at   TIMESTAMPTZ
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
    owner_id                VARCHAR(255),                     -- V2-A tenancy
    is_public               BOOLEAN NOT NULL DEFAULT FALSE,
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


-- ═════════════════════════════════════════════════════════════════════════════
-- OBSERVABILITY COST VIEWS (M11) — token/call accounting. Account complete;
-- the MVP UI shows only per-session/brief footers, but the numbers are all here.
--
-- V2-E0: both carry security_invoker. Without it a view runs with its DEFINER's
-- privileges (the owner role, which bypasses RLS), so app_rls read straight
-- through the tenant policies — measured on the live DB: an unset tenant saw
-- 0 rows in agent_sessions but all 20 in session_cost. Any future view over an
-- RLS table must set this too; prefer querying the table directly.
-- ═════════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW session_cost WITH (security_invoker = true) AS
SELECT s.id AS session_id, s.kind, s.llm_model,
       s.tools_used, s.external_searches,
       count(st.id) AS trace_steps,
       count(st.id) FILTER (WHERE st.status = 'rejected') AS rejected_steps,
       coalesce(sum(st.prompt_tokens), 0) AS prompt_tokens,
       coalesce(sum(st.completion_tokens), 0) AS completion_tokens
FROM agent_sessions s
LEFT JOIN agent_steps st ON st.session_id = s.id
GROUP BY s.id;

CREATE OR REPLACE VIEW research_run_cost WITH (security_invoker = true) AS
SELECT r.id AS research_run_id, r.company_id, r.status,
       sc.tools_used, sc.external_searches, sc.trace_steps,
       sc.prompt_tokens, sc.completion_tokens
FROM research_runs r
LEFT JOIN session_cost sc ON sc.session_id = r.agent_session_id;

-- ═══ V2-C: Postgres RLS tenant isolation ═════════════════════════════════
-- Originally emitted by a throwaway generator (scratchpad/gen_rls.py, never
-- committed and now gone), so this block is hand-maintained from V2-E onward:
-- edit here, then mirror the change as a NEW dated section at the end of
-- infra/migrations/v2_multiuser.sql — this file is the fresh-DB truth, that
-- file is the chronological log applied to live volumes.
-- Runtime connects as the non-owner role app_rls, so these policies bind.
-- The table owner (exposure) BYPASSES RLS, so seed/migration/DDL are unaffected.
-- app.user_id is set transaction-locally by the app (db/session.py listener);
-- unset => current_setting returns NULL => only is_public rows are visible
-- (fail-closed). app_rls has no DELETE (append-only hardened at the grant layer).

-- ── role + grants ────────────────────────────────────────────────────────
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rls') THEN
    CREATE ROLE app_rls LOGIN PASSWORD 'app_rls_pw';
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO app_rls;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_rls;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rls;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO app_rls;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_rls;

-- ── backfill owners + public flags before policies bind ──────────────────
INSERT INTO users (id, email, display_name)
    VALUES ('user_demo_system', NULL, 'Demo (system)') ON CONFLICT (id) DO NOTHING;
UPDATE portfolios     SET owner_id = 'user_demo_system' WHERE owner_id IS NULL;
UPDATE portfolios     SET is_public = TRUE WHERE id = 'port_001';
UPDATE agent_sessions SET owner_id = 'user_demo_system' WHERE owner_id IS NULL;
UPDATE research_runs  SET owner_id = 'user_demo_system' WHERE owner_id IS NULL;
UPDATE issuer_briefs  SET owner_id = 'user_demo_system' WHERE owner_id IS NULL;
UPDATE issuer_briefs  SET is_public = TRUE WHERE owner_id = 'user_demo_system';

-- ── policies ─────────────────────────────────────────────────────────────
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON users;
CREATE POLICY tenant ON users USING (users.id = current_setting('app.user_id', true)) WITH CHECK (users.id = current_setting('app.user_id', true));
ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON portfolios;
CREATE POLICY tenant ON portfolios USING (portfolios.owner_id = current_setting('app.user_id', true) OR portfolios.is_public) WITH CHECK (portfolios.owner_id = current_setting('app.user_id', true));
ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON agent_sessions;
CREATE POLICY tenant ON agent_sessions USING (agent_sessions.owner_id = current_setting('app.user_id', true)) WITH CHECK (agent_sessions.owner_id = current_setting('app.user_id', true));
ALTER TABLE research_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON research_runs;
CREATE POLICY tenant ON research_runs USING (research_runs.owner_id = current_setting('app.user_id', true)) WITH CHECK (research_runs.owner_id = current_setting('app.user_id', true));
ALTER TABLE issuer_briefs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON issuer_briefs;
CREATE POLICY tenant ON issuer_briefs USING (issuer_briefs.owner_id = current_setting('app.user_id', true) OR issuer_briefs.is_public) WITH CHECK (issuer_briefs.owner_id = current_setting('app.user_id', true));

-- portfolio children
ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON positions;
CREATE POLICY tenant ON positions USING (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = positions.portfolio_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = positions.portfolio_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE risk_limits ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON risk_limits;
CREATE POLICY tenant ON risk_limits USING (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = risk_limits.portfolio_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = risk_limits.portfolio_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE exposure_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON exposure_runs;
CREATE POLICY tenant ON exposure_runs USING (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = exposure_runs.portfolio_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = exposure_runs.portfolio_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE schedules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON schedules;
CREATE POLICY tenant ON schedules USING (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = schedules.portfolio_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = schedules.portfolio_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE daily_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON daily_reports;
CREATE POLICY tenant ON daily_reports USING (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = daily_reports.portfolio_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM portfolios p WHERE p.id = daily_reports.portfolio_id AND p.owner_id = current_setting('app.user_id', true)));

-- exposure-run children
ALTER TABLE exposure_metrics ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON exposure_metrics;
CREATE POLICY tenant ON exposure_metrics USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = exposure_metrics.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = exposure_metrics.run_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE sector_exposures ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON sector_exposures;
CREATE POLICY tenant ON sector_exposures USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = sector_exposures.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = sector_exposures.run_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE issuer_exposures ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON issuer_exposures;
CREATE POLICY tenant ON issuer_exposures USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = issuer_exposures.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = issuer_exposures.run_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE factor_attributions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON factor_attributions;
CREATE POLICY tenant ON factor_attributions USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = factor_attributions.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = factor_attributions.run_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE factor_residuals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON factor_residuals;
CREATE POLICY tenant ON factor_residuals USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = factor_residuals.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = factor_residuals.run_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE risk_alerts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON risk_alerts;
CREATE POLICY tenant ON risk_alerts USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = risk_alerts.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = risk_alerts.run_id AND p.owner_id = current_setting('app.user_id', true)));

-- workflow_events: polymorphic over THREE parents — exposure run_, research
-- rrun_, and (V2-E0) task_ for company_readiness, whose handler logs its
-- timeline under run_id = task.id. Missing that third branch denied every
-- readiness step INSERT, so the task type had never once completed through the
-- worker. Both USING and WITH CHECK need it: ORM writes here are
-- INSERT ... RETURNING (flush() backfills the SERIAL id), and Postgres applies
-- the SELECT policy to the returned row, so patching only WITH CHECK still
-- fails — with an error whose text reads exactly like a WITH CHECK failure.
-- tasks carries no RLS, so the third EXISTS is an ordinary lookup.
ALTER TABLE workflow_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON workflow_events;
CREATE POLICY tenant ON workflow_events USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = workflow_events.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public)) OR EXISTS (SELECT 1 FROM research_runs rr WHERE rr.id = workflow_events.run_id AND rr.owner_id = current_setting('app.user_id', true)) OR EXISTS (SELECT 1 FROM tasks t WHERE t.id = workflow_events.run_id AND t.owner_user_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = workflow_events.run_id AND p.owner_id = current_setting('app.user_id', true)) OR EXISTS (SELECT 1 FROM research_runs rr WHERE rr.id = workflow_events.run_id AND rr.owner_id = current_setting('app.user_id', true)) OR EXISTS (SELECT 1 FROM tasks t WHERE t.id = workflow_events.run_id AND t.owner_user_id = current_setting('app.user_id', true)));

-- agent-session children
ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON agent_messages;
CREATE POLICY tenant ON agent_messages USING (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = agent_messages.session_id AND s.owner_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = agent_messages.session_id AND s.owner_id = current_setting('app.user_id', true)));
ALTER TABLE agent_steps ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON agent_steps;
CREATE POLICY tenant ON agent_steps USING (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = agent_steps.session_id AND s.owner_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = agent_steps.session_id AND s.owner_id = current_setting('app.user_id', true)));
ALTER TABLE evidence_packs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON evidence_packs;
CREATE POLICY tenant ON evidence_packs USING (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = evidence_packs.session_id AND s.owner_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = evidence_packs.session_id AND s.owner_id = current_setting('app.user_id', true)));
