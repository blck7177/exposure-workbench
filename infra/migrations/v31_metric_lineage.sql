-- V31: supersession between two metric lines, derived from the filings themselves.
--
-- NVDA's `revenue` line stops 2022-01-30 and `total_revenues` continues to
-- 2026-07-26; over the year both were filed the values agree to the dollar
-- (26,914,000,000 under each tag). That relation was recorded only in
-- analytics/formulas.Formula.alternatives, readable only by evaluate_formula, so
-- the catalogue drew a map with no per-metric coverage and get_flow settled "the
-- latest twelve months" on a line four years dead.
--
-- One row per (issuer, retired line, continuing line). Nothing here is authored:
-- every column is computed by services/lineage_service.derive from the facts
-- table, and `agrees` is the evidence, not an opinion. A pair whose overlap
-- disagrees (or never overlapped) still gets a row with agrees = FALSE, so the
-- desk can say why it will not follow it.
--
-- Additive and idempotent. Rederived per issuer at the end of ingest and over
-- the corpus by scripts/derive_lineage.py.
CREATE TABLE IF NOT EXISTS metric_lineage (
    company_id            VARCHAR(64)  NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    from_metric           VARCHAR(64)  NOT NULL,   -- the line that stopped
    to_metric             VARCHAR(64)  NOT NULL,   -- the line that continues
    from_last_period_end  DATE         NOT NULL,
    to_last_period_end    DATE         NOT NULL,
    switched_at           DATE,                    -- first to_metric period_end after from's last
    overlap_periods       INTEGER      NOT NULL DEFAULT 0,
    overlap_max_rel_diff  DOUBLE PRECISION,        -- NULL when there is no overlap
    agrees                BOOLEAN      NOT NULL DEFAULT FALSE,
    mapping_version       VARCHAR(16),
    derived_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (company_id, from_metric, to_metric)
);

CREATE INDEX IF NOT EXISTS ix_metric_lineage_lookup
    ON metric_lineage (company_id, from_metric) WHERE agrees;

-- Reference data about issuers, like companies and financial_facts: readable by
-- every tenant, written by the owner role only. No RLS policy, mirroring
-- financial_facts.

-- V31 §8 B1: a brief's claims beside its blocks. `blocks` says which fact filled
-- which slot; this says what the sentence asserted of it — a level, a change, a
-- room to a tier — which is what makes a brief's figure traceable to the program
-- node that produced it rather than only to an id. NULL on briefs written before
-- V31; nothing reads it for those.
ALTER TABLE issuer_briefs ADD COLUMN IF NOT EXISTS claims_by_section JSONB;
