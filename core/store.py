"""
core/store.py
~~~~~~~~~~~~~
SQLite-backed persistence for scan sessions, replacing the old whole-file
JSON autosave (core/autosave.py, removed).

Why SQLite over JSON-per-session: the monitor board needs to list every
session across every handheld concurrently, and the JSON approach had no way
to do that without scanning every file in data/cache/sessions/ on every
board rerun. An append/upsert-per-scan SQLite store (WAL mode, so readers
never block a writer) makes many concurrent handhelds and one board safe
and cheap at once.

Session lifecycle: a session is minted handheld-side (see core/session.py:
start_session) and is ACTIVE until either the handheld ends it (normal path)
or the board/admin force-ends it (escape hatch for a dropped/dead device —
see force_end_session). STALE is a derived label, not a stored status: any
ACTIVE session with no scan in the last 4 hours reads as stale to callers,
without a background job to keep it in sync.

Retention: sessions and their scans older than RETENTION_DAYS are purged by
purge_old_sessions(), which core/session.py calls at most once per
_PURGE_INTERVAL_SECONDS (see _maybe_purge) so a purge sweep never runs on
literally every Streamlit rerun.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from data.loader import CACHE_PATH

logger = logging.getLogger(__name__)

DB_PATH = CACHE_PATH.parent / "gtin_scanner.db"

STATUS_ACTIVE = "active"
STATUS_ENDED = "ended"

# A session with no scan in this long reads as STALE to callers (board,
# admin) without being a stored status of its own — see session_is_stale().
STALE_AFTER = timedelta(hours=4)

RETENTION_DAYS = 3

# Full-record field names, mirrored from the flattened history-entry shape
# built in core/lookup.resolve_scan(). Column order matches the `scan` table.
_FULL_RECORD_COLUMNS = (
    ("item", "Item"),
    ("company", "Company"),
    ("brand", "Brand"),
    ("description", "Description"),
    ("gtin_uom", "GTIN UOM"),
    ("uou", "UOU"),
    ("hibcc", "HIBCC"),
    ("lawson_id", "LAWSON ID"),
    ("lawson_uom", "Lawson UOM"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session (
    session_id   TEXT PRIMARY KEY,
    sanford_id   TEXT,
    location     TEXT,
    status       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    ended_at     TEXT
);

CREATE TABLE IF NOT EXISTS scan (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES session(session_id),
    scanned_at    TEXT NOT NULL,
    last_scanned  TEXT NOT NULL,
    scan_count    INTEGER NOT NULL DEFAULT 1,
    gtin          TEXT,
    raw_scan      TEXT,
    status_key    TEXT,
    source        TEXT,
    on_hold       INTEGER,
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

CREATE INDEX IF NOT EXISTS idx_scan_dedupe ON scan(session_id, gtin);
CREATE INDEX IF NOT EXISTS idx_scan_session ON scan(session_id);
CREATE INDEX IF NOT EXISTS idx_session_created ON session(created_at);
"""


def _utcnow_iso() -> str:
    """Full ISO datetime, UTC, second precision — matches every column that
    stores a timestamp (created_at, ended_at, scanned_at, last_scanned)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_session_id() -> str:
    """A short, URL-friendly id — enough entropy that collisions never matter."""
    return uuid.uuid4().hex[:12]


_initialized = False


def _connect() -> sqlite3.Connection:
    """Open a connection with WAL mode + row access by column name.

    WAL mode is set per-connection but persists in the database file once
    written, so this only has real effect on the very first connection —
    it's set on every connection anyway because that's the documented way
    to ensure it, and it's a cheap PRAGMA to repeat.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _cursor() -> Iterator[sqlite3.Cursor]:
    """One connection per call, committed on success, rolled back on error.

    SQLite connections are cheap and the app is Streamlit (one script rerun
    per interaction) — there is no long-lived process to pool a connection
    against, so open/close per operation is the simplest correct thing.
    """
    global _initialized
    conn = _connect()
    try:
        if not _initialized:
            conn.executescript(_SCHEMA)
            _initialized = True
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Session lifecycle ───────────────────────────────────────────────────────
def create_session(sanford_id: str, location: str) -> str:
    """Insert a new ACTIVE session and return its id.

    Called handheld-side at form submit — see core/session.start_session.
    The row is written immediately, before the first scan, so a refresh in
    the window between form submit and the first scan can still resume via
    the URL's `sid` instead of dropping back to the start gate.
    """
    session_id = new_session_id()
    now = _utcnow_iso()
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO session (session_id, sanford_id, location, status, "
            "created_at, ended_at) VALUES (?, ?, ?, ?, ?, NULL)",
            (session_id, sanford_id, location, STATUS_ACTIVE, now),
        )
    return session_id


def get_session(session_id: str) -> dict | None:
    """Return the session row as a dict, or None if it doesn't exist."""
    with _cursor() as cur:
        row = cur.execute(
            "SELECT * FROM session WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def end_session(session_id: str) -> None:
    """Normal end path — handheld only. Marks ENDED with a timestamp."""
    with _cursor() as cur:
        cur.execute(
            "UPDATE session SET status = ?, ended_at = ? WHERE session_id = ?",
            (STATUS_ENDED, _utcnow_iso(), session_id),
        )


def force_end_session(session_id: str) -> bool:
    """Escape hatch for a dead/dropped handheld — board or admin only.

    Same effect as end_session(); the caller is responsible for writing an
    audit log entry (see core/admin.log_audit_event, pages/admin.py), the
    same pattern the existing manual-refresh audit trail uses.

    Returns:
        True if a session was found and force-ended, False if no such
        session existed (already gone / bad id) — lets the caller distinguish
        "nothing to do" from a real failure without raising.
    """
    with _cursor() as cur:
        cur.execute(
            "UPDATE session SET status = ?, ended_at = ? "
            "WHERE session_id = ? AND status = ?",
            (STATUS_ENDED, _utcnow_iso(), session_id, STATUS_ACTIVE),
        )
        return cur.rowcount > 0


def session_is_stale(session: dict, last_scan_at: str | None) -> bool:
    """True if an ACTIVE session has had no scan in over STALE_AFTER.

    STALE is a derived, display-only label (see module docstring) — a
    session with zero scans yet is judged against its created_at instead,
    so a picker who just started but hasn't scanned yet isn't flagged stale
    the moment they open the app.
    """
    if session["status"] != STATUS_ACTIVE:
        return False
    anchor = last_scan_at or session["created_at"]
    try:
        anchor_dt = datetime.fromisoformat(anchor)
    except ValueError:
        return False
    if anchor_dt.tzinfo is None:
        anchor_dt = anchor_dt.replace(tzinfo=UTC)
    return datetime.now(UTC) - anchor_dt > STALE_AFTER


# ── Sessions listing (monitor board) ────────────────────────────────────────
def list_sessions(since_days: int | None = 1) -> list[dict]:
    """Sessions newest-first, each annotated with scan_count/last_scanned.

    Args:
        since_days: Only sessions created within this many days (board
            default view = today, i.e. since_days=1). Pass None for the full
            retention window (board's "show more" filter, up to
            RETENTION_DAYS since anything older is purged anyway).

    Returns:
        One dict per session: every `session` column plus `scan_count`
        (0 if nothing scanned yet) and `last_scanned` (None if none).
    """
    query = """
        SELECT
            s.*,
            COALESCE(SUM(sc.scan_count), 0) AS scan_count,
            MAX(sc.last_scanned) AS last_scanned
        FROM session s
        LEFT JOIN scan sc ON sc.session_id = s.session_id
    """
    params: tuple = ()
    if since_days is not None:
        cutoff = (datetime.now(UTC) - timedelta(days=since_days)).isoformat()
        query += " WHERE s.created_at >= ?"
        params = (cutoff,)
    query += " GROUP BY s.session_id ORDER BY s.created_at DESC"

    with _cursor() as cur:
        rows = cur.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ── Scans ────────────────────────────────────────────────────────────────────
def list_scans(session_id: str) -> list[dict]:
    """This session's scans, oldest-first (matches the old JSON history order)."""
    with _cursor() as cur:
        rows = cur.execute(
            "SELECT * FROM scan WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def find_scan(session_id: str, gtin: str) -> dict | None:
    """This session's existing scan row for `gtin`, if any — the dedupe check."""
    with _cursor() as cur:
        row = cur.execute(
            "SELECT * FROM scan WHERE session_id = ? AND gtin = ?",
            (session_id, gtin),
        ).fetchone()
    return dict(row) if row else None


def record_scan(session_id: str, result: dict) -> None:
    """Insert a new scan row. Caller (core/session.py) has already checked
    find_scan() and only calls this on a first-time GTIN for the session —
    a rescan goes through increment_scan() instead."""
    now = _utcnow_iso()
    full_record = result["full_record"]
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO scan (session_id, scanned_at, last_scanned, scan_count, "
            "gtin, raw_scan, status_key, source, on_hold, item, company, brand, "
            "description, gtin_uom, uou, hibcc, lawson_id, lawson_uom) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                now,
                now,
                result["gtin"],
                full_record.get("Scan", result["gtin"]),
                result["status_key"],
                result["source_label"],
                int(bool(result["on_hold"])),
                *(full_record.get(label, "") for _, label in _FULL_RECORD_COLUMNS),
            ),
        )


def increment_scan(session_id: str, gtin: str) -> dict:
    """Rescan of a GTIN already in this session: bump scan_count, refresh
    last_scanned, and return the updated row so the caller can re-show it.
    """
    now = _utcnow_iso()
    with _cursor() as cur:
        cur.execute(
            "UPDATE scan SET scan_count = scan_count + 1, last_scanned = ? "
            "WHERE session_id = ? AND gtin = ?",
            (now, session_id, gtin),
        )
        row = cur.execute(
            "SELECT * FROM scan WHERE session_id = ? AND gtin = ?",
            (session_id, gtin),
        ).fetchone()
    return dict(row)


# ── Retention ────────────────────────────────────────────────────────────────
def purge_old_sessions() -> int:
    """Delete sessions (and their scans) older than RETENTION_DAYS.

    Returns the number of sessions purged. See core/session.py's
    _maybe_purge for the rate-limited caller — this function itself does no
    rate limiting, so it's safe to call directly from a script/test too.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=RETENTION_DAYS)).isoformat()
    with _cursor() as cur:
        ids = [
            r[0]
            for r in cur.execute(
                "SELECT session_id FROM session WHERE created_at < ?", (cutoff,)
            ).fetchall()
        ]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        cur.execute(f"DELETE FROM scan WHERE session_id IN ({placeholders})", ids)
        cur.execute(f"DELETE FROM session WHERE session_id IN ({placeholders})", ids)
    if ids:
        logger.info("Purged %d session(s) older than %d days.", len(ids), RETENTION_DAYS)
    return len(ids)
