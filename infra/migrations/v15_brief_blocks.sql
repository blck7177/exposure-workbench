-- V15-S5 — the brief as blocks.
--
-- submit_brief now takes six sections of blocks in the same grammar as
-- `respond`, resolved against the session's table. The text columns keep the
-- prose rendering (figures at reader precision); this column keeps the blocks
-- themselves, every slot carrying the id and the figure it resolved to — which
-- is what the Brief tab renders and what prose cannot carry. Briefs written
-- before V15 stay NULL: their text was the whole submission, and no mapping is
-- reconstructed for them. Idempotent; replayable against a live database.
ALTER TABLE issuer_briefs ADD COLUMN IF NOT EXISTS blocks JSONB;
