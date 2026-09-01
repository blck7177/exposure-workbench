-- V15-S4. portfolio.window_return rows carry their unit (RATIO) from now on
-- (drawdown_service passes unit_class); the rows written before that line
-- had neither unit_class nor params.result_type, and the transitional
-- operation-name table never listed the op, so the gate typed them MONEY and a
-- written "-11.95%" could not meet the -0.1195 the row holds. Backfill the
-- unit the writer always meant. Idempotent: only NULLs are touched.
UPDATE calc_ledger
   SET unit_class = 'RATIO'
 WHERE operation = 'portfolio.window_return'
   AND unit_class IS NULL;
