"""
core/export.py
~~~~~~~~~~~~~~
Excel session export.

One workbook per session, triggered from the monitor board (see
pages/board.py) — there is no "export all sessions" in v1. The column set
gained `session_id`, `sanford_id`, `location` (each session-level, one value
for the whole file, inserted as lead columns exactly as `location` already
was) and `Scan Count` (genuinely per-row, since PLAN.md's duplicate-handling
policy increments it instead of dropping or appending a rescan).

The filename is now dynamic — `EXPORT_FILENAME` was a single static constant,
which would collide across the many per-session files the board can now
produce back to back.
"""

from __future__ import annotations

import io
import re

import pandas as pd

EXPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Column order as originally written, plus Scan Count (see PLAN.md "Duplicate
# handling"). Keys added for the UI only (status_key, on_hold, miss_reason —
# the raw key behind the "Miss Reason" label) are deliberately absent, so the
# exported sheet stays clean.
#
# Miss Reason / Miss Detail trail the original columns rather than sitting
# beside `status`: both are blank on every contract hit, which is most rows,
# and inserting two mostly-empty columns mid-sheet would push the item fields
# people actually read off the first screen.
_COLUMNS = [
    "time", "source", "status", "Scan", "Item", "Company", "Brand",
    "Description", "GTIN", "GTIN UOM", "UOU", "HIBCC", "LAWSON ID", "Lawson UOM",
    "Scan Count", "Miss Reason", "Miss Detail",
]

_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _filename_part(value: str | None, fallback: str) -> str:
    """Sanitise a value for use inside the export filename.

    Location and Sanford ID are free text (see PLAN.md "Sanford ID entry") —
    neither is validated against a format, so both need to be scrubbed to
    filesystem/URL-safe characters before landing in a Content-Disposition
    filename.
    """
    cleaned = _FILENAME_UNSAFE_RE.sub("_", (value or "").strip()).strip("_")
    return cleaned or fallback


def export_filename(
    location: str | None, sanford_id: str | None, session_id: str, created_at: str
) -> str:
    """Build a collision-resistant filename for one session's export.

    `created_at` is the session's full ISO datetime (see core/store.py) —
    only the date part is used, matching the existing wall-clock display
    convention (UTC in the DB, formatted for the UI/export).
    """
    date_part = (created_at or "")[:10] or "unknown-date"
    sid8 = (session_id or "")[:8] or "unknown"
    loc = _filename_part(location, "site")
    sid = _filename_part(sanford_id, "picker")
    return f"scans_{loc}_{sid}_{date_part}_{sid8}.xlsx"


def build_workbook(
    history: list[dict],
    location: str | None = None,
    sanford_id: str | None = None,
    session_id: str | None = None,
) -> bytes:
    """Serialise a session's scan history to an .xlsx byte string.

    `location`, `sanford_id` and `session_id` are session-level, not
    per-scan — the same value for every row — so none of them are in
    `_COLUMNS`. Each is inserted as a lead column when set, in the order
    session_id, sanford_id, location, matching PLAN.md's column list.
    """
    df_export = pd.DataFrame(history)
    df_export = df_export[[c for c in _COLUMNS if c in df_export.columns]]
    if location:
        df_export.insert(0, "Warehouse Location", location)
    if sanford_id:
        df_export.insert(0, "Sanford Id/ Name", sanford_id)
    if session_id:
        df_export.insert(0, "Session ID", session_id)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="Scans")

    return output.getvalue()
