# Fabric Lakehouse Migration — Open Items

Tracked separately from the README because these are unresolved questions
about the data model, not settled setup steps. The app currently runs on
`DATA_SOURCE=mock` — none of these block local development or demos.

Resolve an item, then update `data/loader.py` accordingly and delete that
section here.

## 1. `manuf_name` → "Brand" mapping is a guess

`_LAKEHOUSE_COLUMN_MAP` in `data/loader.py` maps the lakehouse column
`manuf_name` to the app's internal `manufacturer_number`, which `core/lookup.py`
labels **"Brand"** in the UI. That mapping is a positional guess — `manuf_name`
sits in the same slot the old Redshift column `manufacturer_number` occupied,
but the name itself suggests it might actually be a readable manufacturer
*name*, which would fit better under **"Company"** (currently fed by
`manuf_code`).

**To resolve:** pull a few real rows from `[Silver_Lake].[infor].[contract_line]`
and check what `manuf_name` actually contains — a brand/product line (e.g.
"Biogel") supports the current mapping; a company name (e.g. "Mölnlycke
Health Care") means it should swap with `manuf_code`. Update
`_LAKEHOUSE_COLUMN_MAP` accordingly.

## 2. No lakehouse column for `low_uom_code_gtin`

The old Redshift query selected a second GTIN column, `low_uom_code_gtin`,
which `engine/lookup.py` (`LookupEngine.__init__`) used to alias the
inner-pack/each-level barcode to the same contract line as the case-level
barcode — a worker could scan either the box or an individual unit inside it
and both resolved correctly.

The new query has no equivalent column. **Inner-pack barcode scans will
silently show "Not Found"** — this is a real feature regression, not a
cosmetic gap, and won't surface until someone actually scans an each-level
barcode.

**To resolve:** find out whether Infor tracks a separate each-level GTIN
anywhere under `[Silver_Lake].[infor]` (possibly a different table/view). If
one exists, add it to the `SELECT` list in `_SQL_TEMPLATE` and rename it back
to `low_uom_code_gtin` in `_LAKEHOUSE_COLUMN_MAP` — `engine/lookup.py` needs
no other changes to pick it back up.

## 3. Active-line filter (`WHERE contract_line_state = 2`) was dropped

The old Redshift query filtered to `contract_line_state = 2` (active lines
only). `[Silver_Lake].[infor].[contract_line]` has no obvious equivalent
column, so the current query in `data/loader.py` is **unfiltered** — it
returns every contract line, including whatever the old filter used to
exclude (inactive, historical, or discontinued lines, if that's what state 2
meant).

**To resolve:** confirm with whoever owns the Infor/Fabric data model whether
an equivalent filter is needed, and if so, add a `WHERE` clause to
`_SQL_TEMPLATE` once the right column is identified.
