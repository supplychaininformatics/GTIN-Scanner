# 🔍 GTIN Barcode Scanner

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
│   └── loader.py             # Redshift (commented) + Mock data (active)
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

Open `.env` and fill in values as needed. For local development the defaults work out of the box — `DATA_SOURCE=mock` is active and no Redshift credentials are required.

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

## Switching to Production Redshift

When VPN access is available:

### 1. Install the Redshift driver

```bash
pip install -e ".[production]"
```

### 2. Update `.env`

```dotenv
DATA_SOURCE=redshift

REDSHIFT_HOST=your-cluster.region.redshift.amazonaws.com
REDSHIFT_PORT=5439
REDSHIFT_DB=your_database
REDSHIFT_USER=your_user
REDSHIFT_PASSWORD=your_password
```

### 3. Uncomment the Redshift block in `data/loader.py`

Open [`data/loader.py`](data/loader.py) and:

- **Uncomment** the `_load_from_redshift()` function (lines marked `PRODUCTION REDSHIFT BLOCK`).
- **Remove** the `NotImplementedError` inside `load_contract_data()` and uncomment the `return _load_from_redshift()` line.

The data cache TTL is set to **24 hours** via `@st.cache_data(ttl=86400)`, so Redshift is queried at most once per day per server instance.

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
| `@st.cache_data(ttl=86400)` | Redshift is hit at most once per day. The mock loader uses the same decorator so switching data sources requires zero refactoring. |
| Session history in `st.session_state` | History persists for the browser session lifetime and resets on page refresh — matching the expected workflow of a warehouse scanning station. |

---

## Project Dependencies

| Package | Version | Purpose |
|---|---|---|
| `streamlit` | ≥ 1.32 | Web UI framework |
| `pandas` | ≥ 2.0 | DataFrame for cached contract line data |
| `python-dotenv` | ≥ 1.0 | `.env` file loading |
| `httpx` | ≥ 0.27 | Synchronous HTTP client for goodID API |
| `redshift_connector` | ≥ 2.1 | *(optional, production only)* Redshift connection |

---

## Stopping the App

Press `Ctrl+C` in the terminal where Streamlit is running.

To deactivate the virtual environment:

```bash
deactivate
```
