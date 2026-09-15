"""
core/session.py
~~~~~~~~~~~~~~~
Session state and the scan-history model, backed by core/store.py (SQLite)
instead of the old whole-file JSON autosave.

History entries keep the exact key set the original app produced —
`time`, `gtin`, `source`, `status` plus the flattened full_record — because
core/export.py and ui/components.py both select those columns and neither's
contract may change. Three keys are added: `status_key` (canonical status),
`on_hold`, and `Scan Count` (new — surfaced now that a rescan increments a
counter instead of being silently dropped).

Every scan write goes straight to the store (no separate autosave step) — the
store *is* the durable copy, so st.session_state.scan_history is rebuilt from
it on every resume rather than being its own source of truth.
"""

from __future__ import annotations

import logging
from datetime import datetime

import streamlit as st

from engine.lookup import MISS_LABELS

from . import offline_queue, store
from .connectivity import is_connectivity_error
from .logsafe import safe_log_value
from .lookup import STATUS_API, STATUS_CACHE, STATUS_HOLD, STATUS_NOT_FOUND

logger = logging.getLogger(__name__)

# How often a rerun is allowed to actually run the purge sweep, rather than on
# every single rerun (which fires once per scan). Module-level, not
# session-level, so it rate-limits across every concurrent handheld sharing
# this process, not just one browser tab.
_PURGE_INTERVAL_SECONDS = 3600
_last_purge_ts: float = 0.0


def _maybe_purge() -> None:
    """Run store.purge_old_sessions() at most once per _PURGE_INTERVAL_SECONDS.

    This is the "checked ... on app start" half of the plan's retention
    policy, adapted to Streamlit's rerun-per-interaction model: cheap enough
    to call unconditionally from init_session(), but rate-limited so it
    doesn't run a DELETE sweep on literally every scan.
    """
    global _last_purge_ts
    now = datetime.now().timestamp()
    if now - _last_purge_ts < _PURGE_INTERVAL_SECONDS:
        return
    _last_purge_ts = now
    store.purge_old_sessions()


# Full-record field names, mirrored from the flattened history-entry shape
# built in record_scan() (see ui.components._FULL_RECORD_FIELDS). "Scan" is
# excluded — a rescan gets its own raw scan string, not the original's.
_FULL_RECORD_KEYS = (
    "Item", "Company", "Brand", "Description", "GTIN",
    "GTIN UOM", "UOU", "HIBCC", "LAWSON ID", "Lawson UOM",
)

# store.scan column -> UI-facing full_record key. GTIN itself is handled
# separately below since the store's `gtin` column is also its own top-level
# history key.
_ROW_TO_FULL_RECORD = {
    "item": "Item",
    "company": "Company",
    "brand": "Brand",
    "description": "Description",
    "gtin_uom": "GTIN UOM",
    "uou": "UOU",
    "hibcc": "HIBCC",
    "lawson_id": "LAWSON ID",
    "lawson_uom": "Lawson UOM",
}

# Legacy emoji labels the export/history table display for a status_key —
# mirrors core.lookup's _LABEL_* constants, needed here because a DB row only
# stores status_key, not the display label (see _row_to_entry).
_STATUS_LABELS = {
    STATUS_CACHE: "✅ Found",
    STATUS_HOLD: "✅ Found",
    STATUS_API: "🌐 API Found",
    STATUS_NOT_FOUND: "❌ Not Found",
}


def _wall_clock(iso_ts: str) -> str:
    """Format a stored UTC ISO datetime for display, matching the legacy
    `%H:%M:%S` look scans have always shown in the UI/export."""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except (TypeError, ValueError):
        return iso_ts or ""
    return dt.strftime("%H:%M:%S")


def _row_to_entry(row: dict) -> dict:
    """Translate a store.scan row into the history-entry shape the UI and
    export expect (see module docstring)."""
    # Stored raw so it stays aggregatable in SQL; the label is derived here,
    # the same split `status_key` -> `status` already uses above.
    miss_reason = row.get("miss_reason")
    entry = {
        "time": _wall_clock(row["scanned_at"]),
        "gtin": row["gtin"],
        "source": row["source"],
        "status": _STATUS_LABELS.get(row["status_key"], row["status_key"]),
        "status_key": row["status_key"],
        "on_hold": bool(row["on_hold"]),
        "Scan Count": row["scan_count"],
        "Scan": row["raw_scan"] or row["gtin"],
        "GTIN": row["gtin"],
        "miss_reason": miss_reason,
        "Miss Reason": MISS_LABELS.get(miss_reason, "") if miss_reason else "",
        "Miss Detail": row.get("miss_detail") or "",
    }
    for col, label in _ROW_TO_FULL_RECORD.items():
        entry[label] = row.get(col, "")
    # A real row read back from the store is, by definition, already durably
    # saved — see _entry_from_result for the offline counterpart.
    entry["pending_sync"] = False
    return entry


def _entry_from_result(result: dict, scan_count: int) -> dict:
    """Build a scan-history UI entry directly from a resolve_scan() result,
    with no DB round trip.

    Used only when the write to the store had to be queued instead of
    applied immediately (see core/offline_queue.py) — the picker still needs
    to see the scan they just made even though it isn't durably saved yet,
    so this mirrors _row_to_entry's shape from data already in hand rather
    than reading it back from a store that just failed to reach.
    """
    full = result.get("full_record", {})
    miss_reason = result.get("miss_reason")
    entry = {
        "time": result.get("time") or datetime.now().strftime("%H:%M:%S"),
        "gtin": result["gtin"],
        "source": result.get("source_label", result.get("source", "")),
        "status": _STATUS_LABELS.get(result["status_key"], result["status_key"]),
        "status_key": result["status_key"],
        "on_hold": bool(result.get("on_hold")),
        "Scan Count": scan_count,
        "Scan": full.get("Scan") or result["gtin"],
        "GTIN": result["gtin"],
        "miss_reason": miss_reason,
        "Miss Reason": MISS_LABELS.get(miss_reason, "") if miss_reason else "",
        "Miss Detail": result.get("miss_detail") or "",
        "pending_sync": True,
    }
    for label in _FULL_RECORD_KEYS:
        if label != "GTIN":
            entry[label] = full.get(label, "")
    return entry


def init_session() -> None:
    """Initialise session state keys on first run. Idempotent."""
    _maybe_purge()
    # Cheap when the queue is empty (one small file read) and internally
    # rate-limited when it isn't (see offline_queue._FLUSH_COOLDOWN_SECONDS),
    # so this is safe to call unconditionally on every rerun.
    offline_queue.flush()
    if "scan_history" not in st.session_state:
        st.session_state.scan_history = []
    if "last_result" not in st.session_state:
        st.session_state.last_result = None
    if "sound_on" not in st.session_state:
        st.session_state.sound_on = True
    # Set once via the pre-scan gate in app.py, then held for the rest of the
    # browser session.
    if "warehouse_location" not in st.session_state:
        st.session_state.warehouse_location = None
    if "sanford_id" not in st.session_state:
        st.session_state.sanford_id = None
    # Identifies this session's row in the store (core/store.py) and is
    # carried in the URL query params so a resumed session can find its way
    # back to it.
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    # Increments once per scan. The JS runtime uses it to fire an alert tone
    # exactly once per scan rather than on every incidental rerun.
    if "scan_nonce" not in st.session_state:
        st.session_state.scan_nonce = 0


def start_session(sanford_id: str, location: str) -> None:
    """Begin a fresh scan session, creating its row in the store.

    The row is written immediately — before the first scan — so a refresh in
    the window between entering the start-form and scanning the first item
    can still resume from the URL's `sid` instead of dropping back to the
    start gate. See app.py's resume gate and core/store.create_session.

    The id is minted here (store.new_session_id() is a pure function, no DB
    call) rather than inside store.create_session(), specifically so scanning
    can start immediately even if the INSERT below has to be queued for a
    transient Neon outage (see core/offline_queue.py). A refresh before that
    queued write lands resumes via resume_pending_session() instead of
    store.get_session() (see app.py's resume gate) — the offline queue is the
    only place that row exists until it syncs.
    """
    session_id = store.new_session_id()
    st.session_state.sanford_id = sanford_id
    st.session_state.warehouse_location = location
    try:
        store.create_session(sanford_id, location, session_id=session_id)
    except Exception as exc:
        if not is_connectivity_error(exc):
            raise
        logger.warning("Neon unreachable starting session %s; queuing.", session_id, exc_info=True)
        offline_queue.enqueue(
            "create_session",
            {"sanford_id": sanford_id, "location": location, "session_id": session_id},
        )
    st.session_state.session_id = session_id
    st.session_state.scan_history = []
    st.session_state.last_result = None


def history_for_session(session_id: str) -> list[dict]:
    """This session's full scan history in the UI/export-facing shape (see
    _row_to_entry). Public because both app.py's resume gate and the monitor
    board's drill-in (pages/board.py) need the identical translation from
    store rows — the board has no st.session_state of its own to rehydrate
    into, it just renders this list directly."""
    return [_row_to_entry(r) for r in store.list_scans(session_id)]


def resume_session(session_id: str, session_row: dict) -> None:
    """Rehydrate session state from a store row found via the URL's `sid`."""
    st.session_state.session_id = session_id
    st.session_state.sanford_id = session_row["sanford_id"]
    st.session_state.warehouse_location = session_row["location"]
    st.session_state.scan_history = history_for_session(session_id)
    st.session_state.last_result = None


def resume_pending_session(session_id: str) -> dict | None:
    """Like resume_session(), but rehydrates from the offline queue instead
    of the store — for a session whose create_session write (and any scans
    made before it synced) haven't reached Neon yet.

    Returns the reconstructed row (same shape store.get_session() would
    have returned) if a pending create_session exists for this id, so the
    caller (app.py's resume gate) can drive both paths the same way. Returns
    None if there's nothing queued for this id either — a genuinely unknown
    or already-synced-and-since-purged session.
    """
    pending = offline_queue.find_pending_session(session_id)
    if pending is None:
        return None
    st.session_state.session_id = session_id
    st.session_state.sanford_id = pending["sanford_id"]
    st.session_state.warehouse_location = pending["location"]
    st.session_state.scan_history = [
        _entry_from_result(result, scan_count=1)
        for result in offline_queue.pending_scans_for_session(session_id)
    ]
    st.session_state.last_result = None
    return pending


def end_session() -> None:
    """End this session in the store (normal, handheld-only path) and reset
    local state back to the start gate.

    Local state resets unconditionally either way — even if the UPDATE below
    has to be queued for a transient Neon outage, the picker is done with
    this device for this session, and there is no local state left to fall
    back to anyway. The board will show the session as still ACTIVE until
    the queued end_session syncs.
    """
    if st.session_state.session_id:
        try:
            store.end_session(st.session_state.session_id)
        except Exception as exc:
            if not is_connectivity_error(exc):
                raise
            logger.warning(
                "Neon unreachable ending session %s; queuing.",
                st.session_state.session_id, exc_info=True,
            )
            offline_queue.enqueue("end_session", {"session_id": st.session_state.session_id})
    st.session_state.sanford_id = None
    st.session_state.warehouse_location = None
    st.session_state.session_id = None
    st.session_state.scan_history = []
    st.session_state.last_result = None


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
    """Persist a resolved scan: insert its row in the store and append the
    UI-shaped entry to the in-memory history.

    If Neon can't be reached right now, the write is queued instead of
    raised (see core/offline_queue.py) and the history entry is built
    locally from `result` — the picker keeps scanning uninterrupted, with
    `last_result["persisted"]` telling app.py to show that this one hasn't
    synced yet. A non-connectivity error (a real bug, a constraint
    violation) still raises normally rather than being masked as "offline".
    """
    session_id = st.session_state.session_id
    persisted = True
    try:
        store.record_scan(session_id, result)
        row = store.find_scan(session_id, result["gtin"])
        entry = _row_to_entry(row)
    except Exception as exc:
        if not is_connectivity_error(exc):
            raise
        logger.warning(
            "Neon unreachable recording scan %s; queuing.",
            safe_log_value(result.get("gtin")), exc_info=True,
        )
        offline_queue.enqueue("record_scan", {"session_id": session_id, "result": result})
        entry = _entry_from_result(result, scan_count=1)
        persisted = False

    st.session_state.last_result = {**result, "duplicate": False, "persisted": persisted}
    st.session_state.scan_history.append(entry)
    st.session_state.scan_nonce += 1


def record_duplicate_scan(raw_gtin: str, gtin: str, existing: dict) -> None:
    """Re-show an already-scanned item: increment its Scan Count in the
    store, update the matching in-memory history entry in place, and flag
    the result as a duplicate for the UI banner.

    Unlike the old JSON-era behaviour (which appended nothing and left the
    history untouched), a rescan is no longer invisible — see PLAN.md
    "Duplicate handling". The KPI math in compute_stats() is still untouched
    by a rescan: it counts distinct history entries, and a rescan mutates an
    existing entry rather than adding one.

    Same offline handling as record_scan(): a connectivity failure queues
    the increment instead of raising, and the count shown locally is
    incremented from what's already in session_state rather than read back
    from the store.
    """
    session_id = st.session_state.session_id
    persisted = True
    try:
        updated_row = store.increment_scan(session_id, gtin)
        updated_entry = _row_to_entry(updated_row)
        new_scan_count = updated_row["scan_count"]
    except Exception as exc:
        if not is_connectivity_error(exc):
            raise
        logger.warning(
            "Neon unreachable incrementing scan %s; queuing.", safe_log_value(gtin), exc_info=True
        )
        offline_queue.enqueue("increment_scan", {"session_id": session_id, "gtin": gtin})
        new_scan_count = int(existing.get("Scan Count") or 1) + 1
        updated_entry = {**existing, "Scan Count": new_scan_count, "pending_sync": True}
        persisted = False

    for i, entry in enumerate(st.session_state.scan_history):
        if entry.get("gtin") == gtin:
            st.session_state.scan_history[i] = updated_entry
            break

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
        # Carried from the stored row rather than re-diagnosed: a rescan of an
        # unmatched item is the same miss, and re-running diagnose() here would
        # cost a lookup to reach an answer already on the row.
        "miss_reason": existing.get("miss_reason"),
        "miss_label": existing.get("Miss Reason", ""),
        "miss_detail": existing.get("Miss Detail", ""),
        "duplicate": True,
        "scan_count": new_scan_count,
        "persisted": persisted,
    }
    st.session_state.scan_nonce += 1


def clear_result() -> None:
    """Drop the current result. Bound to the Esc key via a hidden button."""
    st.session_state.last_result = None


def compute_stats(history: list[dict]) -> dict[str, int]:
    """Derive the session KPI counts from the scan history.

    Note: `cache` counts every contract-line hit *including* on-hold items, so
    cache + api + not_found == total. `on_hold` is an overlay on the cache
    count, not a fifth mutually-exclusive bucket. A rescan does not change
    these counts — it mutates an existing entry's Scan Count rather than
    adding a new one, so `total` stays "distinct GTINs scanned", not "total
    scan events".
    """
    keys = [e.get("status_key") for e in history]
    return {
        "total": len(history),
        "cache": sum(1 for k in keys if k in (STATUS_CACHE, STATUS_HOLD)),
        "api": sum(1 for k in keys if k == STATUS_API),
        "not_found": sum(1 for k in keys if k == STATUS_NOT_FOUND),
        "on_hold": sum(1 for k in keys if k == STATUS_HOLD),
    }
