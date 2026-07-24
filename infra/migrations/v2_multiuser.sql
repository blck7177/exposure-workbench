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
