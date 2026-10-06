-- migrations/005_device_api.sql
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- Schema for the handheld sync REST service (sync_api/). Run once:
--
--     psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/005_device_api.sql
--
-- Idempotent (IF NOT EXISTS throughout), so re-running is harmless.
--
--   * session.device_id — which registered device minted a session. NULL for
--     sessions created by the Streamlit app. The API only lets a device
--     modify sessions it owns, so one handheld (or a stolen token) cannot
--     write into another's session or into a Streamlit-created one.
--   * api_device — one row per handheld. Only a SHA-256 of the bearer token
--     is stored, never the token; revoked_at cuts a lost device off.
--   * sync_scan_op — (device, op_id) pairs already applied. A device retries
--     a batch until it hears back, and a rescan increments a counter, which
--     is not naturally idempotent; this table is what makes a re-sent scan a
--     no-op instead of a double count. ON DELETE CASCADE keeps it inside the
--     same retention window as the sessions it refers to.

BEGIN;

ALTER TABLE session ADD COLUMN IF NOT EXISTS device_id text;

CREATE TABLE IF NOT EXISTS api_device (
    device_id     text PRIMARY KEY,
    label         text NOT NULL,
    token_hash    text NOT NULL UNIQUE,
    created_at    timestamptz NOT NULL,
    revoked_at    timestamptz,
    last_seen_at  timestamptz
);

CREATE TABLE IF NOT EXISTS sync_scan_op (
    device_id   text NOT NULL,
    op_id       text NOT NULL,
    session_id  text NOT NULL REFERENCES session (session_id) ON DELETE CASCADE,
    applied_at  timestamptz NOT NULL,
    PRIMARY KEY (device_id, op_id)
);

CREATE INDEX IF NOT EXISTS sync_scan_op_session_idx ON sync_scan_op (session_id);

COMMIT;
