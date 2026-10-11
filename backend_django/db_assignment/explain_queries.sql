-- Hermes Trading: three queries the app runs, with EXPLAIN ANALYZE.
-- Run with:  psql -h localhost -U postgres -d hermes_trading -f explain_queries.sql > explain_output.txt
-- (Docker:   docker exec -i hermes_postgres psql -U postgres -d hermes_trading < explain_queries.sql > explain_output.txt)
-- In pgAdmin: replace :uid with the number printed by the first SELECT and run each block.

SELECT id AS uid FROM trading_user WHERE email = 'seed_user_01@hermes.test' \gset
\echo 'Using user id' :uid

\echo '\n=== Q1: Portfolio performance chart, last 30 days (views.py portfolio_history) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT "timestamp", total_value, cash_balance, holdings_value
FROM portfolio_snapshot
WHERE user_id = :uid
  AND "timestamp" >= now() - interval '30 days'
ORDER BY "timestamp";

\echo '\n=== Q2: Unread signal badge count, polled every 60s (views.py unread_count) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM trading_signal
WHERE user_id = :uid
  AND is_read = false
  AND is_active = true;

\echo '\n=== Q3: Screener liquidity ranking, last 30 trading days across all tickers (price_bar) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT symbol,
       avg(close * volume)              AS avg_dollar_volume,
       max(high)                        AS high_30d,
       min(low)                         AS low_30d,
       count(*)                         AS days
FROM price_bar
WHERE date >= (SELECT max(date) FROM price_bar) - 30
GROUP BY symbol
ORDER BY avg_dollar_volume DESC
LIMIT 20;
