-- Indexes to test for Q2 and Q3. Create, re-run explain_queries.sql, compare, then decide.
-- Remove with the DROP lines at the bottom if they don't help.

-- Q2: only unread + active rows are ever counted, so a small partial index fits.
CREATE INDEX IF NOT EXISTS signal_unread_active_idx
    ON trading_signal (user_id)
    WHERE is_read = false AND is_active = true;

-- Q3: the existing unique index is (symbol, date) - leading column is symbol, so a
-- date-range filter across ALL symbols can't use it efficiently.
CREATE INDEX IF NOT EXISTS price_bar_date_idx ON price_bar (date);

ANALYZE trading_signal;
ANALYZE price_bar;

-- DROP INDEX IF EXISTS signal_unread_active_idx;
-- DROP INDEX IF EXISTS price_bar_date_idx;
