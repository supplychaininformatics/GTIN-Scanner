# Graph Report - gtin-scanner  (2026-09-14)

## Corpus Check
- 55 files · ~48,228 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 575 nodes · 982 edges · 20 communities (18 shown, 2 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 6 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `798eaf80`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- core/admin.py
- store.py
- components.py
- session.py
- GTIN Barcode Scanner
- loader.py
- board.py
- GTIN Scanner — Handheld + Monitor Two-Surface Plan
- test_gtin_validation.py
- CLAUDE.md
- gtin-scanner
- build
- _conninfo
- enqueue
- CircuitBreaker
- ASVS Security Audit — GTIN Barcode Scanner
- query_goodid
- from_keyring

## God Nodes (most connected - your core abstractions)
1. `CircuitBreaker` - 23 edges
2. `enqueue()` - 19 edges
3. `flush()` - 18 edges
4. `pending_count()` - 17 edges
5. `LookupEngine` - 17 edges
6. `safe_log_value()` - 15 edges
7. `query_goodid()` - 14 edges
8. `resolve_scan()` - 14 edges
9. `_load_from_lakehouse()` - 14 edges
10. `_conninfo()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `GoodIDResult` --uses--> `CircuitBreaker`  [INFERRED]
  api/goodid_client.py → core/circuit_breaker.py
- `GoodIDResult` --uses--> `CircuitOpenError`  [INFERRED]
  api/goodid_client.py → core/circuit_breaker.py
- `_get_breaker()` --calls--> `CircuitBreaker`  [EXTRACTED]
  api/goodid_client.py → core/circuit_breaker.py
- `query_goodid()` --calls--> `assert_allowed_url()`  [EXTRACTED]
  api/goodid_client.py → core/egress.py
- `query_goodid()` --calls--> `safe_log_value()`  [EXTRACTED]
  api/goodid_client.py → core/logsafe.py

## Import Cycles
- None detected.

## Communities (20 total, 2 thin omitted)

### Community 0 - "core/admin.py"
Cohesion: 0.10
Nodes (28): _get_engine_lazy(), cache_resource, _allowed_domains(), _allowed_emails(), cooldown_remaining(), is_admin(), log_audit_event(), core/admin.py ~~~~~~~~~~~~~ Admin-only data refresh: a typed-email allowlist… (+20 more)

### Community 1 - "store.py"
Cohesion: 0.07
Nodes (44): ConnectionPool, _close_pool(), create_session(), _cursor(), end_session(), find_scan(), force_end_session(), _get_pool() (+36 more)

### Community 2 - "components.py"
Cohesion: 0.07
Nodes (39): empty_hero_html(), handheld_history_table_html(), header_html(), history_table_html(), _identity_block_html(), identity_header_html(), _kpi_chip_html(), _logo_data_uri() (+31 more)

### Community 3 - "session.py"
Cohesion: 0.06
Nodes (50): _confirm_end_session(), app.py ~~~~~~ GTIN Barcode Scanner — Handheld scan page, Streamlit entry point.…, Gate on the one moment data could be lost for good: forgetting to export before…, BaseException, is_connectivity_error(), core/connectivity.py ~~~~~~~~~~~~~~~~~~~~~ Classifies whether an exception from…, True if `exc` represents a failure to reach/use the connection itself (DNS…, core package — scan orchestration, session model, export. (+42 more)

### Community 4 - "GTIN Barcode Scanner"
Cohesion: 0.07
Nodes (28): Fabric Lakehouse Migration — Open Items, Resolved, Still open, 1. Clone / open the project, 1. Fill in `.streamlit/secrets.toml`, 1. Install the Microsoft ODBC driver (system-level), 2. Create and activate a virtual environment, 2. Install the Python driver (+20 more)

### Community 5 - "loader.py"
Cohesion: 0.07
Nodes (46): data package — exports the public data-loading interface., _cache_key(), _coerce_bool(), _fabric_access_token(), _fabric_credential(), _fetch_fresh_data(), load_contract_data(), _load_mock_data_fallback() (+38 more)

### Community 6 - "board.py"
Cohesion: 0.10
Nodes (26): build_workbook(), export_filename(), _filename_part(), _neutralize_formula(), core/export.py ~~~~~~~~~~~~~~ Excel session export. One workbook per session,…, Serialise a session's scan history to an .xlsx byte string. `location`,…, Prefix a leading formula-trigger character with `'` so Excel (and openpyxl's…, Sanitise a value for use inside the export filename. Location and Sanford ID… (+18 more)

### Community 7 - "GTIN Scanner — Handheld + Monitor Two-Surface Plan"
Cohesion: 0.14
Nodes (13): Build order (as shipped), Code change map, Core model, Data model — Postgres (Neon), replacing the SQLite plan below, Device onboarding (once per handheld, not per session), Duplicate handling → Scan Count (not drop, not a separate row), Explicitly deferred (deliberate, not forgotten), Export (+5 more)

### Community 8 - "test_gtin_validation.py"
Cohesion: 0.06
Nodes (48): _field(), _field_any(), Resolve a single scanned GTIN: local cache first, goodID API as fallback. Args:…, Pull a display field from a contract-line record. `record` is a DataFrame row's…, First of `keys` that has a real value, else "-". Exists for fields whose source…, resolve_scan(), check_digit(), check_digit_valid() (+40 more)

### Community 11 - "build"
Cohesion: 0.33
Nodes (6): build(), main(), DataFrame, Path, scripts/build_mock_dataset.py ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Turn a raw Fabric…, Read a raw lakehouse export and write it as the canonical mock dataset.

### Community 12 - "_conninfo"
Cohesion: 0.06
Nodes (42): allowed_hosts(), assert_allowed_host(), assert_allowed_url(), EgressBlocked, _fabric_host(), _neon_host(), RuntimeError, core/egress.py ~~~~~~~~~~~~~~~ Application-level egress allowlist. This is a… (+34 more)

### Community 13 - "enqueue"
Cohesion: 0.10
Nodes (39): _checksum(), enqueue(), flush(), _get_or_create_key(), _load(), pending_count(), _prune(), core/offline_queue.py ~~~~~~~~~~~~~~~~~~~~~ Server-side write buffer for a… (+31 more)

### Community 14 - "CircuitBreaker"
Cohesion: 0.08
Nodes (27): CircuitBreaker, CircuitOpenError, RuntimeError, core/circuit_breaker.py ~~~~~~~~~~~~~~~~~~~~~~~~ A minimal, in-process circuit…, Raised by before_call() instead of letting a call through while the breaker is…, Opens after `failure_threshold` consecutive failures and refuses calls…, Raise CircuitOpenError if the breaker is currently open., _contract_line_query() (+19 more)

### Community 15 - "ASVS Security Audit — GTIN Barcode Scanner"
Cohesion: 0.06
Nodes (32): 1.1 GUDID (FDA AccessGUDID) — `api/goodid_client.py`, 1.2 Microsoft Fabric Lakehouse — `data/loader.py`, 1.3 Neon Postgres — `core/store.py`, 1. Network calls — TLS, timeouts, retries, 2. Credentials and secrets, 3. Scanned barcode input — validation and injection surface, 4.1 Contract-line reference data — `data/loader.py`, 4.2 Scan session data — `core/store.py` / `core/session.py` (+24 more)

### Community 16 - "query_goodid"
Cohesion: 0.13
Nodes (19): _get_breaker(), GoodIDResult, query_goodid(), api/goodid_client.py ~~~~~~~~~~~~~~~~~~~~ HTTP fallback client for the FDA…, The module-level circuit breaker, created on first use. Deferred…, Structured result from an AccessGUDID API call. Attributes: success: True if…, Look up a device identifier against the FDA AccessGUDID database. Falls back…, api package — exports the goodID fallback client. (+11 more)

### Community 17 - "from_keyring"
Cohesion: 0.13
Nodes (15): from_keyring(), core/secrets.py ~~~~~~~~~~~~~~~ Layered secret lookup, preferring the strongest…, The keychain-stored value for `key`, or None if unavailable. Every failure mode…, Write `value` into the OS keychain under SERVICE_NAME/key. Not called by the…, store_in_keyring(), main(), fake_keyring(), _FakeKeyring (+7 more)

## Knowledge Gaps
- **63 isolated node(s):** `gtin-scanner`, `Severity key`, `Summary table`, `1.1 GUDID (FDA AccessGUDID) — `api/goodid_client.py``, `1.2 Microsoft Fabric Lakehouse — `data/loader.py`` (+58 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CircuitBreaker` connect `CircuitBreaker` to `query_goodid`, `loader.py`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `LookupEngine` connect `test_gtin_validation.py` to `core/admin.py`, `session.py`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Why does `query_goodid()` connect `query_goodid` to `test_gtin_validation.py`, `session.py`, `_conninfo`?**
  _High betweenness centrality (0.044) - this node is a cross-community bridge._
- **What connects `gtin-scanner`, `Severity key`, `Summary table` to the rest of the system?**
  _63 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `core/admin.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10344827586206896 - nodes in this community are weakly interconnected._
- **Should `store.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07053140096618357 - nodes in this community are weakly interconnected._
- **Should `components.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07179487179487179 - nodes in this community are weakly interconnected._