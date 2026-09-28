-- V2 P2 (plan V2 §3, design v0.4 §07): the minimal persistent analysis state.
--
-- Three logical objects, on the existing stores wherever one already holds the
-- thing: WorkState is a new table, TaskState is columns on analyst_reports (the
-- record a task already leaves), Delivery is written on the llm_call step's args
-- by the loops and needs no column. Every model-written sentence that reaches
-- analysis_state has passed the same check a finding passes (services/
-- analysis_state.propose); a rejected proposal is an agent_steps row and
-- nothing here.
--
-- Tenant rule is the session's, exactly as facts, agent_steps and analyst_reports.
-- Additive and idempotent.
CREATE TABLE IF NOT EXISTS analysis_state (
    id            VARCHAR(64) PRIMARY KEY,
    session_id    VARCHAR(64) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    message_id    VARCHAR(64),
    version       INTEGER NOT NULL DEFAULT 1,
    question      TEXT,                          -- the user's words, verbatim
    requirements  JSONB NOT NULL DEFAULT '[]',   -- [{id, anchor, status, evidence, boundary}]
    scope         JSONB NOT NULL DEFAULT '{}',   -- {subjects, books, as_of, version}
    findings      JSONB NOT NULL DEFAULT '[]',   -- [{text, refs, requirement_ids, check_version, status, task_id}]
    gaps          JSONB NOT NULL DEFAULT '[]',   -- [{requirement_ids, type, boundary, tried}]
    tasks         JSONB NOT NULL DEFAULT '[]',   -- [{task_id, analyst, status, coverage}]
    budget        JSONB NOT NULL DEFAULT '{}',
    completion    VARCHAR(32),                   -- completed | completed_with_boundaries | partial
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analysis_state_session ON analysis_state(session_id, message_id);

ALTER TABLE analysis_state ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON analysis_state;
CREATE POLICY tenant ON analysis_state USING (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = analysis_state.session_id AND s.owner_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = analysis_state.session_id AND s.owner_id = current_setting('app.user_id', true)));

-- TaskState, on the record a task already leaves.
ALTER TABLE analyst_reports ADD COLUMN IF NOT EXISTS requirement_ids JSONB NOT NULL DEFAULT '[]';
ALTER TABLE analyst_reports ADD COLUMN IF NOT EXISTS input_version   JSONB NOT NULL DEFAULT '{}';
ALTER TABLE analyst_reports ADD COLUMN IF NOT EXISTS accepted_lines  JSONB NOT NULL DEFAULT '[]';
ALTER TABLE analyst_reports ADD COLUMN IF NOT EXISTS attempts        INTEGER;
ALTER TABLE analyst_reports ADD COLUMN IF NOT EXISTS receipts        JSONB NOT NULL DEFAULT '[]';

-- Which task a step belongs to. `actor` says which analyst; two tasks of one
-- analyst in one turn were indistinguishable on the trace (log_from_steps).
ALTER TABLE agent_steps ADD COLUMN IF NOT EXISTS task_id VARCHAR(64);
