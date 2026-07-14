"""
core/export.py
~~~~~~~~~~~~~~
Excel session export.

Relocated verbatim from app.py. The produced workbook is byte-for-byte the same
as before the UI rebuild: same sheet name, same column set and order, same
filename. Only the call site moved.
"""

from __future__ import annotations

import io

import pandas as pd

EXPORT_FILENAME = "gtin_scan_history.xlsx"
EXPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Column order as originally written. Keys added for the UI (status_key,
# on_hold) are deliberately absent, so the exported sheet is unchanged.
_COLUMNS = [
    "time", "source", "status", "Scan", "Item", "Company", "Brand",
    "Description", "GTIN", "GTIN UOM", "UOU", "HIBCC", "LAWSON ID", "Lawson UOM",
]


def build_workbook(history: list[dict]) -> bytes:
    """Serialise the session scan history to an .xlsx byte string."""
    df_export = pd.DataFrame(history)
    df_export = df_export[[c for c in _COLUMNS if c in df_export.columns]]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="Scans")

    return output.getvalue()
