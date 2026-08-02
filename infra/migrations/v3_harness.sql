-- V3 harness migration — idempotent ALTERs applied to a LIVE database.
-- init.sql already carries these for fresh databases; this file brings an
-- existing volume up to the same schema without a rebuild. Safe to re-run.
--
-- Apply (BEFORE restarting the API — every column here is read by V3 code):
--   docker exec -i exposure-postgres psql -U exposure -d exposure_workbench \
--     -v ON_ERROR_STOP=1 < infra/migrations/v3_harness.sql
--
-- This project has no alembic (see MODULE_NOTES M14 "明确不做"); this file and
-- v2_multiuser.sql are the migration truth. One file per major phase; every
-- file must be named in docs/PRODUCTION.md (enforced by tests/test_deploy_config.py).
--
-- Five columns across three tables, deliberately in ONE migration: three V3
-- phases each wanted DDL and two of them wanted the same agent_messages column.

-- ═══ A0-2: the gate-exhaustion marker ════════════════════════════════════════
-- Why a column and not a reused `role`: meta_agent._load_history feeds m.role
-- verbatim into the provider's messages array, so a role the API does not know
-- would break the NEXT turn of any session that ever failed a gate.
ALTER TABLE agent_messages ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}';

-- ═══ B0/B2: context measurement + per-turn tool budget ═══════════════════════
-- last_prompt_tokens is observation only (B0). turn_tools_used is enforcement
-- (B2), zeroed inside the same UPDATE that claims the turn.
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS last_prompt_tokens INTEGER;
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS turn_tools_used    INTEGER NOT NULL DEFAULT 0;

-- The per-turn budget is carried BY THE ROW, not decided by a `kind` branch in
-- reserve(). NULL means "this session has no per-turn budget, use the lifetime
-- one" — which is how research keeps working: a research run spends 25-32 tool
-- calls inside a single session and never claims a turn, so a per-turn counter
-- would never be zeroed and every run would die partway through.
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS turn_tool_budget   INTEGER;

-- Backfill in the SAME section as the ALTER, never as a follow-up script.
-- Existing meta sessions predate the column and would otherwise fall through to
-- lifetime semantics for ever.
UPDATE agent_sessions SET turn_tool_budget = 15 WHERE kind = 'meta' AND turn_tool_budget IS NULL;

-- B2 also changes how a stored tool_budget of 0 is read. `session.tool_budget or
-- settings.session_tool_budget` treats 0 as "unset" and hands back the default;
-- `is not None` makes 0 mean zero, which is what a kill switch has to mean. This
-- sweeps the rows where that flips (test residue on this database, but the
-- distinction is real).
UPDATE agent_sessions SET tool_budget = NULL WHERE tool_budget = 0;

-- ═══ C1: per-block citations on a brief ══════════════════════════════════════
-- issuer_briefs.citations is one flat array, and submit_brief builds it with
-- sorted(set(...)) — which destroys the block association at write time. Briefs
-- written before V3 keep a NULL here; read_issuer_brief reports that as the
-- distinct fact it is rather than inventing a mapping.
ALTER TABLE issuer_briefs ADD COLUMN IF NOT EXISTS block_citations JSONB;

-- ═══ R4: a holding needs an id it can be cited by ════════════════════════════
-- The seed script minted position ids as bare uuid4 — the third time in this
-- project an id has been minted without the prefix that makes it evidence
-- (alert<hex> was the first, and V1 fixed that one row by row). positions.id is
-- referenced by nothing: no foreign key, no stored citation, no cached payload,
-- so rewriting it in place is safe in a way the alert fix was not.
--
-- Idempotent by predicate rather than by guard: rows already carrying the prefix
-- do not match. The hex is taken from the uuid so a re-run of this migration
-- lands on the same id, and 12 characters matches new_id().
UPDATE positions
   SET id = 'pos_' || left(replace(id, '-', ''), 12)
 WHERE id NOT LIKE 'pos\_%';
