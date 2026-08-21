-- V4 cost migration — idempotent DDL applied to a LIVE database.
-- Safe to re-run: every statement here is IF EXISTS or CREATE OR REPLACE.
--
-- Apply (BEFORE restarting the API — the ORM no longer declares the three
-- columns dropped below, and the views are what any cost question is asked of):
--   docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
--     -v ON_ERROR_STOP=1 < infra/migrations/v4_cost.sql
--
-- This project has no alembic (see MODULE_NOTES M14 "明确不做"); this file,
-- v2_multiuser.sql and v3_harness.sql are the migration truth. Every file must
-- be named in docs/PRODUCTION.md (enforced by tests/test_deploy_config.py).
--
-- V4-S2 is "the only action that spends money leaves a row". Both agent loops
-- discarded the completion's usage in place, so agent_steps.prompt_tokens and
-- completion_tokens had a schema and a record_step parameter and no writer at
-- all. agents/llm_session.py is the writer; this file is the reader — and the
-- deletion of three columns that never had either.

-- ═══ S2: the three dead cost columns on issuer_briefs ════════════════════════
-- Written by nothing, ever (measured 2026-08-08: 4 briefs, count(llm_model)=0),
-- and read by nothing in apps/ or services/. They are a fossil of the v2 shape
-- where one artifact was one completion — which daily_reports still is, and
-- which is why THAT table's identical columns are alive and stay. A brief is
-- what a 30-turn research session ends with, so "the brief's token count" was
-- never a number these columns could hold.
--
-- Dropped rather than backfilled: the session's llm_call rows are the real
-- accounting and llm_cost_by_research_run below reaches them through
-- research_runs.agent_session_id. Two places holding one number, one of them
-- permanently empty, is how a dashboard ends up disagreeing with itself.
ALTER TABLE issuer_briefs DROP COLUMN IF EXISTS llm_model;
ALTER TABLE issuer_briefs DROP COLUMN IF EXISTS prompt_tokens;
ALTER TABLE issuer_briefs DROP COLUMN IF EXISTS completion_tokens;

-- ═══ S2: token accounting, as views ══════════════════════════════════════════
-- Views and not tables. The account is complete because the ROWS are complete —
-- agent_steps is append-only and llm_session writes one row per completion on
-- the only path the agents layer has to the provider — so a summary table would
-- be a second copy that can disagree with its source, plus a job to keep it
-- fresh. A dashboard should be thin.
--
-- V2-E0: security_invoker on every one of them. Without it a view runs with its
-- DEFINER's privileges (the owner role, which bypasses RLS) and app_rls would
-- read straight through the tenant policies — measured on the live DB when
-- session_cost shipped without it. So under the app role these answer "what did
-- I spend"; an operator asking "what did everyone spend" connects as the owner
-- role, where RLS does not apply.

-- What did this session cost? One row per session, including the ones that never
-- reached the provider.
--
-- The step_type filter is in the JOIN and not in a WHERE: a session that opened,
-- did nothing and was abandoned is a real session that cost zero, and a WHERE
-- would delete it from the answer instead of reporting the zero.
--
-- session_llm_model is the ALIAS the session was opened with (settings.
-- openai_model), not the version the provider served. The served version is in
-- each step's result_summary, because agent_steps has no column for it and S2
-- deliberately added none; the alias is named for what it is so nobody reads it
-- as an answer to "which model charged this".
CREATE OR REPLACE VIEW llm_cost_by_session WITH (security_invoker = true) AS
SELECT s.id                                    AS session_id,
       s.kind,
       s.owner_id,
       s.llm_model                             AS session_llm_model,
       count(st.id)                            AS llm_calls,
       coalesce(sum(st.prompt_tokens), 0)      AS prompt_tokens,
       coalesce(sum(st.completion_tokens), 0)  AS completion_tokens,
       min(st.created_at)                      AS first_call_at,
       max(st.created_at)                      AS last_call_at
FROM agent_sessions s
LEFT JOIN agent_steps st
       ON st.session_id = s.id AND st.step_type = 'llm_call'
GROUP BY s.id;

-- What did this research run cost? A run reaches its completions only through
-- research_runs.agent_session_id — the brief itself carries no cost, which is
-- exactly what the three dropped columns above were pretending otherwise.
--
-- coalesce to zero, not NULL: a run that failed before opening a session spent
-- nothing, and that is a fact, not a missing value. A dashboard printing an
-- empty cell there would be reporting ignorance it does not have.
CREATE OR REPLACE VIEW llm_cost_by_research_run WITH (security_invoker = true) AS
SELECT r.id                            AS research_run_id,
       r.company_id,
       r.owner_id,
       r.status,
       r.agent_session_id,
       coalesce(c.llm_calls, 0)        AS llm_calls,
       coalesce(c.prompt_tokens, 0)    AS prompt_tokens,
       coalesce(c.completion_tokens, 0) AS completion_tokens
FROM research_runs r
LEFT JOIN llm_cost_by_session c ON c.session_id = r.agent_session_id;

-- What is a user spending per day, and is it going up? Chat turns and research
-- runs together, because they come out of the same account.
--
-- UTC, matching usage_daily's day (usage_service.today_utc). A cost report on a
-- local-time day beside a quota on a UTC day is two numbers that disagree for
-- an hour every night and nobody can say why.
--
-- No coalesce here, unlike the view above: every row counted has a completion
-- behind it, so a NULL sum would mean llm_call rows exist with no token counts —
-- a real anomaly, and reporting it as 0 would hide the one thing worth seeing.
CREATE OR REPLACE VIEW llm_cost_by_user_day WITH (security_invoker = true) AS
SELECT s.owner_id                                  AS user_id,
       (st.created_at AT TIME ZONE 'UTC')::date    AS utc_day,
       count(DISTINCT s.id)                        AS sessions,
       count(*)                                    AS llm_calls,
       sum(st.prompt_tokens)                       AS prompt_tokens,
       sum(st.completion_tokens)                   AS completion_tokens
FROM agent_steps st
JOIN agent_sessions s ON s.id = st.session_id
WHERE st.step_type = 'llm_call'
GROUP BY s.owner_id, (st.created_at AT TIME ZONE 'UTC')::date;
