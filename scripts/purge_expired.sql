-- scripts/purge_expired.sql
-- ~~~~~~~~~~~~~~~~~~~~~~~~~
-- Delete sessions past the retention window. Scans go with them via the
-- ON DELETE CASCADE on scan.session_id (see migrations/001_initial.sql), so
-- this is one statement rather than the collect-ids-then-delete-both dance
-- core/store.purge_old_sessions has to do against SQLite.
--
-- Run by .github/workflows/purge-expired.yml on a daily cron. Also safe to run
-- by hand:
--
--     psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 -v retention_days=3 \
--       -f scripts/purge_expired.sql
--
-- retention_days must stay in sync with RETENTION_DAYS in core/store.py — they
-- are two independent copies of the same policy, and nothing checks them
-- against each other.

\if :{?retention_days}
\else
\set retention_days 3
\endif

\echo 'Retention window (days):' :retention_days

-- Counted before the delete, because once the sessions are gone the cascade has
-- already taken their scans and there is nothing left to count. Purely for the
-- workflow log — a run that reports 0/0 is a healthy no-op, not a failure.
WITH cutoff AS (
    SELECT now() - (:'retention_days' || ' days')::interval AS ts
)
SELECT
    (SELECT count(*) FROM session
      WHERE created_at <  (SELECT ts FROM cutoff))          AS sessions_expiring,
    (SELECT count(*) FROM scan
      WHERE session_id IN (SELECT session_id FROM session
                            WHERE created_at < (SELECT ts FROM cutoff)))
                                                            AS scans_expiring,
    (SELECT count(*) FROM session
      WHERE created_at >= (SELECT ts FROM cutoff))          AS sessions_retained;

-- Deletes by session.created_at, matching core/store.purge_old_sessions
-- exactly: a session is judged by when it started, not by when it was last
-- scanned into. A session still ACTIVE past the window is purged along with
-- everything else — with STALE_AFTER at 4 hours, a session alive for three
-- days is already an anomaly, but it is worth knowing that this will drop it.
WITH purged AS (
    DELETE FROM session
    WHERE created_at < now() - (:'retention_days' || ' days')::interval
    RETURNING session_id
)
SELECT count(*) AS sessions_purged FROM purged;
