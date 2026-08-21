-- V6 report-gate migration — idempotent DDL applied to a LIVE database.
-- Safe to re-run: every statement is IF NOT EXISTS.
--
-- Apply (BEFORE restarting the API and worker — the ORM declares the column):
--   docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
--     -v ON_ERROR_STOP=1 < infra/migrations/v6_report_gate.sql
--
-- This project has no alembic (see MODULE_NOTES M14 "明确不做"); this file,
-- v2_multiuser.sql, v3_harness.sql, v4_cost.sql and v5_price_convention.sql are
-- the migration truth. Every file must be named in docs/PRODUCTION.md (enforced
-- by tests/test_deploy_config.py).
--
-- WHY: the exposure report is now gated — every number it states has to match a
-- value of a deterministic row of the same run. Six of them could not, and not
-- because the model invented them: the per-position contribution is the figure a
-- "top contributors" sentence is made of, calc_pnl has always computed it
-- (analytics/pnl.py), and issuer_exposures has never had a column to keep it in.
-- The gate cannot check a number against a row that does not exist, so the row
-- gets the column.

ALTER TABLE issuer_exposures ADD COLUMN IF NOT EXISTS contribution NUMERIC(12, 8);

-- Not backfilled. The value is derivable from rows already stored —
-- daily_pnl / (portfolio_market_value - daily_pnl) — but that identity holds
-- only when every holding priced on both days, and a run where one did not
-- would get a silently wrong number written into it years after the fact.
-- Historical runs keep NULL, which reads as "this run did not record it";
-- computing one would read as "this run measured it".
