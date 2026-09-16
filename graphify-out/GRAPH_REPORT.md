# Graph Report - gtin-scanner  (2026-08-18)

## Corpus Check
- 30 files · ~33,536 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 313 nodes · 494 edges · 12 communities (10 shown, 2 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS · INFERRED: 1 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2713c6c9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- core/lookup.py
- store.py
- components.py
- app.py
- GTIN Barcode Scanner
- loader.py
- board.py
- GTIN Scanner — Handheld + Monitor Two-Surface Plan
- LookupEngine
- CLAUDE.md
- gtin-scanner
- build

## God Nodes (most connected - your core abstractions)
1. `LookupEngine` - 15 edges
2. `_cursor()` - 13 edges
3. `GTIN Scanner — Handheld + Monitor Two-Surface Plan` - 13 edges
4. `get_lookup_engine()` - 11 edges
5. `GTIN Barcode Scanner` - 11 edges
6. `resolve_scan()` - 9 edges
7. `_load_from_lakehouse()` - 9 edges
8. `normalize()` - 9 edges
9. `_utcnow()` - 8 edges
10. `_row()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `_get_engine_lazy()` --calls--> `get_lookup_engine()`  [EXTRACTED]
  app.py → core/lookup.py
- `get_lookup_engine()` --calls--> `load_contract_data()`  [EXTRACTED]
  core/lookup.py → data/loader.py
- `get_lookup_engine()` --references--> `LookupEngine`  [EXTRACTED]
  core/lookup.py → engine/lookup.py
- `resolve_scan()` --references--> `LookupEngine`  [EXTRACTED]
  core/lookup.py → engine/lookup.py
- `resolve_scan()` --calls--> `query_goodid()`  [EXTRACTED]
  core/lookup.py → api/goodid_client.py

## Import Cycles
- None detected.

## Communities (12 total, 2 thin omitted)

### Community 0 - "core/lookup.py"
Cohesion: 0.07
Nodes (40): GoodIDResult, query_goodid(), api/goodid_client.py ~~~~~~~~~~~~~~~~~~~~ HTTP fallback client for the FDA…, Structured result from an AccessGUDID API call. Attributes: success: True if…, Look up a device identifier against the FDA AccessGUDID database. Falls back…, api package — exports the goodID fallback client., _allowed_domains(), _allowed_emails() (+32 more)

### Community 1 - "store.py"
Cohesion: 0.08
Nodes (41): ConnectionPool, _close_pool(), _conninfo(), create_session(), _cursor(), end_session(), find_scan(), force_end_session() (+33 more)

### Community 2 - "components.py"
Cohesion: 0.07
Nodes (39): empty_hero_html(), handheld_history_table_html(), header_html(), history_table_html(), _identity_block_html(), identity_header_html(), _kpi_chip_html(), _logo_data_uri() (+31 more)

### Community 3 - "app.py"
Cohesion: 0.08
Nodes (33): _confirm_end_session(), _get_engine_lazy(), cache_resource, app.py ~~~~~~ GTIN Barcode Scanner — Handheld scan page, Streamlit entry point.…, Gate on the one moment data could be lost for good: forgetting to export before…, clear_result(), compute_stats(), end_session() (+25 more)

### Community 4 - "GTIN Barcode Scanner"
Cohesion: 0.07
Nodes (28): Fabric Lakehouse Migration — Open Items, Resolved, Still open, 1. Clone / open the project, 1. Fill in `.streamlit/secrets.toml`, 1. Install the Microsoft ODBC driver (system-level), 2. Create and activate a virtual environment, 2. Install the Python driver (+20 more)

### Community 5 - "loader.py"
Cohesion: 0.09
Nodes (32): data package — exports the public data-loading interface., _coerce_bool(), _contract_line_query(), _fabric_access_token(), _fabric_connection_string(), _fabric_credential(), _fetch_fresh_data(), load_contract_data() (+24 more)

### Community 6 - "board.py"
Cohesion: 0.13
Nodes (16): build_workbook(), export_filename(), _filename_part(), core/export.py ~~~~~~~~~~~~~~ Excel session export. One workbook per session,…, Sanitise a value for use inside the export filename. Location and Sanford ID…, Build a collision-resistant filename for one session's export. `created_at` is…, Serialise a session's scan history to an .xlsx byte string. `location`,…, pages/board.py ~~~~~~~~~~~~~~ Monitor master board — the passive, wide-layout… (+8 more)

### Community 7 - "GTIN Scanner — Handheld + Monitor Two-Surface Plan"
Cohesion: 0.14
Nodes (13): Build order (as shipped), Code change map, Core model, Data model — Postgres (Neon), replacing the SQLite plan below, Device onboarding (once per handheld, not per session), Duplicate handling → Scan Count (not drop, not a separate row), Explicitly deferred (deliberate, not forgotten), Export (+5 more)

### Community 8 - "LookupEngine"
Cohesion: 0.08
Nodes (29): check_digit(), check_digit_valid(), core(), describe_indicator(), indicator(), is_digits(), normalize(), engine/gtin.py ~~~~~~~~~~~~~~ Pure GTIN arithmetic. No pandas, no Streamlit, no… (+21 more)

### Community 11 - "build"
Cohesion: 0.33
Nodes (6): build(), main(), DataFrame, Path, scripts/build_mock_dataset.py ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Turn a raw Fabric…, Read a raw lakehouse export and write it as the canonical mock dataset.

## Knowledge Gaps
- **36 isolated node(s):** `gtin-scanner`, `graphify`, `Resolved`, `Still open`, `Core model` (+31 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LookupEngine` connect `LookupEngine` to `core/lookup.py`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `get_lookup_engine()` connect `core/lookup.py` to `LookupEngine`, `app.py`, `loader.py`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `load_contract_data()` connect `loader.py` to `core/lookup.py`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **What connects `gtin-scanner`, `graphify`, `Resolved` to the rest of the system?**
  _36 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `core/lookup.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07053140096618357 - nodes in this community are weakly interconnected._
- **Should `store.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07897793263646923 - nodes in this community are weakly interconnected._
- **Should `components.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07179487179487179 - nodes in this community are weakly interconnected._