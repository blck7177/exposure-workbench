-- V8 — the analysis products the gate already knows how to verify, made readable.
--
-- Replayable in full against a live database: every statement is guarded, and
-- nothing here backfills. A run that predates these columns records NULL, and
-- the read tools say so — a computed backfill would assert that a regression
-- which never recorded its window had one, which is the silent convention this
-- codebase keeps removing (see v5_price_convention.sql and v6_report_gate.sql
-- for the same decision taken twice before).
--
-- Apply BEFORE starting the new code: the read tools select these columns.

-- ─── V8-P1: the regression behind the betas ──────────────────────────────────
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS attribution_portfolio_return NUMERIC(12, 8);
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS alpha                  NUMERIC(12, 8);
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS residual               NUMERIC(12, 8);
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS model_r_squared        NUMERIC(12, 8);
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS observations           INTEGER;
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS regression_window_days INTEGER;
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS max_vif                NUMERIC(12, 6);
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS collinear              BOOLEAN;
ALTER TABLE exposure_metrics ADD COLUMN IF NOT EXISTS attribution_date       DATE;

-- ─── V8-P2/P3: the run's own findings become rows ────────────────────────────
-- ─── Stress results (V8-P2) ──────────────────────────────────────────────────
-- calc_stress computed all of this and it reached only workflow_events.payload,
-- which the evidence resolver cannot read. The CHECK is the load-bearing part:
-- an unevaluated scenario stored with loss 0.0 would read as "this book is safe
-- in a rates shock", which is the sentence calc_stress refuses to produce.
CREATE TABLE IF NOT EXISTS stress_results (
    id                  SERIAL PRIMARY KEY,
    run_id              VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    scenario            VARCHAR(64) NOT NULL,
    description         TEXT,
    shocks              JSONB NOT NULL DEFAULT '{}'::jsonb,
    loss_pct            NUMERIC(12, 8),
    loss_usd            NUMERIC(18, 2),
    factors_held_flat   JSONB NOT NULL DEFAULT '[]'::jsonb,
    status              VARCHAR(16) NOT NULL,
    reason              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, scenario),
    CONSTRAINT ck_stress_status CHECK (status IN ('evaluated', 'unevaluated')),
    CONSTRAINT ck_stress_unevaluated_has_no_loss CHECK (
        (status = 'evaluated'   AND loss_pct IS NOT NULL AND reason IS NULL) OR
        (status = 'unevaluated' AND loss_pct IS NULL AND loss_usd IS NULL
                                AND reason IS NOT NULL)
    )
);

-- ─── Limit checks (V8-P3) ────────────────────────────────────────────────────
-- The checks that ran and did NOT fire. Without them "three breached" is
-- citable and "the other five were clear" is not.
CREATE TABLE IF NOT EXISTS limit_checks (
    id          SERIAL PRIMARY KEY,
    run_id      VARCHAR(64) NOT NULL REFERENCES exposure_runs(id) ON DELETE CASCADE,
    limit_type  VARCHAR(64) NOT NULL,
    fired       BOOLEAN NOT NULL,
    alert_id    VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, limit_type)
);

-- V8-P2/P3: same shape as issuer_exposures — scoped through the run to the
-- portfolio. A run child with no policy is readable by every tenant.
ALTER TABLE stress_results ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON stress_results;
CREATE POLICY tenant ON stress_results USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = stress_results.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = stress_results.run_id AND p.owner_id = current_setting('app.user_id', true)));
ALTER TABLE limit_checks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant ON limit_checks;
CREATE POLICY tenant ON limit_checks USING (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = limit_checks.run_id AND (p.owner_id = current_setting('app.user_id', true) OR p.is_public))) WITH CHECK (EXISTS (SELECT 1 FROM exposure_runs r JOIN portfolios p ON p.id = r.portfolio_id WHERE r.id = limit_checks.run_id AND p.owner_id = current_setting('app.user_id', true)));
