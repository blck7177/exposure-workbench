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

-- ═══ V2-C: Postgres RLS tenant isolation (generated; do not hand-edit) ═════
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
