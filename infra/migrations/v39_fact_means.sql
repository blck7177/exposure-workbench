-- V39 (IMPLEMENTATION_PLAN_V1, step 1): what a reading MEANS, on the fact itself.
-- The services computed the words — a net beta's loses/gains, a check's
-- clear/warning/breach, that a fit is collinear — and the tool boundary dropped
-- them, so the model read a signed number and a handbook sentence about signs.
-- `means` holds those words in the registry's closed vocabulary
-- (analytics/registry.py): direction | status | basis | flags | reason | way_out.
-- Additive and idempotent. A row written before this has '{}' and renders
-- without the clause; nothing is backfilled, because the word was never recorded.
ALTER TABLE facts ADD COLUMN IF NOT EXISTS means JSONB NOT NULL DEFAULT '{}';
