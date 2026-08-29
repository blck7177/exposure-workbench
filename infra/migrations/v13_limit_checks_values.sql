-- V13-S5 — a mandate check records what it SAW, not only that it ran.
--
-- `evaluated` (V8-P3) established that a check happened, which was the fix for a
-- run reporting "all limits within bounds" while three of eight checks had
-- silently not run. This is the next question a reader asks and the page could
-- not answer: twenty-seven checks ran and two raised a warning — where were the
-- other twenty-five? "Inside the limit" and "nowhere near it" are different
-- books, and the numbers to tell them apart were computed on every check and
-- then discarded unless a tier was crossed.
--
-- analytics.limits._check_one has always taken all three values. They are now
-- recorded beside the comparison that decides the alert, so a meter on the page
-- and the alert beneath it cannot come from two different readings of one row.
--
-- NOT BACKFILLED, for the same reason as v6_report_gate, v8_skill_reads and
-- v13_run_errors: a run that did not record what a check saw does not acquire it
-- by being asked later. Recomputing from today's risk_limits rows would be worse
-- than a guess — the thresholds may have been edited since — and would put a
-- number that was never checked under a badge that says it was. NULL reads as
-- "this run did not record it"; the limit-book endpoint says so in those words.
--
-- Additive and idempotent. Safe against the running code, which does not name
-- these columns.

ALTER TABLE limit_checks ADD COLUMN IF NOT EXISTS current_value  NUMERIC(20, 8);
ALTER TABLE limit_checks ADD COLUMN IF NOT EXISTS warning_level  NUMERIC(20, 8);
ALTER TABLE limit_checks ADD COLUMN IF NOT EXISTS breach_level   NUMERIC(20, 8);
ALTER TABLE limit_checks ADD COLUMN IF NOT EXISTS status         VARCHAR(16);

COMMENT ON COLUMN limit_checks.current_value IS
    'what this check measured; NULL = recorded before V13';
COMMENT ON COLUMN limit_checks.status IS
    'ok | warning | breach, decided beside the alert so the two cannot disagree';
