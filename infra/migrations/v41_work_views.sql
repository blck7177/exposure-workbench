-- v41: the work view replaces analysis_state (agents/work_view).
--
-- A user turn's record is now a projection of what happened: the analysis views
-- run (`analyze`), the specialists' notes with the observer's verification of
-- them, how each task ended and the budget — one JSONB body per turn, versioned.
-- The requirements/findings/gaps/completion columns of analysis_state belonged to
-- the settled/requirements protocol, which no loop speaks any more; the table is
-- dropped rather than kept beside its successor.
--
-- Tenant rule is the session's, exactly as facts, agent_steps and analyst_reports.
CREATE TABLE IF NOT EXISTS work_views (
    id            VARCHAR(64) PRIMARY KEY,
    session_id    VARCHAR(64) NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
    message_id    VARCHAR(64),
    version       INTEGER NOT NULL DEFAULT 1,
    body          JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_work_views_session ON work_views(session_id, message_id);

ALTER TABLE work_views ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON work_views;
CREATE POLICY tenant ON work_views USING (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = work_views.session_id AND s.owner_id = current_setting('app.user_id', true))) WITH CHECK (EXISTS (SELECT 1 FROM agent_sessions s WHERE s.id = work_views.session_id AND s.owner_id = current_setting('app.user_id', true)));
GRANT SELECT, INSERT, UPDATE, DELETE ON work_views TO app_rls;

DROP TABLE IF EXISTS analysis_state;

-- The ledger rows typed by operation name alone (resources.LEGACY_RATIO_OPS) get
-- their unit written down, so no reader needs the name any more.
UPDATE calc_ledger SET unit_class = 'RATIO'
 WHERE unit_class IS NULL
   AND operation IN ('change.yoy', 'change.qoq', 'change.pct', 'combine.divide', 'stat.cagr', 'window_return',
                     'window_return.relative', 'calc.scalar.divide', 'calc.series.divide', 'stat.mean', 'stat.stdev',
                     'portfolio.reconcile', 'portfolio.drawdown_episodes', 'portfolio.integration');

-- The specialist's record drops the settled/requirements protocol's columns.
ALTER TABLE analyst_reports DROP COLUMN IF EXISTS requirement_ids;
ALTER TABLE analyst_reports DROP COLUMN IF EXISTS input_version;
ALTER TABLE analyst_reports DROP COLUMN IF EXISTS accepted_lines;
ALTER TABLE analyst_reports DROP COLUMN IF EXISTS attempts;
ALTER TABLE analyst_reports DROP COLUMN IF EXISTS receipts;
