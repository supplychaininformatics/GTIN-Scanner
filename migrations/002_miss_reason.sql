-- migrations/002_miss_reason.sql
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- Records *why* a scan failed to match a contract line, instead of collapsing
-- every non-match into a single "Not Found". Run against the same Neon branch
-- as 001:
--
--     psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/002_miss_reason.sql
--
-- Idempotent, and safe to run while the app is serving: both columns are
-- nullable with no default, so on Postgres 11+ this is a catalog-only change
-- that neither rewrites the table nor holds a lock long enough to matter.
--
-- Both columns are NULL for a contract hit — there is nothing to explain — so
-- "NULL" and "matched" mean the same thing and the buckets below only ever
-- describe misses.
--
--   bad_gtin      the barcode failed its own check digit, or was not a
--                 GTIN-8/12/13/14. A scanning problem, not a data problem,
--                 which is why it is tested before the contract is consulted.
--   padding       the same identifier IS on contract, stored at a different
--                 digit width (the file mixes 12/13/14). A normalisation bug
--                 in the lookup, fixable in code.
--   packaging     a GTIN sharing this item's core is on contract at a
--                 different packaging level. Advisory — see engine/gtin.py on
--                 why a core match is evidence and not proof.
--   unknown_item  the vendor prefix is on contract but this item reference is
--                 not. A contract-data gap; belongs with contracting.
--   off_contract  no vendor prefix match at all.
--
-- Deliberately not a CHECK constraint or an enum: the bucket set is expected
-- to be refined once there is real scanning volume to look at, and a text
-- column lets that happen without a second migration + deploy ordering
-- problem. engine/lookup.py's MISS_* constants are the authority.

BEGIN;

ALTER TABLE scan ADD COLUMN IF NOT EXISTS miss_reason text;
ALTER TABLE scan ADD COLUMN IF NOT EXISTS miss_detail text;

-- Serves the question this whole change exists to answer: "over the last N
-- days, how do the miss buckets break down?" Partial, because contract hits
-- are the overwhelming majority of rows and all of them are NULL here.
CREATE INDEX IF NOT EXISTS idx_scan_miss_reason
    ON scan (miss_reason)
    WHERE miss_reason IS NOT NULL;

COMMIT;

-- The histogram that decides whether the packaging-level UI is worth building:
--
--   SELECT miss_reason, count(*) AS scans, count(DISTINCT gtin) AS items
--   FROM scan
--   WHERE miss_reason IS NOT NULL
--     AND scanned_at >= now() - interval '7 days'
--   GROUP BY miss_reason
--   ORDER BY scans DESC;
--
-- and the specific items behind the packaging bucket:
--
--   SELECT gtin, miss_detail, count(*)
--   FROM scan
--   WHERE miss_reason = 'packaging'
--   GROUP BY gtin, miss_detail
--   ORDER BY count(*) DESC;
