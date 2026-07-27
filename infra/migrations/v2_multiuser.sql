-- V2 multi-user migration — idempotent ALTERs applied to a LIVE database.
-- init.sql already carries these for fresh databases; this file brings an
-- existing volume up to the same schema without a rebuild. Safe to re-run.
--
-- Apply:
--   docker exec -i exposure-postgres psql -U exposure -d exposure_workbench < infra/migrations/v2_multiuser.sql
--
-- This project has no alembic (see MODULE_NOTES M14 "明确不做"); this file is the
-- migration truth. Each V2 phase appends its section here.

-- ═══ V2-A: identity + owner columns (nullable; V2-C backfills + tightens) ═════

CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(255) PRIMARY KEY,
    email           VARCHAR(320),
    display_name    VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ
);

ALTER TABLE portfolios     ADD COLUMN IF NOT EXISTS owner_id      VARCHAR(255);
ALTER TABLE portfolios     ADD COLUMN IF NOT EXISTS is_public     BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS owner_id      VARCHAR(255);
ALTER TABLE research_runs  ADD COLUMN IF NOT EXISTS owner_id      VARCHAR(255);
ALTER TABLE issuer_briefs  ADD COLUMN IF NOT EXISTS owner_id      VARCHAR(255);
ALTER TABLE issuer_briefs  ADD COLUMN IF NOT EXISTS is_public     BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE tasks          ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(255);

-- ═══ V2-B: demo portfolio is public so anonymous visitors keep seeing it ══════
INSERT INTO users (id, email, display_name)
    VALUES ('user_demo_system', NULL, 'Demo (system)')
    ON CONFLICT (id) DO NOTHING;
UPDATE portfolios SET is_public = TRUE, owner_id = 'user_demo_system' WHERE id = 'port_001';

-- ═══ V2-C: Postgres RLS tenant isolation ═════════════════════════════════
-- Historical section — do not edit in place. The generator that emitted it
-- (scratchpad/gen_rls.py) was never committed and is gone; from V2-E onward
-- policies are hand-maintained, and a change lands as a NEW dated section at
-- the end of this file (re-running the whole file stays correct because every
-- CREATE POLICY is preceded by its own DROP, so the last definition wins).
-- The workflow_events policy below is SUPERSEDED by the V2-E0 section.
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

-- workflow_events: polymorphic (exposure run_ OR research rrun_)
ALTER TABLE workflow_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON workflow_events;
CREATE POLICY tenant ON workflow_events USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = workflow_events.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public)) OR EXISTS (SELECT 1 FROM research_runs rr WHERE rr.id = workflow_events.run_id AND rr.owner_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = workflow_events.run_id AND p.owner_id = current_setting('app.user_id', true)) OR EXISTS (SELECT 1 FROM research_runs rr WHERE rr.id = workflow_events.run_id AND rr.owner_id = current_setting('app.user_id', true)));

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

-- ═══ V2-D: security_master universe (shared, no RLS) ═════════════════════════
CREATE TABLE IF NOT EXISTS security_master (
    ticker      VARCHAR(20) PRIMARY KEY,
    name        VARCHAR(255),
    exchange    VARCHAR(32),
    is_etf      BOOLEAN NOT NULL DEFAULT FALSE,
    cik         VARCHAR(16),
    status      VARCHAR(16) NOT NULL DEFAULT 'active',
    source      VARCHAR(32),
    fetched_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_security_master_name ON security_master(name);
-- created after the ALL-TABLES grant above, so grant app_rls explicitly
GRANT SELECT, INSERT, UPDATE ON security_master TO app_rls;

-- ═══ V2-E0: prerequisite fixes (supersedes the V2-C block above) ═════════════
-- Re-running this whole file stays correct: every policy below is preceded by
-- its own DROP, so the later definition wins.

-- E0-1 — workflow_events is polymorphic over THREE parents, not two.
-- company_readiness logs its timeline under run_id = task.id ('task_' prefix,
-- set either by the handler's fallback or explicitly by meta_tools), which
-- matched neither branch, so the first step INSERT was denied and the task type
-- had never once completed through the worker (measured: 0 task-prefixed rows in
-- workflow_events, 0 company_readiness rows in tasks — not even failed ones).
-- BOTH halves need the third branch: ORM writes here are INSERT ... RETURNING
-- (flush() backfills the SERIAL id) and Postgres applies the SELECT policy
-- (USING) to the returned row, so patching only WITH CHECK still errors — with a
-- message that reads exactly like a WITH CHECK failure and sends you back to the
-- half you already fixed. tasks has no RLS, so the third EXISTS is a plain lookup.
DROP POLICY IF EXISTS tenant ON workflow_events;
CREATE POLICY tenant ON workflow_events USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = workflow_events.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public)) OR EXISTS (SELECT 1 FROM research_runs rr WHERE rr.id = workflow_events.run_id AND rr.owner_id = current_setting('app.user_id', true)) OR EXISTS (SELECT 1 FROM tasks t WHERE t.id = workflow_events.run_id AND t.owner_user_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = workflow_events.run_id AND p.owner_id = current_setting('app.user_id', true)) OR EXISTS (SELECT 1 FROM research_runs rr WHERE rr.id = workflow_events.run_id AND rr.owner_id = current_setting('app.user_id', true)) OR EXISTS (SELECT 1 FROM tasks t WHERE t.id = workflow_events.run_id AND t.owner_user_id = current_setting('app.user_id', true)));

-- E0-2 — cost views ran with their definer's (owner's) privileges, which bypass
-- RLS: measured on the live DB, app_rls with no tenant set saw 0 rows in
-- agent_sessions but all 20 in session_cost. No code reads them today, so this
-- was never exploited. security_invoker (PG15+) makes them honour the caller.
ALTER VIEW session_cost      SET (security_invoker = true);
ALTER VIEW research_run_cost SET (security_invoker = true);

-- ═══ V2-E1: worker lease + requeue ═══════════════════════════════════════════
-- lease_until is stamped from SERVER time at claim and never renewed. A past
-- value on a 'running' task means the worker holding it died; the reaper then
-- requeues the two replay-safe task types and fails the other two outright
-- (see task_service.REQUEUEABLE_TYPES for why that split is not symmetric).
-- retry_count already existed with no writer since P0 — the reaper is its first,
-- so non-zero values start appearing in the /tasks view. That is expected.
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_tasks_lease ON tasks(lease_until) WHERE status = 'running';

-- ═══ V2-E2/E3: turn lease + daily usage counters ═════════════════════════════
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS turn_started_at TIMESTAMPTZ;

-- Shared layer, NO RLS on purpose — see the note in init.sql. The global
-- backstop lives in this same table as the reserved row user_id = '_global'.
CREATE TABLE IF NOT EXISTS usage_daily (
    user_id     VARCHAR(255) NOT NULL,
    day         DATE NOT NULL,
    kind        VARCHAR(32) NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, kind)
);
-- Created after the ALL-TABLES grant near the top of this file, so app_rls needs
-- an explicit one (the same trap V2-D hit with security_master).
GRANT SELECT, INSERT, UPDATE ON usage_daily TO app_rls;
