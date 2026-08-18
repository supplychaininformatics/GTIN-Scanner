-- migrations/003_no_contract_line.sql
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- Retires the 'unknown_item' and 'off_contract' miss buckets in favour of a
-- single 'no_contract_line'. Run against the same Neon branch as 001/002:
--
--     psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/003_no_contract_line.sql
--
-- RUN THIS BEFORE DEPLOYING the matching app version, not after. The new code
-- drops both old keys from engine.lookup.MISS_LABELS, and core/session.py
-- renders history through that dict — so between a deploy and this migration,
-- old rows would show a blank Miss Reason in the UI and the Excel export.
-- Nothing writes 'no_contract_line' until the new code ships, so running this
-- early is harmless.
--
-- WHY THE OLD BUCKETS WERE WRONG
--
-- They split misses by how many leading digits the scanned GTIN shared with
-- the closest indexed core: >= 8 was labelled "Vendor on contract, item not"
-- and anything less "Vendor not on contract". Two problems, either fatal:
--
--   1. The claim was unsupported. A GS1 company prefix is 6-11 digits and
--      varies per company, so a shared-prefix count is a proxy for vendor
--      identity, never a determination of it. The contract file does carry a
--      real vendor field (manufacturer_code), but on a miss there is no
--      matched row to read it from — vendor identity is precisely what is
--      unknowable at that moment.
--
--   2. "Off contract" is not a thing this app can observe. Everything in the
--      warehouse is on some contract or it could not have been bought. A miss
--      means the barcode is not in the contract file this app loaded, which
--      happens constantly to fully contracted stock: a blank or stale GTIN
--      cell on the source row, a manufacturer re-barcode, a line on a
--      contract outside this load's scope (consignment, bill-only, another
--      tier), or a cache predating the item's addition.
--
-- Both collapse into one bucket because they also had one response: neither
-- was actionable by the person holding the scanner, and both route to
-- contracting. The shared-prefix number survives as evidence inside
-- miss_detail — where it is an observation — and never as a label.

BEGIN;

-- Idempotent: reruns match nothing once the values are gone.
UPDATE scan
   SET miss_reason = 'no_contract_line'
 WHERE miss_reason IN ('unknown_item', 'off_contract');

-- The retired detail strings assert the same thing the labels did, so the
-- claim is stripped while the measurement it was built on is kept. Anchored
-- to the exact formats engine/lookup.py wrote, so any other text is left
-- untouched rather than mangled by a loose pattern.
--
--   'vendor prefix matches 11 digits — item not on contract'
--       -> 'closest on contract shares 11 leading digits'
--   'no vendor prefix match (closest is 3 digits)'
--       -> 'closest on contract shares 3 leading digits'
--
-- Note the em-dash: it is what the application wrote, not a hyphen.
UPDATE scan
   SET miss_detail = regexp_replace(
           miss_detail,
           '^vendor prefix matches (\d+) (digits?) — item not on contract$',
           'closest on contract shares \1 leading \2'
       )
 WHERE miss_detail ~ '^vendor prefix matches \d+ digits? — item not on contract$';

UPDATE scan
   SET miss_detail = regexp_replace(
           miss_detail,
           '^no vendor prefix match \(closest is (\d+) (digits?)\)$',
           'closest on contract shares \1 leading \2'
       )
 WHERE miss_detail ~ '^no vendor prefix match \(closest is \d+ digits?\)$';

COMMIT;

-- Verify: should return zero rows.
--
--   SELECT miss_reason, count(*)
--   FROM scan
--   WHERE miss_reason IN ('unknown_item', 'off_contract')
--   GROUP BY miss_reason;
--
-- and the post-migration bucket histogram:
--
--   SELECT miss_reason, count(*) AS scans, count(DISTINCT gtin) AS items
--   FROM scan
--   WHERE miss_reason IS NOT NULL
--   GROUP BY miss_reason
--   ORDER BY scans DESC;
