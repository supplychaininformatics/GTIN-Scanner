# Graph Report - gtin-scanner  (2026-09-15)

## Corpus Check
- 63 files · ~55,613 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 655 nodes · 1153 edges · 31 communities (29 shown, 2 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 7 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9c980964`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- core/admin.py
- store.py
- components.py
- session.py
- GTIN Barcode Scanner
- _load_mock_from_excel
- app.py
- GTIN Scanner — Handheld + Monitor Two-Surface Plan
- test_gtin_validation.py
- CLAUDE.md
- gtin-scanner
- build
- offline_queue.py
- CircuitBreaker
- ASVS Security Audit — GTIN Barcode Scanner
- _conninfo
- test_egress.py
- from_keyring
- test_contract_cache.py
- test_usage_stats.py
- _load_from_lakehouse
- safe_log_value
- loader.py
- _row
- rollup_day
- history_for_session
- load_contract_data
- record_duplicate_scan
- _no_real_keyring

## God Nodes (most connected - your core abstractions)
1. `CircuitBreaker` - 23 edges
2. `enqueue()` - 22 edges
3. `_cursor()` - 19 edges
4. `flush()` - 18 edges
5. `pending_count()` - 17 edges
6. `LookupEngine` - 17 edges
7. `query_goodid()` - 15 edges
8. `safe_log_value()` - 15 edges
9. `resolve_scan()` - 14 edges
10. `_load_from_lakehouse()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `GoodIDResult` --uses--> `CircuitBreaker`  [INFERRED]
  api/goodid_client.py → core/circuit_breaker.py
- `GoodIDResult` --uses--> `CircuitOpenError`  [INFERRED]
  api/goodid_client.py → core/circuit_breaker.py
- `query_goodid()` --calls--> `assert_allowed_url()`  [EXTRACTED]
  api/goodid_client.py → core/egress.py
- `query_goodid()` --calls--> `safe_log_value()`  [EXTRACTED]
  api/goodid_client.py → core/logsafe.py
- `query_goodid()` --calls--> `record_goodid_lookup()`  [EXTRACTED]
  api/goodid_client.py → core/usage_stats.py

## Import Cycles
- None detected.

## Communities (31 total, 2 thin omitted)

### Community 0 - "core/admin.py"
Cohesion: 0.08
Nodes (43): _allowed_domains(), _allowed_emails(), cooldown_remaining(), is_admin(), log_audit_event(), _log_key(), core/admin.py ~~~~~~~~~~~~~ Admin-only data refresh: a typed-email allowlist…, Decrypt and parse `path`, or return `default` on any failure (missing file,… (+35 more)

### Community 1 - "store.py"
Cohesion: 0.11
Nodes (29): create_session(), _cursor(), end_session(), force_end_session(), _iso(), new_session_id(), purge_old_sessions(), core/store.py ~~~~~~~~~~~~~ Postgres-backed persistence for scan sessions,… (+21 more)

### Community 2 - "components.py"
Cohesion: 0.07
Nodes (39): empty_hero_html(), handheld_history_table_html(), header_html(), history_table_html(), _identity_block_html(), identity_header_html(), _kpi_chip_html(), _logo_data_uri() (+31 more)

### Community 3 - "session.py"
Cohesion: 0.13
Nodes (19): core package — scan orchestration, session model, export., extract_gtin(), core/lookup.py ~~~~~~~~~~~~~~ Scan orchestration. This module holds the…, Extract a 14-digit GTIN from a composite GS1 barcode., compute_stats(), _entry_from_result(), init_session(), _maybe_purge() (+11 more)

### Community 4 - "GTIN Barcode Scanner"
Cohesion: 0.06
Nodes (33): Fabric Lakehouse Migration — Open Items, Resolved, Still open, 1. Clone / open the project, 1. Fill in `.streamlit/secrets.toml`, 1. Install the Microsoft ODBC driver (system-level), 2. Create and activate a virtual environment, 2. Install the Python driver (+25 more)

### Community 5 - "_load_mock_from_excel"
Cohesion: 0.18
Nodes (13): _coerce_bool(), _fetch_fresh_data(), _load_mock_data_fallback(), _load_mock_from_excel(), DataFrame, Path, Coerce a boolean-ish column to real bools, treating NULL/blank as False.…, Load a representative sample from the real contract_line.xlsx dataset. Mirrors… (+5 more)

### Community 6 - "app.py"
Cohesion: 0.08
Nodes (33): _get_engine_lazy(), cache_resource, app.py ~~~~~~ GTIN Barcode Scanner — Handheld scan page, Streamlit entry point.…, build_workbook(), export_filename(), _filename_part(), _neutralize_formula(), core/export.py ~~~~~~~~~~~~~~ Excel session export. One workbook per session,… (+25 more)

### Community 7 - "GTIN Scanner — Handheld + Monitor Two-Surface Plan"
Cohesion: 0.14
Nodes (13): Build order (as shipped), Code change map, Core model, Data model — Postgres (Neon), replacing the SQLite plan below, Device onboarding (once per handheld, not per session), Duplicate handling → Scan Count (not drop, not a separate row), Explicitly deferred (deliberate, not forgotten), Export (+5 more)

### Community 8 - "test_gtin_validation.py"
Cohesion: 0.06
Nodes (48): _field(), _field_any(), Resolve a single scanned GTIN: local cache first, goodID API as fallback. Args:…, Pull a display field from a contract-line record. `record` is a DataFrame row's…, First of `keys` that has a real value, else "-". Exists for fields whose source…, resolve_scan(), check_digit(), check_digit_valid() (+40 more)

### Community 11 - "build"
Cohesion: 0.33
Nodes (6): build(), main(), DataFrame, Path, scripts/build_mock_dataset.py ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Turn a raw Fabric…, Read a raw lakehouse export and write it as the canonical mock dataset.

### Community 12 - "offline_queue.py"
Cohesion: 0.06
Nodes (64): _confirm_end_session(), Gate on the one moment data could be lost for good: forgetting to export before…, BaseException, is_connectivity_error(), core/connectivity.py ~~~~~~~~~~~~~~~~~~~~~ Classifies whether an exception from…, True if `exc` represents a failure to reach/use the connection itself (DNS…, _checksum(), enqueue() (+56 more)

### Community 13 - "CircuitBreaker"
Cohesion: 0.07
Nodes (34): _get_breaker(), GoodIDResult, query_goodid(), api/goodid_client.py ~~~~~~~~~~~~~~~~~~~~ HTTP fallback client for the FDA…, The module-level circuit breaker, created on first use. Deferred…, Structured result from an AccessGUDID API call. Attributes: success: True if…, Look up a device identifier against the FDA AccessGUDID database. Falls back…, api package — exports the goodID fallback client. (+26 more)

### Community 14 - "ASVS Security Audit — GTIN Barcode Scanner"
Cohesion: 0.05
Nodes (38): 1.1 GUDID (FDA AccessGUDID) — `api/goodid_client.py`, 1.2 Microsoft Fabric Lakehouse — `data/loader.py`, 1.3 Neon Postgres — `core/store.py`, 1. Network calls — TLS, timeouts, retries, 2. Credentials and secrets, 3. Scanned barcode input — validation and injection surface, 4.1 Contract-line reference data — `data/loader.py`, 4.2 Scan session data — `core/store.py` / `core/session.py` (+30 more)

### Community 15 - "_conninfo"
Cohesion: 0.08
Nodes (26): ConnectionPool, _close_pool(), _conninfo(), _get_pool(), The Neon connection string: env var, then OS keychain, then Streamlit secrets —…, The process-wide connection pool, created on first use. A module-level pool is…, Close the pool and let the next call build a fresh one. Registered with atexit;…, parametrize (+18 more)

### Community 16 - "test_egress.py"
Cohesion: 0.12
Nodes (23): allowed_hosts(), assert_allowed_host(), assert_allowed_url(), EgressBlocked, _fabric_host(), _neon_host(), RuntimeError, core/egress.py ~~~~~~~~~~~~~~~ Application-level egress allowlist. This is a… (+15 more)

### Community 17 - "from_keyring"
Cohesion: 0.13
Nodes (15): from_keyring(), core/secrets.py ~~~~~~~~~~~~~~~ Layered secret lookup, preferring the strongest…, The keychain-stored value for `key`, or None if unavailable. Every failure mode…, Write `value` into the OS keychain under SERVICE_NAME/key. Not called by the…, store_in_keyring(), main(), fake_keyring(), _FakeKeyring (+7 more)

### Community 18 - "test_contract_cache.py"
Cohesion: 0.20
Nodes (17): _cache_key(), Fernet key for the on-disk contract-data cache. Same pattern as…, Encrypt `df` (as Parquet) and write it to CACHE_PATH., Decrypt and return the cached DataFrame, or None if it's missing, unreadable,…, _read_cache(), _write_cache(), DataFrame, Tests for the contract-data cache's at-rest encryption and hard expiry ceiling… (+9 more)

### Community 19 - "test_usage_stats.py"
Cohesion: 0.16
Nodes (16): classify_anomaly(), Classify `today` against `history` (oldest-first daily counts, not including…, Log one AccessGUDID fallback call. Called from api.goodid_client at every…, record_goodid_lookup(), Tests for core.usage_stats: the anomaly classifier (pure, no DB) and…, A scan must never fail because this logging call couldn't reach Neon — see the…, End-to-end: query_goodid() must still return a normal result even if…, test_goodid_client_lookup_failure_never_raises_even_if_logging_is_broken() (+8 more)

### Community 20 - "_load_from_lakehouse"
Cohesion: 0.16
Nodes (14): _contract_line_query(), _fabric_connection_string(), _load_from_lakehouse(), Build the contract line query against the configured lakehouse table., Assemble the ODBC connection string for the Fabric SQL analytics endpoint.…, Pull active contract lines from the Fabric Lakehouse gold layer. Connects to…, _fabric_env(), fixture (+6 more)

### Community 21 - "safe_log_value"
Cohesion: 0.29
Nodes (9): core/logsafe.py ~~~~~~~~~~~~~~~~ Sanitizes attacker-controlled strings — a…, A version of `value` safe to interpolate into a log message., safe_log_value(), Tests for core.logsafe (ASVS-AUDIT.md item 7 — no log injection via a crafted…, test_long_value_is_truncated(), test_newlines_and_control_chars_are_stripped(), test_non_string_values_are_stringified(), test_none_becomes_empty_string() (+1 more)

### Community 22 - "loader.py"
Cohesion: 0.29
Nodes (9): _fabric_access_token(), _fabric_credential(), data/loader.py ~~~~~~~~~~~~~~ Responsible for loading and caching the supply…, The stored AuthenticationRecord, or None if there isn't a usable one. A missing…, Persist the AuthenticationRecord so the next run can reuse the cache., Build the azure-identity credential named by FABRIC_AUTH. Sign-in is done here…, Acquire an Azure AD token, packed in the layout the ODBC driver expects. The…, _read_auth_record() (+1 more)

### Community 23 - "_row"
Cohesion: 0.25
Nodes (8): find_scan(), get_session(), list_sessions(), One result row with its timestamp columns converted to ISO strings., Return the session row as a dict, or None if it doesn't exist., Sessions newest-first, each annotated with scan_count/last_scanned. Args:…, This session's existing scan row for `gtin`, if any — the dedupe check., _row()

### Community 24 - "rollup_day"
Cohesion: 0.32
Nodes (7): date, Compute and upsert `day`'s row in daily_usage_stats from the raw…, rollup_day(), main(), date, scripts/rollup_daily_stats.py ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Compute…, _target_day()

### Community 25 - "history_for_session"
Cohesion: 0.33
Nodes (6): history_for_session(), This session's full scan history in the UI/export-facing shape (see…, Rehydrate session state from a store row found via the URL's `sid`., resume_session(), list_scans(), This session's scans, oldest-first (matches the old JSON history order).

### Community 26 - "load_contract_data"
Cohesion: 0.40
Nodes (4): data package — exports the public data-loading interface., load_contract_data(), cache_data, Load contract line data, preferring a local encrypted cache over a live query.…

### Community 27 - "record_duplicate_scan"
Cohesion: 0.50
Nodes (4): Re-show an already-scanned item: increment its Scan Count in the store, update…, record_duplicate_scan(), increment_scan(), Rescan of a GTIN already in this session: bump scan_count, refresh…

### Community 28 - "_no_real_keyring"
Cohesion: 0.50
Nodes (4): _isolated_cache(), _no_real_keyring(), fixture, Force the local-key-file fallback path so these tests never touch the real OS…

## Knowledge Gaps
- **72 isolated node(s):** `gtin-scanner`, `Severity key`, `Summary table`, `1.1 GUDID (FDA AccessGUDID) — `api/goodid_client.py``, `1.2 Microsoft Fabric Lakehouse — `data/loader.py`` (+67 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CircuitBreaker` connect `CircuitBreaker` to `_load_from_lakehouse`, `loader.py`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Why does `LookupEngine` connect `test_gtin_validation.py` to `core/admin.py`, `session.py`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `query_goodid()` connect `CircuitBreaker` to `session.py`, `test_gtin_validation.py`, `test_egress.py`, `test_usage_stats.py`, `safe_log_value`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **What connects `gtin-scanner`, `Severity key`, `Summary table` to the rest of the system?**
  _72 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `core/admin.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07624113475177305 - nodes in this community are weakly interconnected._
- **Should `store.py` be split into smaller, more focused modules?**
  _Cohesion score 0.1053763440860215 - nodes in this community are weakly interconnected._
- **Should `components.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07179487179487179 - nodes in this community are weakly interconnected._