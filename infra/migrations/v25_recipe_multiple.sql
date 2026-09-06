-- V25: the recipe's two liquidity measures are read as multiples, not percents.
--
--     docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
--       -v ON_ERROR_STOP=1 < infra/migrations/v25_recipe_multiple.sql
--
-- WHAT WAS WRONG. A current ratio of 1.28 reached the reader as "128.3%", and
-- cash ÷ long-term debt of 1.02 as "102.2%". Not only on the page:
-- analytics/display_conventions.display is the one rule the server and the
-- client share, so an answer or a brief citing either figure printed a percent
-- too.
--
-- WHY V17 DID NOT ALREADY FIX IT. It did list `current_ratio` — that migration
-- corrected exactly the eight measures analytics/formulas.py declares as
-- multiples. It keyed on `params.result_type.quantity`, which is how a typed
-- calculation names what it produced, and the standard recipe passes no
-- `as_quantity` at all: 61 of this desk's 87 `calc.series.divide` rows carry a
-- null quantity. So the rows V17 was written for were invisible to it, and the
-- eight-measure guard in tests/test_v9_formulas.py went on passing, because the
-- registry was right the whole time. Nothing was ever going to surface this
-- except a reader looking at the number, which is what happened when the
-- issuer page started listing every measure with its latest value beside it.
--
-- HOW THIS ONE FINDS THEM. Through the recipe's own manifest, which names each
-- label's calc_id (services/recipe.OP_MANIFEST) — the only handle these rows
-- have, precisely because they are anonymous. That is a narrower key than V17's
-- and it is the honest one: it corrects rows this recipe produced under these
-- two labels, and nothing else.
--
-- WHAT IT DOES AND DOES NOT DO. It corrects the recorded READING of rows that
-- already exist. No value is touched, no operand, no basis, no input ref, no
-- period: the number each row holds was always right, and what was wrong was
-- the two places saying how to print it. That is why this is an UPDATE on an
-- append-only ledger and stays one — a row whose value changed would be a new
-- row, and there is no such row here.
--
-- Both places, not one. `calc_ledger.unit_class` is what the table and the
-- reader read (services/quantities._calc_unit); the JSONB
-- `params.result_type.unit_class` is what the calculator reads back when the
-- row becomes an operand (services/typed_calculator._resolve). These rows
-- predate the column, so it is NULL on all of them and the JSONB is the one
-- that has been deciding; both are set here, for the reason v15_calc_unit.sql
-- introduced the column — two rules about one fact is the failure mode.
--
-- Idempotent: re-running matches nothing the first run already changed.
--
-- STILL TRUE AFTER THIS, and named so it is not discovered twice: the recipe's
-- series rows record no `result_type.quantity`. It is why V17 missed them, and
-- it is why any future correction has to go through the manifest as this one
-- does. Giving them names changes how the model's table refers to them, which
-- is the agent path and not this batch.

BEGIN;

UPDATE calc_ledger AS c
   SET unit_class = 'MULTIPLE',
       params = jsonb_set(c.params, '{result_type,unit_class}', '"multiple"')
  FROM calc_ledger AS m,
       LATERAL jsonb_each_text(m.result -> 'labels') AS l(label, calc_id)
 WHERE m.operation = 'recipe.manifest'
   AND l.label IN ('current_ratio', 'cash_to_long_term_debt_noncurrent')
   AND c.id = l.calc_id
   AND c.params -> 'result_type' ->> 'unit_class' = 'ratio'
   AND (c.unit_class IS NULL OR c.unit_class = 'RATIO');

COMMIT;
