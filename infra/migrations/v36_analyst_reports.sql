-- V36: a domain analyst's full reading, kept on the record.
--
-- A turn now has two kinds of writing in it: the brief a domain analyst files
-- for the lead, which is short and answers the task line by line, and the
-- report behind it. The lead reads the brief; the reader opens the report when
-- the brief is not enough. Both pass the answer check against the same session
-- ledger, so `status` is what the check said and a refused report keeps its
-- problems instead of its prose — showing unchecked analysis under a heading
-- that implies it was checked is the one failure this table must not have.
--
-- Tenant rule is the session's, exactly as `facts` and `agent_steps`.
-- Additive and idempotent.
CREATE TABLE IF NOT EXISTS analyst_reports (
    id                 VARCHAR(64) PRIMARY KEY,
    session_id         VARCHAR(64) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    message_id         VARCHAR(64),
    task_id            VARCHAR(64),
    domain             VARCHAR(64) NOT NULL,
    status             VARCHAR(16) NOT NULL,          -- verified | refused
    title              TEXT,
    brief              JSONB NOT NULL DEFAULT '{}',   -- findings / not_done / caveats / follow_ups, as filed
    text               TEXT,                          -- the report's prose, figures written as the desk showed them
    blocks             JSONB NOT NULL DEFAULT '[]',   -- answer_check.accepted's blocks; empty when refused
    citations          JSONB NOT NULL DEFAULT '[]',
    verified           JSONB NOT NULL DEFAULT '{}',
    problems           JSONB NOT NULL DEFAULT '[]',   -- non-empty only when refused
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    evidence_calls     INTEGER,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analyst_reports_session ON analyst_reports(session_id, message_id);

ALTER TABLE analyst_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON analyst_reports;
CREATE POLICY tenant ON analyst_reports USING (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = analyst_reports.session_id AND s.owner_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = analyst_reports.session_id AND s.owner_id = current_setting('app.user_id', true)));
