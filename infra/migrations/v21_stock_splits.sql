-- V21: the splits a held name went through, so a stated share count can be
-- carried to the date it is valued on.
--
-- positions.quantity is what the holder stated, as of positions.as_of_date.
-- A run values it at the run date's as-traded close. Between the two dates a
-- 4:1 split leaves the stated count on the old basis and the close on the new
-- one, and the position is valued at a quarter of itself — weights, sector
-- and issuer concentration and every limit check on them follow (V5 §5, the
-- one thing the price convention did not fix). The workflow now carries each
-- count through the splits in (as_of_date, run_date] (analytics/splits.py),
-- and this is where it reads them from.
--
-- Filled by the same provider call that fills market_prices (yfinance's
-- history carries a "Stock Splits" column), on every price sync. Nothing is
-- backfilled here: the next run of each portfolio syncs its holdings' prices
-- and writes their splits on the way through. A run computed before that
-- reads an empty table and carries nothing — which is exactly what it did
-- before this file existed.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS stock_splits (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(16) NOT NULL,
    ex_date         DATE NOT NULL,
    -- new shares per old share: 4.0 for a 4:1 split, 0.1 for a 1:10 reverse
    ratio           NUMERIC(14, 6) NOT NULL,
    source          VARCHAR(32),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, ex_date)
);
