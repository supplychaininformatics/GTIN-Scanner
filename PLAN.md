# GTIN Scanner — Handheld + Monitor Two-Surface Plan

Status: design locked, ready to build. Not yet implemented.

## Core model

**One session = one handheld's scanning run.** Session is created on the
handheld and ended on the handheld. The monitor is a passive master board —
it never scans and never owns session lifecycle (except the force-end escape
hatch below). No in-app camera anywhere.

## Surfaces

| Surface | Role |
|---|---|
| **Handheld scan app** (stacked mobile layout) | Opens to a **start form**: Sanford ID (scan badge or type) + location (free text). Submitting creates the session. Then the scan loop: big scan field, lean list of the picker's own scans (status + Item Description + Lawson UOM + Scan Count). Ends its own session behind a confirm dialog. |
| **Monitor master board** (wide layout, evolution of current `app.py`) | Shows the static app QR/link (provisioning/fallback, not per-session). Lists **today's sessions** — Sanford ID, location, status, scan count, last-scan time. Click a session → full scan list. **Per-session Excel export.** Small filter to view the full 3-day retention window. Force-end control for dead sessions. |
| **Admin** (`pages/admin.py`) | Unchanged — Fabric refresh, audit log. Natural home for the force-end control. |

## Device onboarding (once per handheld, not per session)

Scan the monitor/printed QR with the device's **system camera app** (not
in-app) → opens the app URL in the browser → **Add to Home Screen**.
Thereafter pickers just tap the icon. The QR is a static link — it never
carries a session id, so it doesn't need to be re-scanned each session.

Rejected: in-app live QR scanning. Handheld-minted sessions removed the need
for the QR to carry data, and Streamlit's iframe-based custom components
can't reliably get `getUserMedia`/camera permission — building it would have
spent the riskiest engineering in the whole plan solving a problem that no
longer exists.

## Session lifecycle

```
[tap icon] → start form (ID + location) → ACTIVE → [End Session on handheld] → ENDED
                                            │
                                            ├── no scans for 4h → STALE (shown distinctly on board; export still works)
                                            └── board/admin Force End (audited) → ENDED
```

- `session_id` is minted on the handheld at form submit and written into the
  URL immediately (`?sid=...`), reusing the resume mechanism already in
  `app.py`/`core/session.py` — refresh, sleep, or reconnect resumes from the
  DB instead of losing state.
- Normal end = handheld only. Force-end = escape hatch for a dead/dropped
  device, so a session can't get stuck ACTIVE forever. Logged like the
  existing admin audit log (`data/cache/admin_audit.log`).

**Explicit accepted assumption:** scanning is online-only for v1. A scan that
happens during a Wi-Fi drop must be re-scanned. No offline queue. Revisit
later if it's a real problem in the warehouse.

## Duplicate handling → Scan Count (not drop, not a separate row)

- Rescanning a GTIN **within the same session** (same handheld): flag it on
  screen (as today), and **increment `scan_count` + update `last_scanned`**
  on the existing row instead of appending a new row or silently dropping it.
- The same GTIN in a **different session** (different handheld, or same
  handheld on a later session): a separate, legitimate entry. No cross-session
  dedupe.
- Export ends up with one row per GTIN per session, with a `Scan Count`
  column — no quantity information is destroyed, and the export stays clean.

## Data model — SQLite, WAL mode, on the app server

Replaces the current whole-file JSON autosave (`core/autosave.py`) with an
append/upsert-per-scan store, which is what makes multiple concurrent
sessions safe.

```sql
session(
  session_id   TEXT PRIMARY KEY,          -- minted handheld-side on form submit
  sanford_id   TEXT,                      -- scanned (badge barcode) or typed, trusted, no format validation
  location     TEXT,                      -- free text for now; dropdown later (deferred, see below)
  status       TEXT,                      -- active | stale | ended
  created_at   TEXT,                      -- full ISO datetime, UTC
  ended_at     TEXT
)

scan(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id    TEXT REFERENCES session(session_id),
  scanned_at    TEXT,                     -- full ISO datetime, UTC (first scan)
  last_scanned  TEXT,                     -- updated on rescan
  scan_count    INTEGER DEFAULT 1,
  gtin          TEXT,
  status_key    TEXT,
  source        TEXT,                     -- kept: required by existing export contract
  on_hold       INTEGER,                  -- kept: required by existing KPI/UI contract (compute_stats)
  item          TEXT,
  company       TEXT,
  brand         TEXT,
  description   TEXT,
  gtin_uom      TEXT,
  uou           TEXT,
  hibcc         TEXT,
  lawson_id     TEXT,
  lawson_uom    TEXT
);

CREATE INDEX idx_scan_dedupe ON scan(session_id, gtin);
```

Notes carried over from the current code that must not be lost in the
rewrite (see `core/session.py` docstring and `_FULL_RECORD_KEYS`):
- `source` and `on_hold` are both consumed downstream (export columns, KPI
  math in `compute_stats`) — dropping them would break existing contracts.
- Timestamps move from `%H:%M:%S` time-of-day strings to full ISO datetimes
  (UTC in the DB, formatted for wall-clock display in the UI/export) — the
  old format breaks once sessions persist across days and get listed on a
  board.

## Retention

- **Board default view: today's sessions only.**
- A small filter exposes the full **3-day window** (today + 2 prior days),
  so a session from yesterday or the day before is still reachable for
  export.
- **Auto-purge:** sessions and their scans older than 3 days are deleted
  (checked daily or on app start). No archival beyond this in v1.
- Consequence to flag to warehouse staff: **exports must happen within 3
  days** — after purge, the data is gone. The 3-day window is the only
  backup.

## Export

- Per-session only (no "export all sessions" in v1), triggered from the
  board.
- Columns = today's workbook columns (`core/export.py`, unchanged shape)
  **plus** `session_id`, `sanford_id`, `location`, `Scan Count`.
- Filename becomes dynamic to avoid collisions across many sessions:
  `scans_{location}_{sanford_id}_{YYYY-MM-DD}_{sid8}.xlsx` (currently a
  static `EXPORT_FILENAME` constant).
- `build_workbook(history, location)` keeps its current signature/shape —
  the board builds a `history` list from a DB query and hands it in exactly
  as `app.py` does today.

## Sanford ID entry

- Scan-or-type: the ID field accepts either a scanned badge barcode (imager
  types into the focused field, same keystroke-emulation mechanism as GTIN
  scanning) or manual entry. No format/roster validation — trusted input,
  consistent with how `warehouse_location` is handled today.

## Code change map

| File | Change |
|---|---|
| `core/autosave.py` | Replaced by **`core/store.py`**: SQLite schema above, session create/end/force-end, scan insert-or-increment, purge job. This is the foundation everything else depends on — build and verify it first. |
| `core/session.py` | Scan record/dedupe/stats logic reads and writes the store, scoped by `session_id`. Dedupe changes from "drop" to "upsert scan_count". Timestamps become full ISO datetimes. |
| `app.py` | Splits into two pages: **handheld scan page** (start form → scan loop, stacked mobile layout) and **monitor board page** (session list, drill-in, per-session export, force-end control). |
| `core/export.py` | Add `session_id`, `sanford_id`, `location`, `Scan Count` columns; dynamic filename instead of the `EXPORT_FILENAME` constant. |
| `pages/admin.py` | Optionally hosts the force-end control, reusing the existing audit-log pattern. |
| Unchanged | `engine/`, `api/`, `data/` (lookup engine, AccessGUDID client, Fabric contract-line loader) — none of this is affected by the session/store rewrite. |

## Explicitly deferred (deliberate, not forgotten)

1. **Location dropdown / per-station URL preset.** Free text for now, to
   test basic functionality in the warehouse first. Revisit once real
   location strings are known.
2. **Wi-Fi resilience / offline scan queue.** Online-only accepted for v1;
   revisit if dead zones turn out to be a real problem.
3. **DataWedge profile tuning** on the Zebra TC52x / HC50. Default keystroke
   output is expected to work out of the box for both badge scans and item
   scans (both just type into whatever text field has focus); formal
   DataWedge profile setup is a later, separate task if needed.
4. **Retention beyond 3 days / real archival.** Purge-after-3-days is the
   v1 policy; a longer-term archive (e.g. into Fabric) is a future decision.

## Suggested build order

1. `core/store.py` — schema, session lifecycle functions, scan
   insert-or-increment, purge job. Testable standalone with no UI.
2. Wire `core/session.py` to the store.
3. Handheld scan page (start form + scan loop) against the new store.
4. Monitor board page (session list + drill-in + export + force-end).
5. `core/export.py` column/filename changes.
6. End-to-end test in the actual warehouse with a real TC52x/HC50 on Wi-Fi.
