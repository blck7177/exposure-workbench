-- V23: the turn budget is charged per assistant message, not per tool call.
-- The last message charged is carried on the session row (see init.sql).
-- Additive and idempotent.
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS charged_message_id VARCHAR(64);
