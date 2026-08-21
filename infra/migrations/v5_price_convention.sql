-- V5 price-convention migration — idempotent DDL applied to a LIVE database.
-- Safe to re-run: every statement is IF NOT EXISTS.
--
-- Apply (BEFORE restarting the API and worker — the ORM declares the column
-- below and the read path raises a named error where it is null):
--   docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
--     -v ON_ERROR_STOP=1 < infra/migrations/v5_price_convention.sql
--
-- This project has no alembic (see MODULE_NOTES M14 "明确不做"); this file,
-- v2_multiuser.sql, v3_harness.sql and v4_cost.sql are the migration truth.
-- Every file must be named in docs/PRODUCTION.md (enforced by
-- tests/test_deploy_config.py).
--
-- WHY: market_prices has carried adj_close since M4, factor_prices never did.
-- After V5 every return in the system is measured on the adjusted series, and
-- the factor panel is one side of the regression that produces the betas. Two
-- of the eight factors — TLT and HYG — distribute several percent a year, so on
-- close alone their returns are short by exactly those distributions and every
-- beta estimated against them is biased by it.

ALTER TABLE factor_prices ADD COLUMN IF NOT EXISTS adj_close NUMERIC(18, 4);

-- Deliberately NOT backfilled with `close`. Existing rows are unadjusted and
-- copying them into adj_close would assert, in the data itself, that they had
-- been adjusted — the exact silent-convention failure this batch removes. They
-- stay NULL, market_data_service raises a named error naming the ticker, and
-- the exposure workflow's step 1 re-ingests factor prices on the next run,
-- which repopulates the column from the provider. One run, self-healing, no
-- fabricated history in between.
