-- V13-S2 — a run that stopped says WHAT KIND of failure it was, separately from
-- whose words describe it.
--
-- Before this, a failed research run reached the person waiting for it as
-- whatever str(exc) happened to be, rendered verbatim on the issuer page. Off
-- the live database on 2026-08-29:
--
--   Research agent analysing AAPL — ERROR: Error code: 429 - {'error':
--       {'message': 'You exceeded your current quota, please check your plan …
--   the research tool face at http://exposure-mcp:8000/mcp/research could not
--       be reached (connect_error)
--   pre-fix crash (max_tokens param)
--
-- A billing relationship the reader is not party to, an internal hostname, and
-- a note this desk wrote to itself.
--
-- error_code is the closed set in exposure_workbench.errors.workflow_codes; the
-- UI keys its sentence on it. error_detail is the exception's own words, kept
-- because the operator needs them and shown only in the audit layer.
--
-- NOT BACKFILLED, for the third time in this repo and the same reason as
-- exposure_metrics' regression columns (v8_skill_reads.sql) and
-- issuer_exposures.contribution (v6_report_gate.sql): a run that never recorded
-- what kind of failure it had does not acquire one by being asked later.
-- Guessing a code from the old error_message text would be exactly the
-- text-matching this batch replaced. NULL reads as "this run did not record
-- it", and the UI answers with its generic sentence rather than a claim about a
-- cause it does not have.
--
-- Idempotent and safe to run against the old code: nothing reads these columns
-- until the images carrying V13 are up.

ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS error_code   VARCHAR(32);
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS error_detail TEXT;

ALTER TABLE exposure_runs ADD COLUMN IF NOT EXISTS error_code   VARCHAR(32);
ALTER TABLE exposure_runs ADD COLUMN IF NOT EXISTS error_detail TEXT;

COMMENT ON COLUMN research_runs.error_code IS
    'exposure_workbench.errors.workflow_codes; NULL = recorded before V13';
COMMENT ON COLUMN research_runs.error_detail IS
    'the exception''s own words — audit layer only, never the reader''s sentence';
COMMENT ON COLUMN exposure_runs.error_code IS
    'exposure_workbench.errors.workflow_codes; NULL = recorded before V13';
COMMENT ON COLUMN exposure_runs.error_detail IS
    'the exception''s own words — audit layer only, never the reader''s sentence';
