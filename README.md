# GTIN Barcode Scanner

A production-ready Streamlit application that modernizes a legacy Excel macro for barcode scanning in supply chain analytics. Scans a GTIN (Global Trade Item Number) from a physical barcode scanner, performs an O(1) in-memory lookup against a cached dataset of medical supply contract lines, and falls back to an external goodID API if the item isn't found locally.

---

## Architecture

```
gtin-scanner/
├── app.py                    # Streamlit entry point — layout composition only
├── ui/
│   ├── theme.py              # The single CSS injection + palette + JS runtime
│   └── components.py         # header, kpi tiles, result card, pills, tables
├── core/
│   ├── lookup.py             # Scan orchestration (GS1 parse → cache → API)
│   ├── session.py            # Session state + scan history model
│   └── export.py             # Excel writer
├── data/
│   └── loader.py             # Fabric Lakehouse + Mock data (active by default)
├── engine/
│   └── lookup.py             # O(1) dict-indexed GTIN lookup
├── api/
│   └── goodid_client.py      # Sync httpx fallback client
├── assets/
│   └── sanford-logo.png      # Official mark — referenced, never redrawn
├── .streamlit/
│   └── config.toml           # Theme and server config
├── .env.example              # Environment variable template
└── pyproject.toml            # Project metadata and dependencies
```

`engine/`, `api/` and `data/` hold the lookup, API and caching logic and are
independent of the UI. `core/` orchestrates them; `ui/` draws the result. No
colour is hardcoded outside `ui/theme.py`.

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

> This installs everything listed in `pyproject.toml` (`streamlit`, `pandas`, `python-dotenv`, `httpx`).

### 4. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in values as needed. For local development the defaults work out of the box — `DATA_SOURCE=mock` is active and no database access is required.

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
| Session history in `st.session_state` | History persists for the browser session lifetime and resets on page refresh — matching the expected workflow of a warehouse scanning station. |

---

## Project Dependencies

| Package | Version | Purpose |
|---|---|---|
| `streamlit` | ≥ 1.32 | Web UI framework |
| `pandas` | ≥ 2.0 | DataFrame for cached contract line data |
| `python-dotenv` | ≥ 1.0 | `.env` file loading |
| `httpx` | ≥ 0.27 | Synchronous HTTP client for goodID API |
| `pyodbc` | ≥ 5.1 | *(optional, production only)* Fabric Lakehouse connection. Also needs the Microsoft ODBC driver installed at system level. |

---

## Stopping the App

Press `Ctrl+C` in the terminal where Streamlit is running.

To deactivate the virtual environment:

```bash
deactivate
```
