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
