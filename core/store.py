"""
core/store.py
~~~~~~~~~~~~~
Postgres-backed persistence for scan sessions, replacing the SQLite store
that preceded it (which in turn replaced a whole-file JSON autosave).

Why Postgres over SQLite: SQLite lived on the container's local disk, and
Streamlit Cloud restarts the container freely — every restart took the scan
history with it. The database now lives in Neon, outside the app's lifecycle,
so a restart is invisible to pickers mid-shift.

The schema is NOT created here. It lives in migrations/001_initial.sql and is
applied out-of-band (see that file's header). A missing table surfaces as
psycopg.errors.UndefinedTable, which means the migration has not been run
against whatever database NEON_DATABASE_URL points at.

Session lifecycle: a session is minted handheld-side (see core/session.py:
start_session) and is ACTIVE until either the handheld ends it (normal path)
or the board/admin force-ends it (escape hatch for a dropped/dead device —
see force_end_session). STALE is a derived label, not a stored status: any
ACTIVE session with no scan in the last 4 hours reads as stale to callers,
without a background job to keep it in sync.

Retention: the authoritative sweep is a daily GitHub Action
(.github/workflows/purge-expired.yml) which runs whether or not anybody has
the app open. purge_old_sessions() is kept as a belt-and-braces in-app sweep
on the same window, called at most once per _PURGE_INTERVAL_SECONDS by
core/session.py's _maybe_purge.

Timestamps: the database columns are timestamptz, but every function here
returns them as ISO-8601 UTC strings — the same shape the SQLite store
returned, because five call sites across core/, ui/ and pages/ depend on it
(two of them by string-slicing, e.g. created_at[:10] in core/export.py).
Storing real timestamps is what matters: it is what lets retention and the
board's since_days filter use interval arithmetic instead of leaning on
ISO-8601 happening to sort lexicographically. Converting back at this
boundary keeps that win without rippling through the UI. See _iso().
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import secrets

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_ENDED = "ended"

# A session with no scan in this long reads as STALE to callers (board,
# admin) without being a stored status of its own — see session_is_stale().
STALE_AFTER = timedelta(hours=4)

# Must stay in sync with retention_days in .github/workflows/purge-expired.yml.
# They are two independent copies of one policy and nothing reconciles them.
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

# Columns whose values come back from psycopg as datetime and are handed to
# callers as ISO-8601 strings instead — see the module docstring.
_TIMESTAMP_COLUMNS = frozenset(
    {"created_at", "ended_at", "scanned_at", "last_scanned"}
)


def _utcnow() -> datetime:
    """Now, UTC, second precision.

    Second precision is deliberate: it is what the SQLite store wrote, and
    _iso() truncates on the way back out anyway, so keeping it here means a
    value read back matches the value written rather than differing in a
    microsecond field nothing displays.
    """
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    """A timestamptz as the ISO-8601 UTC string callers expect.

    Normalises to UTC first: psycopg renders timestamptz in the connection's
    timezone, so without this the offset would follow server configuration
    rather than always being +00:00 — and core/export.py slices the first ten
    characters off this string to build a filename.
    """
    if not isinstance(value, datetime):
        return value
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def _row(row: dict | None) -> dict | None:
    """One result row with its timestamp columns converted to ISO strings."""
    if row is None:
        return None
    return {
        k: (_iso(v) if k in _TIMESTAMP_COLUMNS else v) for k, v in row.items()
    }


def new_session_id() -> str:
    """A short, URL-friendly id — enough entropy that collisions never matter."""
    return uuid.uuid4().hex[:12]


# ── Connection pool ──────────────────────────────────────────────────────────
_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _conninfo() -> str:
    """The Neon connection string: env var, then OS keychain, then Streamlit
    secrets — see core/secrets.py for why that order and what each source is
    for.

    Environment first so the same module works unchanged in a script, a test
    or CI, where there is no Streamlit runtime to read secrets from and no
    interactive OS session to hold a keychain. streamlit is imported lazily
    for that same reason — importing this module must not require it.
    """
    url = (
        os.environ.get("NEON_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or secrets.from_keyring("neon_database_url")
    )
    if not url:
        try:
            import streamlit as st  # noqa: PLC0415

            url = str(st.secrets["neon"]["url"])
        except Exception as exc:  # noqa: BLE001 — any failure here means the same thing
            raise RuntimeError(
                "No database connection string. Set NEON_DATABASE_URL, store it "
                "in the OS keychain (see scripts/store_secret.py), or add a "
                "[neon] url = ... entry to .streamlit/secrets.toml "
                "(see .streamlit/secrets.toml.example)."
            ) from exc

    # sslmode=require (+ channel_binding=require, when present) has to survive
    # every copy/paste of this value between .env, Streamlit Cloud secrets and
    # .streamlit/secrets.toml — nothing else in this module re-asserts TLS, so
    # a connection string pasted from a different Neon tab without it would
    # otherwise silently downgrade to an unencrypted session. Fail loudly
    # instead. See ASVS-AUDIT.md finding #9 / ASVS-COMPLIANCE.md V9.
    if "sslmode=require" not in url and "sslmode=verify-full" not in url:
        raise RuntimeError(
            "The Neon connection string does not require TLS "
            "(missing sslmode=require). Refusing to connect — copy the "
            "connection string from Neon's 'Pooled connection' tab, which "
            "includes sslmode=require by default."
        )

    return url


def _get_pool() -> ConnectionPool:
    """The process-wide connection pool, created on first use.

    A module-level pool is what makes this workable under Streamlit: the
    script reruns on every interaction, but module import happens once per
    process, so the pool outlives reruns instead of a fresh connection being
    opened per scan. The lock guards the one-time construction against
    Streamlit serving two sessions on different threads at once.
    """
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        # Re-checked inside the lock: another thread may have built it while
        # this one waited.
        if _pool is None:
            conninfo = _conninfo()
            # Host only — never the full conninfo, which carries the
            # password — so this line is safe to leave at INFO for IT to
            # monitor the egress point (endpoint + outcome + the log
            # formatter's own timestamp), per ASVS-AUDIT.md item 7.
            host = urlparse(conninfo).hostname or "(unknown host)"
            logger.info("Opening Neon connection pool to %s.", host)
            try:
                _pool = ConnectionPool(
                    conninfo,
                    min_size=1,
                    # Small on purpose. Handhelds are read-light and
                    # write-tiny, and Neon's free tier is not somewhere to
                    # hoard connections.
                    max_size=5,
                    kwargs={"row_factory": dict_row},
                    # Neon scales its compute to zero when idle, which drops
                    # pooled connections without the pool noticing. check
                    # runs a liveness probe before handing one out, so the
                    # first scan after a quiet spell reconnects instead of
                    # raising.
                    check=ConnectionPool.check_connection,
                    max_idle=300,
                    timeout=20,
                    open=False,
                )
                _pool.open()
            except Exception:
                logger.error("Failed to open Neon connection pool to %s.", host, exc_info=True)
                raise
            logger.info("Neon connection pool to %s is open.", host)
            # The pool's worker threads are not daemons, so without an
            # explicit close the interpreter blocks on each of them at
            # shutdown and logs a "couldn't stop thread" warning per thread
            # after a 5s wait. Streamlit Cloud restarts containers routinely,
            # and that is exactly when the delay would be felt.
            atexit.register(_close_pool)
    return _pool


def _close_pool() -> None:
    """Close the pool and let the next call build a fresh one.

    Registered with atexit; also useful directly in a test or script that
    wants to drop connections without ending the process.
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def _cursor() -> Iterator[psycopg.Cursor]:
    """A pooled cursor, committed on success and rolled back on error.

    pool.connection() owns the transaction: it commits when the block exits
    cleanly and rolls back if it raises, which is the same contract the
    SQLite version's open/commit/close provided.
    """
    with _get_pool().connection() as conn, conn.cursor() as cur:
        yield cur


# ── Session lifecycle ───────────────────────────────────────────────────────
def create_session(sanford_id: str, location: str, session_id: str | None = None) -> str:
    """Insert a new ACTIVE session and return its id.

    Called handheld-side at form submit — see core/session.start_session.
    The row is written immediately, before the first scan, so a refresh in
    the window between form submit and the first scan can still resume via
    the URL's `sid` instead of dropping back to the start gate.

    `session_id`: pass an id already minted elsewhere instead of generating
    one here. Used by the offline-write-queue replay path (core/session.py
    generates the id locally so scanning can continue before this INSERT has
    actually landed, then replays this exact call once Neon is reachable
    again) — omit it for the normal online path, which mints its own.
    """
    session_id = session_id or new_session_id()
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO session (session_id, sanford_id, location, status, "
            "created_at, ended_at) VALUES (%s, %s, %s, %s, %s, NULL)",
            (session_id, sanford_id, location, STATUS_ACTIVE, _utcnow()),
        )
    return session_id


def get_session(session_id: str) -> dict | None:
    """Return the session row as a dict, or None if it doesn't exist."""
    with _cursor() as cur:
        cur.execute("SELECT * FROM session WHERE session_id = %s", (session_id,))
        return _row(cur.fetchone())


def end_session(session_id: str) -> None:
    """Normal end path — handheld only. Marks ENDED with a timestamp."""
    with _cursor() as cur:
        cur.execute(
            "UPDATE session SET status = %s, ended_at = %s WHERE session_id = %s",
            (STATUS_ENDED, _utcnow(), session_id),
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
            "UPDATE session SET status = %s, ended_at = %s "
            "WHERE session_id = %s AND status = %s",
            (STATUS_ENDED, _utcnow(), session_id, STATUS_ACTIVE),
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
    except (TypeError, ValueError):
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
    # Grouping by the primary key alone is enough for s.* to be selectable —
    # Postgres recognises that every other session column is functionally
    # dependent on it.
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
        query += " WHERE s.created_at >= %s"
        params = (datetime.now(UTC) - timedelta(days=since_days),)
    query += " GROUP BY s.session_id ORDER BY s.created_at DESC"

    with _cursor() as cur:
        cur.execute(query, params)
        return [_row(r) for r in cur.fetchall()]


# ── Scans ────────────────────────────────────────────────────────────────────
def list_scans(session_id: str) -> list[dict]:
    """This session's scans, oldest-first (matches the old JSON history order)."""
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM scan WHERE session_id = %s ORDER BY id ASC",
            (session_id,),
        )
        return [_row(r) for r in cur.fetchall()]


def find_scan(session_id: str, gtin: str) -> dict | None:
    """This session's existing scan row for `gtin`, if any — the dedupe check."""
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM scan WHERE session_id = %s AND gtin = %s",
            (session_id, gtin),
        )
        return _row(cur.fetchone())


def _insert_scan(cur: psycopg.Cursor, session_id: str, result: dict, at: datetime) -> None:
    full_record = result["full_record"]
    cur.execute(
        "INSERT INTO scan (session_id, scanned_at, last_scanned, scan_count, "
        "gtin, raw_scan, status_key, source, on_hold, miss_reason, "
        "miss_detail, item, company, brand, "
        "description, gtin_uom, uou, hibcc, lawson_id, lawson_uom) "
        "VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s, %s)",
        (
            session_id,
            at,
            at,
            result["gtin"],
            full_record.get("Scan", result["gtin"]),
            result["status_key"],
            result["source_label"],
            bool(result["on_hold"]),
            # NULL on a contract hit — see migrations/002_miss_reason.sql.
            # .get() rather than [] so a caller building a result dict by
            # hand (tests, the duplicate path) is not forced to carry keys
            # that only ever describe a miss.
            result.get("miss_reason"),
            result.get("miss_detail"),
            *(full_record.get(label, "") for _, label in _FULL_RECORD_COLUMNS),
        ),
    )


def record_scan(session_id: str, result: dict) -> None:
    """Insert a new scan row. Caller (core/session.py) has already checked
    find_scan() and only calls this on a first-time GTIN for the session —
    a rescan goes through increment_scan() instead."""
    with _cursor() as cur:
        _insert_scan(cur, session_id, result, _utcnow())


def increment_scan(session_id: str, gtin: str) -> dict:
    """Rescan of a GTIN already in this session: bump scan_count, refresh
    last_scanned, and return the updated row so the caller can re-show it.
    """
    with _cursor() as cur:
        # RETURNING gets the updated row in the same round trip the UPDATE
        # already costs, where SQLite needed a follow-up SELECT.
        cur.execute(
            "UPDATE scan SET scan_count = scan_count + 1, last_scanned = %s "
            "WHERE session_id = %s AND gtin = %s RETURNING *",
            (_utcnow(), session_id, gtin),
        )
        return _row(cur.fetchone())


# ── Device API (sync_api/) ───────────────────────────────────────────────────
# Everything below backs the REST service handhelds sync through. Kept apart
# from the Streamlit-facing functions above because its contract differs:
# every write is idempotent (a device retries a batch until it hears back) and
# every write is checked against the calling device's identity.
SYNC_APPLIED = "applied"
SYNC_DUPLICATE = "duplicate"


class SyncRejected(Exception):
    """This op can never succeed as sent — the device should drop it."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SyncRetry(Exception):
    """This op could not be applied right now but may succeed later."""


def create_device(device_id: str, label: str, token_hash: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO api_device (device_id, label, token_hash, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (device_id, label, token_hash, _utcnow()),
        )


def revoke_device(device_id: str) -> bool:
    """Revoke a device's token. True if an active device was revoked."""
    with _cursor() as cur:
        cur.execute(
            "UPDATE api_device SET revoked_at = %s WHERE device_id = %s AND revoked_at IS NULL",
            (_utcnow(), device_id),
        )
        return cur.rowcount > 0


def list_devices() -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT device_id, label, created_at, revoked_at, last_seen_at "
            "FROM api_device ORDER BY created_at"
        )
        return [
            {k: (_iso(v) if isinstance(v, datetime) else v) for k, v in r.items()}
            for r in cur.fetchall()
        ]


def device_for_token_hash(token_hash: str) -> dict | None:
    """The active (non-revoked) device owning this token hash, if any."""
    with _cursor() as cur:
        cur.execute(
            "SELECT device_id, label FROM api_device "
            "WHERE token_hash = %s AND revoked_at IS NULL",
            (token_hash,),
        )
        return cur.fetchone()


def touch_device(device_id: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE api_device SET last_seen_at = %s WHERE device_id = %s",
            (_utcnow(), device_id),
        )


def scan_exists(session_id: str, gtin: str) -> bool:
    return find_scan(session_id, gtin) is not None


def _owned_session_row(cur: psycopg.Cursor, session_id: str, device_id: str) -> dict:
    """Lock and return the session row, or raise SyncRejected if it is
    missing or belongs to another device (or to the Streamlit app, which
    leaves device_id NULL)."""
    cur.execute(
        "SELECT device_id, status FROM session WHERE session_id = %s FOR UPDATE",
        (session_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise SyncRejected("unknown_session")
    if row["device_id"] != device_id:
        raise SyncRejected("session_not_owned")
    return row


def apply_create_session(
    device_id: str,
    session_id: str,
    sanford_id: str,
    location: str,
    created_at: datetime,
) -> str:
    """Create a device-owned session with a device-minted id. Re-sending the
    same create is a no-op (SYNC_DUPLICATE); an id already used by another
    device or by the Streamlit app is rejected."""
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO session (session_id, sanford_id, location, status, "
            "created_at, ended_at, device_id) VALUES (%s, %s, %s, %s, %s, NULL, %s) "
            "ON CONFLICT (session_id) DO NOTHING",
            (session_id, sanford_id, location, STATUS_ACTIVE, created_at, device_id),
        )
        if cur.rowcount == 1:
            return SYNC_APPLIED
        _owned_session_row(cur, session_id, device_id)
        return SYNC_DUPLICATE


def apply_scan_op(
    device_id: str,
    op_id: str,
    session_id: str,
    gtin: str,
    result: dict | None,
    at: datetime,
) -> str:
    """Apply one queued scan exactly once.

    `result` is the server-resolved record for a GTIN not yet in the session
    (see sync_api/sync.py); it may be None only when the caller saw the GTIN
    already present, in which case this is a rescan and just bumps the count.
    The session row lock serialises concurrent syncs of the same session.
    """
    with _cursor() as cur:
        _owned_session_row(cur, session_id, device_id)
        cur.execute(
            "INSERT INTO sync_scan_op (device_id, op_id, session_id, applied_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (device_id, op_id, session_id, _utcnow()),
        )
        if cur.rowcount == 0:
            return SYNC_DUPLICATE
        cur.execute(
            "UPDATE scan SET scan_count = scan_count + 1, "
            "last_scanned = GREATEST(last_scanned, %s), "
            "scanned_at = LEAST(scanned_at, %s) "
            "WHERE session_id = %s AND gtin = %s",
            (at, at, session_id, gtin),
        )
        if cur.rowcount == 1:
            return SYNC_APPLIED
        if result is None:
            raise SyncRetry("scan disappeared between check and apply")
        _insert_scan(cur, session_id, result, at)
        return SYNC_APPLIED


def apply_end_session_op(device_id: str, session_id: str, at: datetime) -> str:
    with _cursor() as cur:
        row = _owned_session_row(cur, session_id, device_id)
        if row["status"] != STATUS_ACTIVE:
            return SYNC_DUPLICATE
        cur.execute(
            "UPDATE session SET status = %s, ended_at = %s WHERE session_id = %s",
            (STATUS_ENDED, at, session_id),
        )
        return SYNC_APPLIED


# ── Retention ────────────────────────────────────────────────────────────────
def purge_old_sessions() -> int:
    """Delete sessions (and their scans) older than RETENTION_DAYS.

    The scan rows go with them via ON DELETE CASCADE, so unlike the SQLite
    version this does not need to collect ids and delete from both tables.

    Note this is the secondary sweep — the authoritative one is the daily
    GitHub Action, which runs even when nobody has the app open. See the
    module docstring, and core/session.py's _maybe_purge for the rate-limited
    caller; this function itself does no rate limiting, so it stays safe to
    call directly from a script or test.

    Returns the number of sessions purged.
    """
    cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    with _cursor() as cur:
        cur.execute("DELETE FROM session WHERE created_at < %s", (cutoff,))
        purged = cur.rowcount
    if purged:
        logger.info("Purged %d session(s) older than %d days.", purged, RETENTION_DAYS)
    return purged
