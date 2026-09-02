-- V17: eight measures and a beta are read as multiples, not as percents.
--
-- money ÷ money is a RATIO to the unit algebra, and that is all it can be: net
-- margin and debt/EBITDA are the same operation on the same units. Only the
-- registry knows which of the two a named measure is, and until now it had no
-- way to say so — so every coverage, turnover and leverage ratio on this desk
-- was displayed by the percent rule. A debt/EBITDA of 2.30 reached the reader
-- as "230.0%", a current ratio of 1.85 as "185.0%", and an OLS beta of -0.543
-- as "-54.3%" (the G7 residual in docs/spikes/V16_COVERAGE.md §1).
--
-- WHAT THIS FILE DOES AND DOES NOT DO. It corrects the recorded READING of
-- rows that already exist. No value is touched, no operand, no basis, no input
-- ref, no period: the number each row holds was always right, and what was
-- wrong was the column saying how to print it. That is why this is an UPDATE on
-- an append-only ledger and stays one — a row whose value changed would be a
-- new row, and there is no such row here.
--
-- Both places are corrected, not one. `calc_ledger.unit_class` is what the
-- table and the reader read (services/quantities._calc_unit); the JSONB
-- `params.result_type.unit_class` is what the calculator reads back when the
-- row becomes an operand (services/typed_calculator._resolve). Leaving one
-- behind would be two rules about one fact, which is the failure mode the
-- column was introduced to end (v15_calc_unit.sql).
--
-- The name list is the registry's, in analytics/formulas.py: exactly the
-- formulas declaring unit_class='multiple'. tests/test_v9_formulas.py holds
-- that list to the same eight, so a ninth measure added there without a line
-- here is visible — this file is history, not a mirror that has to keep up.
--
-- Idempotent: re-running matches nothing the first run already changed.

BEGIN;

UPDATE calc_ledger
   SET unit_class = 'MULTIPLE',
       params = jsonb_set(params, '{result_type,unit_class}', '"multiple"')
 WHERE unit_class = 'RATIO'
   AND params->'result_type'->>'quantity' IN (
        'ebit_interest_coverage',
        'debt_to_ebitda',
        'debt_to_operating_cash_flow',
        'net_debt_to_ebitda',
        'current_ratio',
        'quick_ratio',
        'asset_turnover',
        'equity_multiplier'
   );

-- A beta is how many times the benchmark's move the name makes. Its alpha (a
-- return over the same bars) and its r² (a share of variance) are percents and
-- are deliberately not touched.
UPDATE calc_ledger
   SET unit_class = 'MULTIPLE',
       params = jsonb_set(params, '{result_type,unit_class}', '"multiple"')
 WHERE unit_class = 'RATIO'
   AND operation = 'price.regress.beta';

COMMIT;
