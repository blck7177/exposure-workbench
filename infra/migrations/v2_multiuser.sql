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
    -- chat_turn|research_run|readiness|exposure_run|market_sync
    -- |portfolio_create|position_upload|agent_session  (V2-H)
    -- Unconstrained on purpose: a new pool needs no DDL, so this comment is the
    -- only thing that can fall behind usage_service.POOLS.
    kind        VARCHAR(32) NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, kind)
);
-- Created after the ALL-TABLES grant near the top of this file, so app_rls needs
-- an explicit one (the same trap V2-D hit with security_master).
GRANT SELECT, INSERT, UPDATE ON usage_daily TO app_rls;

-- ═══ V2-H4 (2026-08-02): risk_limits becomes the only source of a threshold ══
-- Until now every threshold a run used came from configs/risk_limits.yaml, or —
-- because the API container has no /app/configs — from 16 literals inside
-- check_limits' own cfg() closure. The risk_limits rows were built, passed in as
-- `db_limits`, and never read. Making the table authoritative means the numbers
-- stop passing through git review on their way in, so the guarantees review used
-- to provide have to become constraints.
--
-- Statement order below is argued, not arbitrary. Read the comment on each one
-- before moving it.
--
-- An ADD CONSTRAINT below can fail on a row that already violates it. That is
-- the intended outcome, and the fix is the row: weakening the constraint would
-- leave the offending number in force with nothing anywhere else checking it.

-- (1) A risk_limits.limit_type VALUE is renamed here. Nothing else is.
-- 'stress_loss_tech' is ALSO the name of an unrelated NUMERIC column on
-- exposure_metrics — the tech_selloff scenario's estimated_loss_pct, written by
-- every run. That column is NOT renamed, dropped or touched by this migration:
-- the statement below is scoped to risk_limits and only rewrites a string value
-- in one column of that one table. Nothing here reads exposure_metrics at all.
--
-- As a limit_type, 'stress_loss_tech' is a legacy name from the retired seed CSV
-- that no code has ever looked up — check_limits asks for 'stress_loss'. Yet all
-- six rows are is_active=true and GET /portfolios/{id}/limits has been serving
-- them to users as policy in force. The numbers already ARE the stress_loss
-- numbers, so this is a rename, not a policy change.
--
-- It runs BEFORE the index on purpose: a volume that somehow holds both names
-- for one portfolio then fails at index creation, loudly, instead of quietly
-- ending up with two portfolio-wide defaults for the same check. Re-running this
-- file matches nothing.
UPDATE risk_limits SET limit_type = 'stress_loss' WHERE limit_type = 'stress_loss_tech';

-- (2) The existing UNIQUE (portfolio_id, limit_type, entity_id) is NULLS
-- DISTINCT on PG 16, so two contradictory portfolio-wide defaults for the same
-- check are legal today. Without this index the read path would need a tie-break
-- over duplicates — the same shape of patch this whole change exists to delete.
CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_limits_default
    ON risk_limits (portfolio_id, limit_type) WHERE entity_id IS NULL;

-- (3) There is NO check on these numbers today. The two failures below were out
-- of reach only because every threshold arrived through a YAML in git review,
-- which is exactly what this change removes. Both are mechanical own-goals, and
-- each disables a tier outright:
--   * warning_level <= 0 makes every positive reading an alert, because
--     _check_one's only floor is its `current_value <= 0` early return.
--   * breach_level <= warning_level kills the warning tier, because breach is
--     tested first, so a value that should have warned is reported as a breach.
--     Equality does that exactly as thoroughly as inversion — hence strict `>`.
-- Requiring breach > warning > 0 also keeps breach_level off zero, and zero is
-- what would pin every utilization on the row to 0.0.
--
-- What it does NOT do is judge whether a number is sensible for the check it
-- belongs to, and it deliberately does not try: breach_level = 9.99 on
-- daily_loss satisfies this and can never fire. A ceiling would have to be
-- per-check, because gross_exposure legitimately sits above 1.0 (1.10/1.20
-- seeded below, higher for a levered book), and a per-check ceiling is threshold
-- numbers back in the schema — the fourth source of truth this change deletes.
-- So nothing catches an implausible-but-legal number today: the limits endpoint
-- displays it, and no code judges it.
--
-- Live database checked 2026-08-02: 0 rows with a non-positive warning_level,
-- 0 rows with breach_level <= warning_level. This ADD will not fail there.
ALTER TABLE risk_limits DROP CONSTRAINT IF EXISTS ck_risk_limits_levels;
ALTER TABLE risk_limits ADD  CONSTRAINT ck_risk_limits_levels
    CHECK (warning_level > 0 AND breach_level > warning_level);

-- (4) Nothing reads the 'unit' column and _check_one compares raw floats, so
-- unit='percent', warning=15, breach=20 is schema-valid today and can never
-- fire. Making the table authoritative would IMPORT an error class the YAML
-- never had.
--
-- The IS NOT NULL half is not redundant: `unit` is nullable, and a CHECK whose
-- predicate evaluates to NULL is satisfied, so `unit = 'fraction'` on its own
-- would let an explicit unit=NULL row straight through and leave the
-- percent-scale error class open — the constraint would read as coverage while
-- providing none.
--
-- Live database checked 2026-08-02: 0 NULL units, 0 rows on any other scale.
ALTER TABLE risk_limits DROP CONSTRAINT IF EXISTS ck_risk_limits_unit;
ALTER TABLE risk_limits ADD  CONSTRAINT ck_risk_limits_unit
    CHECK (unit IS NOT NULL AND unit = 'fraction');

-- (5) app_rls has no DELETE, so is_active=false is the only removal mechanism a
-- user has. Aimed at a required portfolio-wide default it would arm a run
-- failure for later — "deactivate" and "fail every future run" would be the same
-- button. Per-entity overrides stay deactivatable; that is the supported way to
-- retire one.
ALTER TABLE risk_limits DROP CONSTRAINT IF EXISTS ck_risk_limits_default_active;
ALTER TABLE risk_limits ADD  CONSTRAINT ck_risk_limits_default_active
    CHECK (is_active OR entity_id IS NOT NULL);

-- (6) The backfill: every portfolio gets the eight portfolio-wide defaults it is
-- now required to carry.
--
-- A CROSS JOIN over portfolios, never an enumerated id list: port_rvprobe exists
-- in the live database with zero grep hits anywhere in this repo, so portfolios
-- demonstrably appear from outside the codebase and any hand-written list is
-- already wrong.
--
-- The VALUES block is a FROZEN SNAPSHOT of analytics/limit_defaults.SEED_DEFAULTS
-- as of this date. It is NOT a second source of truth, and it must NOT be edited
-- when SEED_DEFAULTS changes: a later policy change reaches new databases through
-- the seed and existing ones through its own dated section further down this
-- file. Every row is ON CONFLICT DO NOTHING, so this statement can only create a
-- default that is missing — it can never move a number already in the table.
-- tests/test_risk_limits_parity.py pins these literals to SEED_DEFAULTS, so
-- editing one without the other fails offline.
--
-- Run as the owner (psql -U exposure). The tenant policy's WITH CHECK compares
-- p.owner_id to current_setting('app.user_id'), which is unset here, so app_rls
-- would be refused every insert.
INSERT INTO risk_limits (id, portfolio_id, limit_type, entity_type, entity_id,
                         warning_level, breach_level, unit, is_active)
SELECT 'rl_' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 12),
       p.id, d.limit_type, d.entity_type, NULL, d.warning, d.breach, 'fraction', TRUE
  FROM portfolios p
 CROSS JOIN (VALUES
     ('issuer_concentration',   'issuer',    0.15,  0.20),
     ('sector_concentration',   'sector',    0.40,  0.50),
     ('gross_exposure',         'portfolio', 1.10,  1.20),
     ('var_95',                 'portfolio', 0.025, 0.035),
     ('expected_shortfall_95',  'portfolio', 0.035, 0.050),
     ('daily_loss',             'portfolio', 0.020, 0.030),
     ('stress_loss',            'portfolio', 0.060, 0.080),
     ('rolling_volatility_30d', 'portfolio', 0.18,  0.25)
 ) AS d(limit_type, entity_type, warning, breach)
ON CONFLICT (portfolio_id, limit_type) WHERE entity_id IS NULL DO NOTHING;

-- (7) Verification, as two statements that FAIL rather than two that print.
--
-- These were bare SELECTs until the reviewer pointed out what that buys:
-- docs/PRODUCTION.md pipes this file through `psql -v ON_ERROR_STOP=1` and then
-- proceeds unconditionally to v3_harness.sql and `docker compose up -d`. psql
-- exits 0 whether a SELECT returns eight rows or none, so ON_ERROR_STOP cannot
-- see a failed check and the operator's only warning is a table in scrollback
-- that scrolls past. A guarantee that depends on someone reading output is not
-- a guarantee. RAISE EXCEPTION is what makes ON_ERROR_STOP stop.
--
-- Each message names the offending rows. The fix for either is the row — add
-- the missing default, or delete/rename the row naming a check that does not
-- exist — never a weaker check here, for the same reason statement (3) argues:
-- weakening leaves the offending row in force with nothing else looking at it.
--
-- Both are read-only. Re-running this file after the fix is safe and expected.

-- Any portfolio missing a required active portfolio-wide default. Once
-- risk_limits is the only source, that check has no number to run against; the
-- contract analytics/limits.MissingLimit states is a run that stops rather than
-- one that invents a threshold. So a portfolio listed here is a book that cannot
-- be valued — found at deploy time instead of by a user pressing Run.
DO $$
DECLARE missing_defaults text;
BEGIN
    SELECT string_agg(p.id || '/' || t.limit_type, ', ' ORDER BY p.id, t.limit_type)
      INTO missing_defaults
      FROM portfolios p
     CROSS JOIN (VALUES
         ('issuer_concentration'), ('sector_concentration'), ('gross_exposure'),
         ('var_95'), ('expected_shortfall_95'), ('daily_loss'),
         ('stress_loss'), ('rolling_volatility_30d')
     ) AS t(limit_type)
     WHERE NOT EXISTS (
         SELECT 1 FROM risk_limits rl
          WHERE rl.portfolio_id = p.id
            AND rl.limit_type = t.limit_type
            AND rl.entity_id IS NULL
            AND rl.is_active
     );
    IF missing_defaults IS NOT NULL THEN
        RAISE EXCEPTION
            'V2-H4: these portfolio/limit_type pairs have no active portfolio-wide default, so those portfolios cannot be run: %',
            missing_defaults;
    END IF;
END $$;

-- Any limit_type in the table the engine cannot evaluate. A row here is the
-- stress_loss_tech failure repeating itself: served to users as policy in force,
-- looked up by nothing.
DO $$
DECLARE unknown_types text;
BEGIN
    SELECT string_agg(DISTINCT limit_type, ', ')
      INTO unknown_types
      FROM risk_limits
     WHERE limit_type NOT IN (
         'issuer_concentration', 'sector_concentration', 'gross_exposure',
         'var_95', 'expected_shortfall_95', 'daily_loss',
         'stress_loss', 'rolling_volatility_30d'
     );
    IF unknown_types IS NOT NULL THEN
        RAISE EXCEPTION
            'V2-H4: risk_limits rows name checks the engine cannot run: %',
            unknown_types;
    END IF;
END $$;
