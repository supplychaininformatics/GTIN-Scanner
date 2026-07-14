"""
core/session.py
~~~~~~~~~~~~~~~
Session state and the scan-history model.

History entries keep the exact key set the original app produced —
`time`, `gtin`, `source`, `status` plus the flattened full_record — because
core/export.py selects those columns and the exported workbook must not change.
Two keys are *added* for the UI only: `status_key` (canonical status) and
`on_hold`. The export ignores them.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from .lookup import STATUS_API, STATUS_CACHE, STATUS_HOLD, STATUS_NOT_FOUND

# Full-record field names, mirrored from the flattened history-entry shape
# built in record_scan() (see ui.components._FULL_RECORD_FIELDS). "Scan" is
# excluded — a rescan gets its own raw scan string, not the original's.
_FULL_RECORD_KEYS = (
    "Item", "Company", "Brand", "Description", "GTIN",
    "GTIN UOM", "UOU", "HIBCC", "LAWSON ID", "Lawson UOM",
)


def init_session() -> None:
    """Initialise session state keys on first run. Idempotent."""
    if "scan_history" not in st.session_state:
        st.session_state.scan_history = []
    if "last_result" not in st.session_state:
        st.session_state.last_result = None
    if "sound_on" not in st.session_state:
        st.session_state.sound_on = True
    # Increments once per scan. The JS runtime uses it to fire an alert tone
    # exactly once per scan rather than on every incidental rerun.
    if "scan_nonce" not in st.session_state:
        st.session_state.scan_nonce = 0


def find_duplicate(gtin: str) -> dict | None:
    """Return this session's existing history entry for `gtin`, if any.

    GTIN — not the raw scan string — is the dedupe key, so a composite GS1
    barcode and a bare 14-digit GTIN for the same item are recognised as the
    same item.
    """
    for entry in st.session_state.scan_history:
        if entry.get("gtin") == gtin:
            return entry
    return None


def record_scan(result: dict) -> None:
    """Persist a resolved scan as the current result and append it to history."""
    st.session_state.last_result = {**result, "duplicate": False}

    entry = {
        "time": result["time"],
        "gtin": result["gtin"],
        "source": result["source_label"],
        "status": result["status_label"],
        "status_key": result["status_key"],
        "on_hold": result["on_hold"],
    }
    entry.update(result["full_record"])
    st.session_state.scan_history.append(entry)
    st.session_state.scan_nonce += 1


def record_duplicate_scan(raw_gtin: str, gtin: str, existing: dict) -> None:
    """Re-show an already-scanned item without touching history or any KPI.

    Nothing is appended to scan_history, so compute_stats() — and the Excel
    export, which is built straight from history — are both untouched by a
    rescan. The item's known data is reused from `existing` so this never
    needs a cache/API lookup.
    """
    st.session_state.last_result = {
        "gtin": gtin,
        "time": datetime.now().strftime("%H:%M:%S"),
        "full_record": {
            **{k: existing.get(k, "") for k in _FULL_RECORD_KEYS},
            "Scan": raw_gtin,
        },
        "on_hold": existing.get("on_hold", False),
        "status_key": existing.get("status_key"),
        "status_label": existing.get("status"),
        "source_label": existing.get("source"),
        "source": None,
        "duplicate": True,
    }
    st.session_state.scan_nonce += 1


def clear_result() -> None:
    """Drop the current result. Bound to the Esc key via a hidden button."""
    st.session_state.last_result = None


def compute_stats(history: list[dict]) -> dict[str, int]:
    """Derive the session KPI counts from the scan history.

    Note: `cache` counts every contract-line hit *including* on-hold items, so
    cache + api + not_found == total. `on_hold` is an overlay on the cache
    count, not a fifth mutually-exclusive bucket.
    """
    keys = [e.get("status_key") for e in history]
    return {
        "total": len(history),
        "cache": sum(1 for k in keys if k in (STATUS_CACHE, STATUS_HOLD)),
        "api": sum(1 for k in keys if k == STATUS_API),
        "not_found": sum(1 for k in keys if k == STATUS_NOT_FOUND),
        "on_hold": sum(1 for k in keys if k == STATUS_HOLD),
    }
