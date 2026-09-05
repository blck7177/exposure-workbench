-- V24: the facts table — every Fact a tool ever put in front of the model, by id.
-- The step (agent_steps.evidence_refs) is the record of what one call showed;
-- this table is the index, so the evidence drawer, a brief and a later session
-- resolve an f_ id without finding the step. Written in the same transaction
-- as the step. Additive and idempotent. Tenant rule mirrors agent_steps.
CREATE TABLE IF NOT EXISTS facts (
    id          VARCHAR(64) PRIMARY KEY,
    session_id  VARCHAR(64) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    step_id     VARCHAR(64),
    message_id  VARCHAR(64),
    kind        VARCHAR(16) NOT NULL,          -- scalar | series | passage | absence | task
    subject     VARCHAR(64),
    measure     TEXT NOT NULL,
    unit        VARCHAR(24),
    value       DOUBLE PRECISION,
    points      JSONB,
    text        TEXT,
    as_of       VARCHAR(32),
    "window"    JSONB,
    params      JSONB NOT NULL DEFAULT '{}',
    standalone  BOOLEAN NOT NULL DEFAULT TRUE,
    sources     JSONB NOT NULL DEFAULT '[]',
    "group"     VARCHAR(32),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_facts_session ON facts(session_id);
ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON facts;
CREATE POLICY tenant ON facts USING (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = facts.session_id AND s.owner_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = facts.session_id AND s.owner_id = current_setting('app.user_id', true)));
