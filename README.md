# GTIN Barcode Scanner

A production-ready Streamlit application that modernizes a legacy Excel macro for barcode scanning in supply chain analytics. Scans a GTIN (Global Trade Item Number) from a physical barcode scanner, performs an O(1) in-memory lookup against a cached dataset of medical supply contract lines, and falls back to an external goodID API if the item isn't found locally.

---

## Architecture

```
gtin-scanner/
├── app.py                    # Handheld scan page (start form + scan loop) — default page
├── pages/
│   ├── board.py               # Monitor master board: today's sessions, drill-in, export, force-end
│   └── admin.py               # Admin-only data refresh + force-end (email-allowlist gated)
├── ui/
│   ├── theme.py              # The single CSS injection + palette + JS runtime
│   └── components.py         # header, kpi tiles, result card, pills, tables
├── core/
│   ├── lookup.py             # Scan orchestration (GS1 parse → cache → API)
│   ├── store.py              # Postgres (Neon) session/scan store — session & scan persistence
│   ├── session.py            # Session state + scan history model, backed by core/store.py
│   ├── export.py             # Excel writer (per-session, dynamic filename)
│   └── admin.py               # Admin auth check + cache-refresh orchestration
├── data/
│   └── loader.py             # Fabric Lakehouse + Mock data (active by default)
├── engine/
│   └── lookup.py             # O(1) dict-indexed GTIN lookup
├── api/
│   └── goodid_client.py      # Sync httpx fallback client
├── assets/
│   └── sanford-logo.png      # Official mark — referenced, never redrawn
├── migrations/
│   └── 001_initial.sql       # Neon Postgres schema for session/scan (run once, idempotent)
├── scripts/
│   └── purge_expired.sql     # Retention sweep, run by the daily GitHub Action below
├── .github/workflows/
│   └── purge-expired.yml     # Daily cron: purges sessions/scans past the retention window
├── .streamlit/
│   ├── config.toml           # Theme and server config
│   └── secrets.toml.example  # Template for the Neon connection string + admin email allowlist
├── .env.example              # Environment variable template
└── pyproject.toml            # Project metadata and dependencies
```

`engine/`, `api/` and `data/` hold the lookup, API and caching logic and are
independent of the UI. `core/` orchestrates them; `ui/` draws the result. No
colour is hardcoded outside `ui/theme.py`.

Two picker/supervisor-facing surfaces, both backed by the same Neon Postgres
store (`core/store.py` — see `PLAN.md` for the full design, and "Setting Up
the Database" below for connecting it):

- **`app.py`** (default page) — the handheld: a picker scans their Sanford ID
  (badge or typed) and enters a location to start a session, then scans
  GTINs in a loop. Only the handheld that started a session can normal-end
  it.
- **`pages/board.py`** — the monitor: a passive, wide-layout board listing
  today's sessions (Sanford ID, location, status, scan count, last scan),
  with drill-in to any session's full scan list, a per-session Excel export,
  a filter for the full 3-day retention window, and a Force End control for
  a dropped/dead handheld's session.
- **`pages/admin.py`** — data refresh (unchanged) plus the same Force End
  control, for supervisors who reach session management through the admin
  gate instead of the board.

Sessions and scans older than 3 days are purged automatically — export
before then, since the 3-day window is the only backup (no offline queue,
no archival beyond it in v1; see `PLAN.md` → "Retention"). The authoritative
sweep is a daily GitHub Action (`.github/workflows/purge-expired.yml`,
running `scripts/purge_expired.sql` against Neon) so it fires even when
nobody has the app open; `core/store.purge_old_sessions()` runs the same
policy in-app as a belt-and-braces backstop.

**Data flow per scan:**

```
Barcode Scanner (keyboard emulator)
        │
        ▼
  st.form input  ──►  LookupEngine.search(gtin)  ──►  Cache HIT  ──►  Display metrics
                              │                                         + on_hold warning
                         Cache MISS
                              │
                              ▼
                       goodID API (httpx)  ──►  Success  ──►  Display JSON
                                          └──►  Failure  ──►  Display error
```

---

## Prerequisites

- Python 3.11 or higher
- macOS / Linux (Windows works but activate the venv differently)
- A Postgres database for session/scan storage — a [Neon](https://neon.tech)
  project is what this app is built and deployed against. This is required
  even for local development with mock catalog data: `DATA_SOURCE` only
  switches the product-catalog source (mock vs. Fabric); sessions and scans
  always persist through `core/store.py` to Postgres. See "Setting Up the
  Database" below.

---

## Setup

### 1. Clone / open the project

```bash
cd /path/to/gtin-scanner
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -e .
```

> This installs everything listed in `pyproject.toml` (`streamlit`, `pandas`, `psycopg[binary,pool]`, `python-dotenv`, `httpx`, `pyarrow`, `openpyxl`, `Pillow`).

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in values as needed. `DATA_SOURCE=mock` is active by
default, so no Fabric/Azure setup is needed for local development — but
session and scan storage always goes through Postgres regardless of
`DATA_SOURCE`. Set that up next.

### 5. Set up the database (Neon Postgres)

Sessions and scans persist to Postgres (`core/store.py`) — this step is not
optional, including for local dev against mock catalog data.

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

1. Create a free [Neon](https://neon.tech) project (or point at any Postgres
   instance).
2. Copy the **pooled** connection string (the host with `-pooler` in it —
   every Streamlit rerun opens a connection, so pooling matters even for
   local dev) into `.streamlit/secrets.toml` under `[neon].url`. This file is
   git-ignored, unlike `.env`, so it's the right place for a credential.
   Alternatively, set `NEON_DATABASE_URL` (or `DATABASE_URL`) in the
   environment — it takes precedence over `secrets.toml` if both are set.
3. Apply the schema once (idempotent — safe to re-run):

   ```bash
   psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_initial.sql
   ```

Without a valid connection string, `core/store.py` raises on first use — the
app fails fast rather than silently losing scans.

---

## Running Locally (Mock Data)

```bash
source .venv/bin/activate     # if not already active
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

### Test GTINs (Mock Dataset)

| GTIN | Item | Expected Result |
|---|---|---|
| `00841098765432` | Surgical Mesh 15cm | ✅ Cache hit |
| `00123456789012` | Nitrile Gloves, Large | ⚠️ Cache hit — **ON HOLD** warning |
| `00555555555555` | Titanium Knee Joint | ✅ Cache hit |
| `00312345678901` | Foley Catheter 14Fr | ✅ Cache hit |
| `00499988776655` | IV Administration Set | ⚠️ Cache hit — **ON HOLD** warning |
| `00000000000000` | *(not in dataset)* | 🌐 goodID API fallback |

> **Tip:** If you're testing with an actual barcode scanner, point it at a barcode you've printed or displayed on screen — the scanner will auto-submit via Enter and the result will appear immediately.

---

## Switching to the Fabric Lakehouse

Production data lives in a Microsoft Fabric Lakehouse. The app reaches it through
the lakehouse's **SQL analytics endpoint** — a SQL-Server-style (TDS) connection
over ODBC, authenticated with your own Azure AD identity. **No password is stored
anywhere**, which is why `.env` is safe to keep in version control.

### 1. Install the Microsoft ODBC driver (system-level)

`pip` cannot do this one — the driver is a system package from Microsoft.

```bash
# macOS
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18

# Windows — download and run the installer:
# https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server
```

Verify it registered: `odbcinst -q -d` (macOS/Linux), or check *ODBC Data Sources*
→ *Drivers* (Windows). You should see `ODBC Driver 18 for SQL Server`.

### 2. Install the Python driver

```bash
pip install -e ".[fabric]"
```

### 3. Fill in `.env`

Get the endpoint and lakehouse name from the Fabric workspace:
**Lakehouse → "SQL analytics endpoint" → Settings → Connection string**.

```dotenv
DATA_SOURCE=fabric

FABRIC_SQL_ENDPOINT=xxxxx.datawarehouse.fabric.microsoft.com
FABRIC_DATABASE=your_lakehouse_name
FABRIC_TABLE=[Silver_Lake].[infor].[contract_line]
FABRIC_AUTH=ActiveDirectoryInteractive
```

`FABRIC_TABLE` accepts a bracket-quoted `[db].[schema].[table]` name (T-SQL
style) or a plain `schema.table`. If the lakehouse ever renames the
contract-line table or view, update it here — the SQL itself does not need
editing.

> **Before flipping `DATA_SOURCE=fabric` for real use:** three open questions
> about this table's schema — a column-mapping guess, a dropped barcode-alias
> feature, and a dropped active-line filter — are tracked in
> [FABRIC_TODO.md](FABRIC_TODO.md). Resolve those first.

### 4. Run it

On the first query a **browser window opens for Azure AD sign-in**. That is
`ActiveDirectoryInteractive` doing its job. Two consequences worth knowing:

- The sign-in prompt appears on **the machine running the Python process**, not
  in the user's browser tab. This works when you run Streamlit locally. It
  cannot work on a headless/shared server — nobody is there to click. If you
  deploy this app, switch `FABRIC_AUTH` to `ActiveDirectoryDefault` (reuses an
  `az login` session or a managed identity) or `ActiveDirectoryDeviceCode`.
- You will be prompted at most **once per day**: results are written to
  `data/cache/contract_lines.parquet` and reused for 24 hours.

---

## Admin Refresh Page

The 24h cache described above is deliberately passive. In the warehouse, new
items land in `contract_line` and get scanned again **2-3 hours later, the
same day** — so a purely passive cache means those items read as "Not Found"
until the next day. `pages/admin.py` adds a manual "Refresh data now" button
for exactly that gap, restricted to managers/supervisors so line staff can't
hammer it.

Works identically regardless of `DATA_SOURCE` — on `mock` it re-reads the
Excel file, on `fabric` it re-runs the lakehouse query — so you can build and
test the whole flow today, before ever flipping to Fabric.

### Why it needs three cache layers cleared, not one

A scan is served by four independent caches stacked on top of each other:
the on-disk Parquet file (fresh for 24h by file **mtime**), `load_contract_data()`'s
own `@st.cache_data`, `_load_from_lakehouse()`'s separate `@st.cache_data` on
the Fabric path specifically, and `get_lookup_engine()`'s `@st.cache_resource`
(no TTL — holds for the whole app lifetime). `core/admin.refresh_now()` clears
all four together and rebuilds immediately, which is why "refresh" isn't just
deleting the Parquet file — doing that alone would still serve a stale
in-memory copy until the next server restart.

### Access model: typed-email allowlist, not a verified login

A visitor types their email; the page checks it against an allowlist, the
software equivalent of a sign-in sheet — not a badge reader. **It is not
verified identity.** Anyone who learns an allowlisted address could type it
in and get through. That tradeoff is deliberate for now (no identity
provider to stand up), and is offset by an audit trail: every attempt —
granted or denied — and every refresh is logged, so misuse is visible after
the fact even though it isn't prevented up front.

If that tradeoff stops being acceptable (e.g. the allowlist leaks, or this
needs to move to a shared/public URL), the natural upgrade is a verified
login — Streamlit's native `st.login()` against Microsoft Entra ID, reusing
the same Azure AD tenant as the Fabric connection. That would replace the
`st.text_input` email check in `pages/admin.py` with `st.user.email` from a
completed OAuth flow; `core/admin.py::is_admin()`'s allowlist check itself
wouldn't need to change.

### 1. Fill in `.streamlit/secrets.toml`

This is the same file created in Setup step 5 for the Neon connection string
— don't re-run the `cp` from that step here, it would overwrite the `[neon]`
URL you already filled in. Just add the `[admin]` block to the existing file
(or create it from the template if you skipped that step):

```bash
[ -f .streamlit/secrets.toml ] || cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

List who's allowed to refresh:

```toml
[admin]
allowed_emails = ["manager1@example.org", "supervisor2@example.org"]
# allowed_domains = ["example.org"]   # optional: grant a whole group by domain
```

This file is git-ignored (like `data/cache/`) — without it, the allowlist is
empty and every typed email is denied (and logged as such).

### 2. Run it

```bash
streamlit run app.py
```

Visit `http://localhost:8501/admin`. A blank/non-allowlisted email shows an
access-denied message; an allowlisted email is remembered for the browser
session and shows the last-refresh banner, the refresh button, and a
**Recent access log** expander (who signed in/was denied/refreshed, and
when — the same data written to `data/cache/admin_audit.log`, one JSON
record per line, also git-ignored). Each refresh is throttled by a 5-minute
cooldown, tracked in `data/cache/refresh_meta.json` — cross-session, so it
holds even if a different admin clicks it from another browser.

---

## goodID / AccessGUDID API

The fallback API is the **FDA AccessGUDID** (Automated Identification and Data Capture GUDID) — a publicly accessible database of medical device identifiers maintained by the U.S. National Library of Medicine.

- **No credentials or API key required.** The API is open to the public.
- **Endpoint:** `https://accessgudid.nlm.nih.gov/api/v2/devices/lookup.json?di=<GTIN>`
- **Docs:** https://accessgudid.nlm.nih.gov/api_docs

No `.env` changes are needed for the goodID integration. It works out of the box.

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| `st.form(clear_on_submit=True)` | Physical scanners send the same GTIN + Enter twice in a row. Without a form, Streamlit won't rerun because the widget value hasn't changed. The form clears the field on every submit, guaranteeing a rerun. |
| O(1) dict index in `LookupEngine` | The DataFrame is indexed into a Python dict at startup. Every subsequent scan is a single dict lookup — no DataFrame scanning, no filtering. |
| Synchronous `httpx.Client` | Streamlit's execution model is synchronous. `asyncio.run()` inside Streamlit causes event-loop conflicts. Sync client avoids this entirely. |
| No auth on goodID API | The FDA AccessGUDID is a fully public API — no token, no OAuth, no rate limiting for typical use. |
| GTIN stored as `str`, no normalisation | Leading zeros are preserved exactly as scanned. No `lstrip("0")` or zero-padding — the GTIN in the DB and the scanner output must match as-is. |
| `@st.cache_data(ttl=86400)` | The lakehouse is hit at most once per day — which also means the Azure AD sign-in prompt appears at most once per day. The mock loader uses the same decorator so switching data sources requires zero refactoring. |
| Sessions persisted to Postgres, not just `st.session_state` | The DB row is the durable copy; `st.session_state` is a cache rebuilt from it. A `?sid=` query param lets `app.py` call `resume_session()` and rehydrate scan history after a page refresh or the handheld browser being killed and reopened — matching a warehouse floor where a device can lose its tab mid-shift. |

---

## Project Dependencies

| Package | Version | Purpose |
|---|---|---|
| `streamlit` | ≥ 1.32 | Web UI framework |
| `pandas` | ≥ 2.0 | DataFrame for cached contract line data |
| `psycopg[binary,pool]` | ≥ 3.1 | Postgres driver + connection pool for the Neon-backed session/scan store (`core/store.py`). `binary` ships a prebuilt libpq, so no system Postgres install is needed. |
| `python-dotenv` | ≥ 1.0 | `.env` file loading |
| `httpx` | ≥ 0.27 | Synchronous HTTP client for goodID API |
| `pyarrow` | ≥ 15.0 | Parquet read/write for the 24h contract-data cache (`data/cache/contract_lines.parquet`) |
| `openpyxl` | ≥ 3.1 | Excel engine for per-session export (`core/export.py`) |
| `Pillow` | ≥ 10.0 | Logo image processing (`ui/components.py`) |
| `pyodbc` | ≥ 5.1 | *(optional, production only, `pip install -e ".[fabric]"`)* Fabric Lakehouse connection. Also needs the Microsoft ODBC driver installed at system level. |

---

## Stopping the App

Press `Ctrl+C` in the terminal where Streamlit is running.

To deactivate the virtual environment:

```bash
deactivate
```
