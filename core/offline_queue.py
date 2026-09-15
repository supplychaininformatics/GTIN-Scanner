"""
core/offline_queue.py
~~~~~~~~~~~~~~~~~~~~~
Server-side write buffer for a transient Neon Postgres outage.

Scope note — read this before changing anything here: this buffers writes
between the Streamlit SERVER process and Neon. It has nothing to do with a
handheld's own WiFi connection to the Streamlit server, which Streamlit's
request/rerun model cannot buffer around from server-side code — see
PLAN.md's "Explicit accepted assumption" and ASVS-COMPLIANCE.md for why that
is a separate, larger problem (a true client-side offline mode would need a
service worker and local storage, i.e. a different kind of app). What this
module protects against is Neon being unreachable *from the server* for a
while — a cold-start delay, a transient network blip between the app's host
and Neon, a brief Neon maintenance window — without silently losing the
scans recorded during that window.

Each queued item is one deferred call back into core.store (create_session,
record_scan, increment_scan, end_session), stored as one Fernet-encrypted
JSON blob on disk. A SHA-256 checksum over each entry's args is verified
before replay, so a corrupted or truncated queue file (a crash mid-write,
disk corruption) can never silently replay altered data into the shared
database — a checksum mismatch drops that entry with a logged error instead.
Entries older than _MAX_AGE_SECONDS are dropped rather than retried forever.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken

from data.loader import CACHE_PATH

from . import secrets

logger = logging.getLogger(__name__)

_QUEUE_PATH = CACHE_PATH.parent / "pending_writes.enc"
_FALLBACK_KEY_PATH = CACHE_PATH.parent / ".offline_queue_key"
_KEYRING_KEY_NAME = "offline_queue_key"

# Deliberately much shorter than store.RETENTION_DAYS (3 days): if Neon has
# been unreachable from the server for this long, something is fundamentally
# broken, and an ever-growing retry queue would just mask that instead of
# surfacing it.
_MAX_AGE_SECONDS = 24 * 3600
# A sanity cap, not an expected operating point — protects disk/memory if
# something is stuck retrying far longer than _MAX_AGE_SECONDS should allow.
_MAX_QUEUE_SIZE = 500

# flush() is called once per rerun (core.session.init_session), i.e. up to
# once per scan. Without a cooldown, a sustained Neon outage would mean every
# single scan pays a full connection/pool timeout (up to 20s — see
# core/store.py's pool `timeout`) just to find out Neon is still down. This
# makes flush() a fast no-op between attempts instead.
_FLUSH_COOLDOWN_SECONDS = 30

_lock = threading.Lock()
_last_flush_attempt = 0.0


def _get_or_create_key() -> bytes:
    """Fernet key for the queue file.

    Prefers the OS keychain (via core.secrets), generating and persisting a
    key there on first use so a server restart doesn't orphan a still-
    pending queue. Falls back to a local key file (0600) only when no
    keyring backend is available at all (e.g. a headless container with no
    Secret Service running) — the queue is still encrypted either way, just
    with a weaker at-rest guarantee for the key itself in that fallback case.
    """
    existing = secrets.from_keyring(_KEYRING_KEY_NAME)
    if existing:
        return existing.encode()

    key = Fernet.generate_key()
    try:
        secrets.store_in_keyring(_KEYRING_KEY_NAME, key.decode())
        return key
    except Exception:  # noqa: BLE001 — no keyring backend; use the file fallback
        logger.warning(
            "No OS keychain backend available; falling back to a local key "
            "file for the offline write queue."
        )
    if _FALLBACK_KEY_PATH.exists():
        return _FALLBACK_KEY_PATH.read_bytes()
    _FALLBACK_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FALLBACK_KEY_PATH.write_bytes(key)
    _FALLBACK_KEY_PATH.chmod(0o600)
    return key


def _checksum(op: str, args: dict) -> str:
    payload = json.dumps({"op": op, "args": args}, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _load() -> list[dict]:
    """Decrypt and parse the queue file. Any failure — missing file,
    wrong/rotated key, truncated write — is treated as "empty queue" rather
    than raised: a lost retry queue is a cost, not a correctness problem,
    and this must never be the reason the app fails to start."""
    if not _QUEUE_PATH.exists():
        return []
    try:
        fernet = Fernet(_get_or_create_key())
        raw = fernet.decrypt(_QUEUE_PATH.read_bytes())
        entries = json.loads(raw)
        return entries if isinstance(entries, list) else []
    except (InvalidToken, json.JSONDecodeError, OSError):
        logger.warning("Offline write queue is unreadable; treating it as empty.", exc_info=True)
        return []


def _save(entries: list[dict]) -> None:
    """Encrypt and atomically write the queue file.

    Atomic (write to a temp file, then os.replace) so a crash mid-write
    can't leave a half-written file that _load() would otherwise choke on.
    """
    fernet = Fernet(_get_or_create_key())
    token = fernet.encrypt(json.dumps(entries).encode())
    _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _QUEUE_PATH.with_suffix(".tmp")
    tmp_path.write_bytes(token)
    tmp_path.replace(_QUEUE_PATH)


def _prune(entries: list[dict]) -> list[dict]:
    now = time.time()
    fresh = [e for e in entries if now - e.get("ts", 0) < _MAX_AGE_SECONDS]
    dropped_for_age = len(entries) - len(fresh)
    if dropped_for_age:
        logger.warning(
            "Dropping %d offline-queue entr%s older than %ds — Neon has "
            "been unreachable from the server too long to keep retrying.",
            dropped_for_age, "y" if dropped_for_age == 1 else "ies", _MAX_AGE_SECONDS,
        )
    if len(fresh) > _MAX_QUEUE_SIZE:
        overflow = len(fresh) - _MAX_QUEUE_SIZE
        logger.warning("Offline queue exceeded %d entries; dropping the %d oldest.", _MAX_QUEUE_SIZE, overflow)
        fresh = fresh[overflow:]
    return fresh


def enqueue(op: str, args: dict) -> None:
    """Buffer one deferred core.store call for later replay.

    `args` must be JSON-serializable and match the keyword arguments of the
    core.store function named by `op` exactly — see flush()'s dispatch table.
    """
    entry = {
        "id": uuid.uuid4().hex,
        "ts": time.time(),
        "op": op,
        "args": args,
        "checksum": _checksum(op, args),
    }
    with _lock:
        entries = _prune(_load())
        entries.append(entry)
        _save(entries)
    logger.info("Queued offline write: %s (queue depth now %d).", op, len(entries))


def pending_count() -> int:
    """How many writes are currently waiting to sync — for UI messaging."""
    with _lock:
        return len(_prune(_load()))


def find_pending_session(session_id: str) -> dict | None:
    """A store `session`-row-shaped dict reconstructed from a still-queued
    create_session entry for `session_id`, or None if there isn't one.

    Lets a resume-by-URL flow work even when the session's INSERT hasn't
    reached Neon yet, instead of looking like an unknown/purged session —
    see core.session.resume_pending_session, and start_session's docstring
    for the gap this closes.
    """
    with _lock:
        entries = _prune(_load())
    for entry in entries:
        if entry["op"] == "create_session" and entry["args"].get("session_id") == session_id:
            args = entry["args"]
            created_at = datetime.fromtimestamp(entry["ts"], tz=UTC).replace(microsecond=0).isoformat()
            return {
                "session_id": session_id,
                "sanford_id": args["sanford_id"],
                "location": args["location"],
                "status": "active",
                "created_at": created_at,
                "ended_at": None,
            }
    return None


def pending_scans_for_session(session_id: str) -> list[dict]:
    """Queued record_scan results for `session_id`, oldest first.

    Used to rebuild scan history on a resume before those writes have
    synced. Does not cover a queued increment_scan on its own (a rescan
    carries no display fields, only session_id+gtin — the rest lives on
    the scan_history entry that was already in hand at the time of the
    rescan) — a narrow, documented gap, not a data-loss one: the queued
    increment still applies once synced, it just doesn't retroactively
    reconstruct on this code path.
    """
    with _lock:
        entries = _prune(_load())
    return [
        entry["args"]["result"]
        for entry in entries
        if entry["op"] == "record_scan" and entry["args"].get("session_id") == session_id
    ]


def flush() -> int:
    """Replay every queued write against core.store, in the order queued.

    Stops at the first entry that still fails for a connectivity reason
    (Neon is presumably still down — no point burning through the rest of
    the queue this rerun) but continues past an entry that fails for any
    other reason, logging and dropping it: retrying an operation that fails
    for a non-connectivity reason (e.g. a checksum mismatch, or a session_id
    that no longer makes sense) would otherwise loop forever.

    Returns the number of entries successfully applied.

    Rate-limited to once per _FLUSH_COOLDOWN_SECONDS regardless of caller —
    see that constant's comment. Returns 0 immediately when called again
    inside the cooldown window, without touching disk or Neon.
    """
    global _last_flush_attempt
    now = time.time()
    if now - _last_flush_attempt < _FLUSH_COOLDOWN_SECONDS:
        return 0
    _last_flush_attempt = now

    # Local import: core.store imports this module indirectly via
    # core.session, and core.store itself has no reason to import the queue
    # — keeping the dependency one-directional (queue -> store, never back)
    # avoids a cycle.
    from . import store  # noqa: PLC0415
    from .connectivity import is_connectivity_error  # noqa: PLC0415

    dispatch = {
        "create_session": lambda a: store.create_session(**a),
        "record_scan": lambda a: store.record_scan(**a),
        "increment_scan": lambda a: store.increment_scan(**a),
        "end_session": lambda a: store.end_session(**a),
    }

    with _lock:
        entries = _prune(_load())
        if not entries:
            return 0

        applied = 0
        remaining = list(entries)
        for entry in entries:
            if _checksum(entry["op"], entry["args"]) != entry.get("checksum"):
                logger.error(
                    "Dropping offline-queue entry %s: checksum mismatch "
                    "(corrupted on disk) — refusing to replay it.",
                    entry.get("id", "?"),
                )
                remaining.remove(entry)
                continue

            handler = dispatch.get(entry["op"])
            if handler is None:
                logger.error("Dropping offline-queue entry with unknown op %r.", entry["op"])
                remaining.remove(entry)
                continue

            try:
                handler(entry["args"])
            except Exception as exc:  # noqa: BLE001 — dispatch below decides retry vs drop
                if is_connectivity_error(exc):
                    logger.info("Neon still unreachable; %d entries remain queued.", len(remaining))
                    break
                logger.error(
                    "Dropping offline-queue entry %s (%s): failed for a "
                    "non-connectivity reason, retrying would loop forever.",
                    entry.get("id", "?"), entry["op"], exc_info=True,
                )
                remaining.remove(entry)
                continue
            else:
                applied += 1
                remaining.remove(entry)

        _save(remaining)

    if applied:
        logger.info("Synced %d queued write(s) to Neon.", applied)
    return applied
