# Fabric Lakehouse Migration — Open Items

The three schema questions that blocked `DATA_SOURCE=fabric` were resolved on
2026-08-07 against the live lakehouse. What remains is listed at the bottom.

## Resolved

**1. `manuf_name` → "Brand" was the wrong column.** The right one is
`manuf_item`, which matches the old Redshift `manufacturer_number` on 100% of
~400k comparable rows (checked against the retained mock dataset).
`manuf_name` is a readable *company* name ("INTUITIVE SURGICAL INC") and is 1:1
with `manuf_code` ("INTU") — 2,103 distinct values each — so it was never a
brand or a part number. `_LAKEHOUSE_COLUMN_MAP` now uses `manuf_item`.

**2. `low_uom_code_gtin` exists as `base_uom_gtin`.** Also a 100% match against
the mock dataset. Added to the query and mapped back, so
`engine.LookupEngine`'s inner-pack alias works again with no change to the
engine. Verified: 5/5 sampled inner-pack barcodes resolve to the correct item.
Present on 21,616 active lines — and some items have *only* an inner-pack
barcode (blank `gtin`), so they were previously unreachable by any scan.

**3. The active-line filter is `WHERE active = 1`.** The lakehouse equivalent
of the old `contract_line_state = 2`. Restores pre-migration behaviour: an
inactive line does not resolve, so scanning a discontinued item reports
"Not Found". Cuts 176,296 rows to 157,658 (10.6% excluded).

**4. "Company" now shows the readable vendor name.** `manuf_name` is mapped to
its own `manufacturer_name` field and feeds Company, so a scan shows
"INTUITIVE SURGICAL INC" rather than "INTU". The mock datasets predate that
column, so `core/lookup.py:_field_any` prefers the name and falls back to
`manufacturer_code` — neither data source special-cases the other.

## Still open

**B. Brand means two different things depending on the source.** The lakehouse
path fills "Brand" from a manufacturer part number (`470179`), while the
AccessGUDID fallback in `core/lookup.py` fills the same field from a real
`brandName`. This mismatch predates the migration; it is now just easier to see.

**C. Deployment auth is unsolved.** `devicecode` needs a human, so it cannot
work on Streamlit Cloud. That needs a service principal — see README →
"Switching to the Fabric Lakehouse" → step 4, and note that `.env` is currently
tracked in git.
