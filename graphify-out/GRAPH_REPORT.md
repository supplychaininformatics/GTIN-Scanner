# Graph Report - gtin-scanner  (2026-09-23)

## Corpus Check
- 99 files · ~71,007 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1077 nodes · 2068 edges · 68 communities (61 shown, 7 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 108 edges (avg confidence: 0.75)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `71a3701d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- core/admin.py
- store.py
- components.py
- session.py
- GTIN Barcode Scanner
- loader.py
- test_export_injection.py
- GTIN Scanner — Handheld + Monitor Two-Surface Plan
- test_gtin_validation.py
- CLAUDE.md
- gtin-scanner
- build
- enqueue
- CircuitBreaker
- ASVS Security Audit — GTIN Barcode Scanner
- _get_pool
- _conninfo
- from_keyring
- test_contract_cache.py
- test_usage_stats.py
- _load_from_lakehouse
- safe_log_value
- _fabric_access_token
- Database
- test_sync_api.py
- MainActivity
- InMemoryReferenceStore
- test_offline_session.py
- LookupEngine
- test_offline_resume.py
- SyncEngine
- board.py
- sync_api/__init__.py
- HttpResult
- ReferenceRow
- SyncStatus
- log_audit_event
- engine/lookup.py
- core/lookup.py
- ScanControllerTest
- app.py
- MirrorResult
- .doWork
- InMemoryOpQueue
- .diagnose
- Gs1Test
- ConfigSource
- Fakes.kt
- GTIN Scanner — Android client
- _FakeKeyring
- is_admin
- ._build_diagnostics
- Setup
- Handheld Sync API
- Endpoints
- Fabric Lakehouse Migration — Open Items
- Admin Refresh Page
- Switching to the Fabric Lakehouse
- Usage Dashboard
- gradlew
- Gs1
- _isolated_queue

## God Nodes (most connected - your core abstractions)
1. `_cursor()` - 29 edges
2. `sync()` - 26 edges
3. `CircuitBreaker` - 23 edges
4. `enqueue()` - 22 edges
5. `LookupEngine` - 22 edges
6. `InMemoryReferenceStore` - 21 edges
7. `create_op()` - 21 edges
8. `auth()` - 20 edges
9. `safe_log_value()` - 19 edges
10. `scan_op()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_refresh_meta_file_is_encrypted_at_rest()` --calls--> `_write_refresh_meta()`  [EXTRACTED]
  tests/test_admin_log_encryption.py → core/admin.py
- `create_app()` --indirect_call--> `load_contract_data()`  [INFERRED]
  sync_api/app.py → data/loader.py
- `build_app()` --indirect_call--> `load_contract_data()`  [INFERRED]
  sync_api/dev_server.py → data/loader.py
- `GoodIDResult` --uses--> `CircuitBreaker`  [INFERRED]
  api/goodid_client.py → core/circuit_breaker.py
- `GoodIDResult` --uses--> `CircuitOpenError`  [INFERRED]
  api/goodid_client.py → core/circuit_breaker.py

## Import Cycles
- None detected.

## Communities (68 total, 7 thin omitted)

### Community 0 - "core/admin.py"
Cohesion: 0.16
Nodes (18): cooldown_remaining(), _log_key(), core/admin.py ~~~~~~~~~~~~~ Admin-only data refresh: a typed-email allowlist…, Decrypt and parse `path`, or return `default` on any failure (missing file,…, Return {'ts': float, 'by': str} from the last refresh, or None if the data has…, Seconds until the next refresh is allowed; 0 if none is in effect., Invalidate every cache layer and rebuild the lookup index immediately. Clears,…, Fernet key for the audit log / refresh-meta files — OS keychain first, a local… (+10 more)

### Community 1 - "store.py"
Cohesion: 0.05
Nodes (68): apply_create_session(), apply_end_session_op(), apply_scan_op(), create_device(), create_session(), _cursor(), device_for_token_hash(), end_session() (+60 more)

### Community 2 - "components.py"
Cohesion: 0.07
Nodes (39): empty_hero_html(), handheld_history_table_html(), header_html(), history_table_html(), _identity_block_html(), identity_header_html(), _kpi_chip_html(), _logo_data_uri() (+31 more)

### Community 3 - "session.py"
Cohesion: 0.09
Nodes (28): _confirm_end_session(), Gate on the one moment data could be lost for good: forgetting to export before…, BaseException, is_connectivity_error(), core/connectivity.py ~~~~~~~~~~~~~~~~~~~~~ Classifies whether an exception from…, True if `exc` represents a failure to reach/use the connection itself (DNS…, end_session(), _entry_from_result() (+20 more)

### Community 4 - "GTIN Barcode Scanner"
Cohesion: 0.20
Nodes (10): Architecture, goodID / AccessGUDID API, GTIN Barcode Scanner, Handheld Sync API (offline-first clients), Key Design Decisions, Prerequisites, Project Dependencies, Running Locally (Mock Data) (+2 more)

### Community 5 - "loader.py"
Cohesion: 0.15
Nodes (18): data package — exports the public data-loading interface., _coerce_bool(), _fetch_fresh_data(), load_contract_data(), _load_mock_data_fallback(), _load_mock_from_excel(), cache_data, DataFrame (+10 more)

### Community 6 - "test_export_injection.py"
Cohesion: 0.18
Nodes (17): build_workbook(), export_filename(), _filename_part(), _neutralize_formula(), core/export.py ~~~~~~~~~~~~~~ Excel session export. One workbook per session,…, Serialise a session's scan history to an .xlsx byte string. `location`,…, Prefix a leading formula-trigger character with `'` so Excel (and openpyxl's…, Sanitise a value for use inside the export filename. Location and Sanford ID… (+9 more)

### Community 7 - "GTIN Scanner — Handheld + Monitor Two-Surface Plan"
Cohesion: 0.14
Nodes (13): Build order (as shipped), Code change map, Core model, Data model — Postgres (Neon), replacing the SQLite plan below, Device onboarding (once per handheld, not per session), Duplicate handling → Scan Count (not drop, not a separate row), Explicitly deferred (deliberate, not forgotten), Export (+5 more)

### Community 8 - "test_gtin_validation.py"
Cohesion: 0.17
Nodes (20): Resolve a single scanned GTIN: local cache first, goodID API as fallback. Args:…, resolve_scan(), check_digit(), check_digit_valid(), normalize(), A GTIN-8/12/13/14 left-padded to its 14-digit form, or '' if unusable. GS1…, The mod-10 check digit for the first 13 digits of a GTIN-14. Weights alternate…, True if `gtin` normalises and its trailing check digit is correct. A False here… (+12 more)

### Community 11 - "build"
Cohesion: 0.33
Nodes (6): build(), main(), DataFrame, Path, scripts/build_mock_dataset.py ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Turn a raw Fabric…, Read a raw lakehouse export and write it as the canonical mock dataset.

### Community 12 - "enqueue"
Cohesion: 0.16
Nodes (28): _checksum(), enqueue(), flush(), _get_or_create_key(), _load(), pending_count(), pending_scans_for_session(), _prune() (+20 more)

### Community 13 - "CircuitBreaker"
Cohesion: 0.07
Nodes (34): _get_breaker(), GoodIDResult, query_goodid(), api/goodid_client.py ~~~~~~~~~~~~~~~~~~~~ HTTP fallback client for the FDA…, The module-level circuit breaker, created on first use. Deferred…, Structured result from an AccessGUDID API call. Attributes: success: True if…, Look up a device identifier against the FDA AccessGUDID database. Falls back…, api package — exports the goodID fallback client. (+26 more)

### Community 14 - "ASVS Security Audit — GTIN Barcode Scanner"
Cohesion: 0.05
Nodes (38): 1.1 GUDID (FDA AccessGUDID) — `api/goodid_client.py`, 1.2 Microsoft Fabric Lakehouse — `data/loader.py`, 1.3 Neon Postgres — `core/store.py`, 1. Network calls — TLS, timeouts, retries, 2. Credentials and secrets, 3. Scanned barcode input — validation and injection surface, 4.1 Contract-line reference data — `data/loader.py`, 4.2 Scan session data — `core/store.py` / `core/session.py` (+30 more)

### Community 15 - "_get_pool"
Cohesion: 0.20
Nodes (10): ConnectionPool, _close_pool(), _get_pool(), The process-wide connection pool, created on first use. A module-level pool is…, Close the pool and let the next call build a fresh one. Registered with atexit;…, fixture, Tests that core.store._get_pool logs the Neon host (never the full connection…, _reset_pool() (+2 more)

### Community 16 - "_conninfo"
Cohesion: 0.07
Nodes (39): allowed_hosts(), assert_allowed_host(), assert_allowed_url(), EgressBlocked, _fabric_host(), _neon_host(), RuntimeError, core/egress.py ~~~~~~~~~~~~~~~ Application-level egress allowlist. This is a… (+31 more)

### Community 17 - "from_keyring"
Cohesion: 0.18
Nodes (13): from_keyring(), core/secrets.py ~~~~~~~~~~~~~~~ Layered secret lookup, preferring the strongest…, The keychain-stored value for `key`, or None if unavailable. Every failure mode…, Write `value` into the OS keychain under SERVICE_NAME/key. Not called by the…, store_in_keyring(), _cache_key(), Fernet key for the on-disk contract-data cache. Same pattern as…, main() (+5 more)

### Community 18 - "test_contract_cache.py"
Cohesion: 0.17
Nodes (19): Encrypt `df` (as Parquet) and write it to CACHE_PATH., Decrypt and return the cached DataFrame, or None if it's missing, unreadable,…, _read_cache(), _write_cache(), _isolated_cache(), _no_real_keyring(), DataFrame, fixture (+11 more)

### Community 19 - "test_usage_stats.py"
Cohesion: 0.16
Nodes (16): classify_anomaly(), Classify `today` against `history` (oldest-first daily counts, not including…, Log one AccessGUDID fallback call. Called from api.goodid_client at every…, record_goodid_lookup(), Tests for core.usage_stats: the anomaly classifier (pure, no DB) and…, A scan must never fail because this logging call couldn't reach Neon — see the…, End-to-end: query_goodid() must still return a normal result even if…, test_goodid_client_lookup_failure_never_raises_even_if_logging_is_broken() (+8 more)

### Community 20 - "_load_from_lakehouse"
Cohesion: 0.16
Nodes (14): _contract_line_query(), _fabric_connection_string(), _load_from_lakehouse(), Build the contract line query against the configured lakehouse table., Assemble the ODBC connection string for the Fabric SQL analytics endpoint.…, Pull active contract lines from the Fabric Lakehouse gold layer. Connects to…, _fabric_env(), fixture (+6 more)

### Community 21 - "safe_log_value"
Cohesion: 0.08
Nodes (30): core/logsafe.py ~~~~~~~~~~~~~~~~ Sanitizes attacker-controlled strings — a…, A version of `value` safe to interpolate into a log message., safe_log_value(), extract_gtin(), Extract a 14-digit GTIN from a composite GS1 barcode., Exception, This op can never succeed as sent — the device should drop it., This op could not be applied right now but may succeed later. (+22 more)

### Community 22 - "_fabric_access_token"
Cohesion: 0.29
Nodes (8): _fabric_access_token(), _fabric_credential(), The stored AuthenticationRecord, or None if there isn't a usable one. A missing…, Persist the AuthenticationRecord so the next run can reuse the cache., Build the azure-identity credential named by FABRIC_AUTH. Sign-in is done here…, Acquire an Azure AD token, packed in the layout the ODBC driver expects. The…, _read_auth_record(), _write_auth_record()

### Community 23 - "Database"
Cohesion: 0.06
Nodes (14): android, Database, SqlOpQueue, SqlReferenceStore, SqlSessionLog, GtinScannerApp, OpQueue, SessionLog (+6 more)

### Community 24 - "test_sync_api.py"
Cohesion: 0.06
Nodes (82): JSONResponse, Request, Starlette, _BodyTooLarge, create_app(), _error(), _json(), Exception (+74 more)

### Community 25 - "MainActivity"
Cohesion: 0.10
Nodes (14): Activity, DataWedge, BroadcastReceiver, Context, MainActivity, Invalid, JSONObject, ScanController (+6 more)

### Community 26 - "InMemoryReferenceStore"
Cohesion: 0.19
Nodes (4): MirrorUpdater, InMemoryReferenceStore, offline(), MirrorUpdaterTest

### Community 27 - "test_offline_session.py"
Cohesion: 0.24
Nodes (13): Begin a fresh scan session, creating its row in the store. The row is written…, start_session(), _clean_session_state(), _isolated_queue(), _neon_down(), fixture, Integration tests: core.session's write paths degrade to the offline queue on a…, test_end_session_queues_on_connectivity_failure() (+5 more)

### Community 28 - "LookupEngine"
Cohesion: 0.15
Nodes (12): LookupEngine, Every (index key, contract-line record) pair, sorted by key. The keys are…, Look up a GTIN in the in-memory index. Leading zeros are preserved exactly as…, Return the number of indexed contract lines., In-memory GTIN lookup backed by a pre-built dict index. Args: df: Contract line…, build_snapshot(), sync_api/reference.py ~~~~~~~~~~~~~~~~~~~~~ The contract-line reference data…, Up to `limit` rows whose key sorts after `after`, plus the cursor for the next… (+4 more)

### Community 31 - "test_offline_resume.py"
Cohesion: 0.28
Nodes (12): find_pending_session(), A store `session`-row-shaped dict reconstructed from a still-queued…, Like resume_session(), but rehydrates from the offline queue instead of the…, resume_pending_session(), _clean_session_state(), Tests for resuming a session whose create_session write is still queued (the…, _reset_queue(), test_find_pending_session_reconstructs_row() (+4 more)

### Community 32 - "SyncEngine"
Cohesion: 0.34
Nodes (3): SyncEngine, ScriptedTransport, SyncEngineTest

### Community 33 - "board.py"
Cohesion: 0.15
Nodes (12): Render the typed-email allowlist gate; return the verified email once granted,…, render_access_gate(), pages/board.py ~~~~~~~~~~~~~~ Monitor master board — the passive, wide-layout…, pages/usage_dashboard.py ~~~~~~~~~~~~~~~~~~~~~~~~ Owner-only usage/security…, ui package — presentation layer only. No business logic lives here., inject_theme(), ui/theme.py ~~~~~~~~~~~ The single source of truth for brand colour, type and…, Mount the client runtime: autofocus, alert tones, Esc, clock, copy, count-up.… (+4 more)

### Community 35 - "HttpResult"
Cohesion: 0.22
Nodes (4): HttpUrlConnectionTransport, HttpResult, Transport, HttpURLConnection

### Community 36 - "ReferenceRow"
Cohesion: 0.15
Nodes (4): ReferenceStore, ReferenceRow, StagingState, ref()

### Community 37 - "SyncStatus"
Cohesion: 0.15
Nodes (11): Rejection, SyncReport, SyncStatus, AUTH_FAILED, DRAINED, OFFLINE, PARTIAL, PROTOCOL_ERROR (+3 more)

### Community 38 - "log_audit_event"
Cohesion: 0.21
Nodes (13): log_audit_event(), Append one record to the (encrypted) admin audit log. `event` is a short label…, Most-recent-first audit entries, up to `limit`. [] if none logged yet., read_audit_log(), _isolated_paths(), fixture, Tests that the admin audit log and refresh metadata are encrypted at rest…, test_audit_log_caps_at_max_records() (+5 more)

### Community 39 - "engine/lookup.py"
Cohesion: 0.19
Nodes (11): core(), indicator(), is_digits(), engine/gtin.py ~~~~~~~~~~~~~~ Pure GTIN arithmetic. No pandas, no Streamlit, no…, `gtin` re-expressed at another packaging level, check digit recomputed. Returns…, True for a non-empty all-ASCII-digit string. `str.isdigit()` is True for…, The packaging indicator digit: '0' for a base unit (each), '1'-'8' for…, The 12-digit company-prefix + item-reference core, or '' if unusable. This is… (+3 more)

### Community 40 - "core/lookup.py"
Cohesion: 0.21
Nodes (10): core package — scan orchestration, session model, export., contract_display_fields(), _field(), _field_any(), core/lookup.py ~~~~~~~~~~~~~~ Scan orchestration. This module holds the…, The display fields shown for a contract-line hit, from a raw record. Single…, Pull a display field from a contract-line record. `record` is a DataFrame row's…, First of `keys` that has a real value, else "-". Exists for fields whose source… (+2 more)

### Community 42 - "app.py"
Cohesion: 0.20
Nodes (10): _get_engine_lazy(), cache_resource, app.py ~~~~~~ GTIN Barcode Scanner — Handheld scan page, Streamlit entry point.…, get_lookup_engine(), cache_resource, Build the GTIN lookup engine once and cache for the app lifetime. Wraps…, clear_result(), find_duplicate() (+2 more)

### Community 43 - "MirrorResult"
Cohesion: 0.33
Nodes (7): AuthFailed, MirrorResult, Offline, RateLimited, ServerError, Updated, UpToDate

### Community 44 - ".doWork"
Cohesion: 0.25
Nodes (5): Context, SyncScheduler, SyncWorker, Result, Worker

### Community 46 - ".diagnose"
Cohesion: 0.22
Nodes (5): describe_indicator(), A human label for a packaging indicator digit, for UI/export text., Closest known core to `body`, as (shared leading digits, that core). Returns…, Explain why `gtin` did not match a contract line. Only meaningful after…, , Lawson 6112009' for a record that has one, else ''.

### Community 48 - "ConfigSource"
Cohesion: 0.48
Nodes (3): ConfigSource, Context, SyncConfig

### Community 49 - "Fakes.kt"
Cohesion: 0.62
Nodes (5): JSONObject, ok(), rowJson(), rowsPage(), versionResponse()

### Community 50 - "GTIN Scanner — Android client"
Cohesion: 0.29
Nodes (5): Build & test, GTIN Scanner — Android client, How it behaves, Layout, Status — read this

### Community 51 - "_FakeKeyring"
Cohesion: 0.29
Nodes (4): fake_keyring(), _FakeKeyring, fixture, Minimal in-memory stand-in for the `keyring` module's public API.

### Community 52 - "is_admin"
Cohesion: 0.33
Nodes (6): _allowed_domains(), _allowed_emails(), is_admin(), Admin allowlist, lower-cased, from .streamlit/secrets.toml [admin]., Optional email-domain allowlist (e.g. 'sanfordhealth.org') so a whole group can…, True if the typed `email` is on the admin allowlist. This checks the string a…

### Community 53 - "._build_diagnostics"
Cohesion: 0.33
Nodes (3): DataFrame, Build the two indexes diagnose() needs, from the exact index. Derived from…, Normalise a GTIN cell to a lookup key, or '' if empty/NaN. Empty low-UOM cells…

### Community 54 - "Setup"
Cohesion: 0.33
Nodes (6): 1. Clone / open the project, 2. Create and activate a virtual environment, 3. Install dependencies, 4. Configure environment variables, 5. Set up the database (Neon Postgres), Setup

### Community 55 - "Handheld Sync API"
Cohesion: 0.33
Nodes (6): Client rules that keep the data correct, Handheld Sync API, Auth, Model, Running it, Security properties

### Community 56 - "Endpoints"
Cohesion: 0.33
Nodes (6): Endpoints, `GET /healthz`, `GET /v1/lookup?code=<raw scan>`, `GET /v1/reference/contract-lines?version=&after=&limit=`, `GET /v1/reference/version`, `POST /v1/sync`

### Community 57 - "Fabric Lakehouse Migration — Open Items"
Cohesion: 0.40
Nodes (3): Fabric Lakehouse Migration — Open Items, Resolved, Still open

### Community 58 - "Admin Refresh Page"
Cohesion: 0.40
Nodes (5): 1. Fill in `.streamlit/secrets.toml`, 2. Run it, Access model: typed-email allowlist, not a verified login, Admin Refresh Page, Why it needs three cache layers cleared, not one

### Community 59 - "Switching to the Fabric Lakehouse"
Cohesion: 0.40
Nodes (5): 1. Install the Microsoft ODBC driver (system-level), 2. Install the Python driver, 3. Fill in `.env`, 4. Run it, Switching to the Fabric Lakehouse

### Community 60 - "Usage Dashboard"
Cohesion: 0.40
Nodes (5): A spike in "users" isn't proof of an attack, Access model: admin allowlist, narrowed to one owner, Enabling the nightly rollup, Usage Dashboard, Why it needs its own tables

### Community 61 - "gradlew"
Cohesion: 0.83
Nodes (3): gradlew script, die(), warn()

### Community 63 - "_isolated_queue"
Cohesion: 0.67
Nodes (3): _isolated_queue(), fixture, Every test gets its own queue file/key, never the real one, and never touches…

## Knowledge Gaps
- **96 isolated node(s):** `Offline`, `AuthFailed`, `DRAINED`, `PARTIAL`, `OFFLINE` (+91 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LookupEngine` connect `LookupEngine` to `engine/lookup.py`, `core/lookup.py`, `test_gtin_validation.py`, `app.py`, `.diagnose`, `._build_diagnostics`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Why does `query_goodid()` connect `CircuitBreaker` to `test_gtin_validation.py`, `core/lookup.py`, `_conninfo`, `test_usage_stats.py`, `safe_log_value`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._
- **Why does `resolve_scan()` connect `test_gtin_validation.py` to `core/lookup.py`, `app.py`, `CircuitBreaker`, `safe_log_value`, `test_sync_api.py`, `LookupEngine`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **What connects `Offline`, `AuthFailed`, `DRAINED` to the rest of the system?**
  _96 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `store.py` be split into smaller, more focused modules?**
  _Cohesion score 0.054773082942097026 - nodes in this community are weakly interconnected._
- **Should `components.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07179487179487179 - nodes in this community are weakly interconnected._
- **Should `session.py` be split into smaller, more focused modules?**
  _Cohesion score 0.09195402298850575 - nodes in this community are weakly interconnected._