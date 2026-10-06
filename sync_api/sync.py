"""
sync_api/sync.py
~~~~~~~~~~~~~~~~
Validates and applies a batch of operations queued on a handheld.

Trust model: the device sends only *raw facts* — session identity, raw
barcode strings, and the times they happened. Everything derived (the GTIN,
whether it matched a contract line, the goodID fallback, miss reasons) is
computed here from the server's own reference data. A compromised or buggy
handheld therefore cannot write arbitrary product records into the shared
database; the worst it can do is record scans, in sessions it owns.

Per-op statuses returned to the device:
  applied    — done.
  duplicate  — already applied earlier (a retried batch); treat as done.
  rejected   — will never succeed as sent; drop it. `code` says why.
  retry      — could not be applied right now; keep it and send it again.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from core.connectivity import is_connectivity_error
from core.logsafe import safe_log_value
from core.lookup import extract_gtin
from core.store import SyncRejected, SyncRetry

logger = logging.getLogger(__name__)

MAX_OPS_PER_BATCH = 100
# A batch that has been running this long stops resolving and tells the device
# to retry the rest — keeps a slow goodID from holding a request open.
DEADLINE_SECONDS = 25.0

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_OP_TYPES = ("create_session", "scan", "end_session")
_MAX_SANFORD_ID = 64
_MAX_LOCATION = 128
_MAX_RAW_SCAN = 256
_MAX_GTIN = 64


class _Reject(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _text(op: dict, field: str, max_len: int, *, allow_gs: bool = False) -> str:
    value = op.get(field)
    if not isinstance(value, str):
        raise _Reject(f"invalid_{field}")
    value = value.strip()
    if not value or len(value) > max_len:
        raise _Reject(f"invalid_{field}")
    for ch in value:
        if (ord(ch) < 0x20 or ord(ch) == 0x7F) and not (allow_gs and ch == "\x1d"):
            raise _Reject(f"invalid_{field}")
    return value


def _identifier(op: dict, field: str) -> str:
    value = op.get(field)
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise _Reject(f"invalid_{field}")
    return value


def _timestamp(op: dict, field: str, now: datetime, retention: timedelta) -> datetime:
    value = op.get(field)
    if not isinstance(value, str):
        raise _Reject(f"invalid_{field}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _Reject(f"invalid_{field}") from None
    if parsed.tzinfo is None:
        raise _Reject(f"invalid_{field}")
    parsed = parsed.astimezone(UTC).replace(microsecond=0)
    if parsed < now - retention:
        raise _Reject("too_old")
    # A handheld with a fast clock is clamped rather than refused: the scan
    # is real, only its timestamp is wrong.
    return min(parsed, now.replace(microsecond=0))


def _is_transient_lookup_failure(result: dict) -> bool:
    """True when a goodID miss means "couldn't ask", not "not in goodID"."""
    if result.get("source") != "api":
        return False
    api = result.get("api_result")
    if api is None or api.success:
        return False
    code = api.status_code
    return code is None or code == 429 or code >= 500


def process_ops(
    device_id: str,
    ops: list,
    *,
    store,
    resolve: Callable[[str], dict],
    retention: timedelta,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    clock: Callable[[], float] = time.monotonic,
    deadline_seconds: float | None = None,
) -> list[dict]:
    """Apply `ops` in order; return one status dict per op, same order.

    `resolve(raw_scan)` returns a core.lookup.resolve_scan()-shaped result.
    """
    if deadline_seconds is None:
        deadline_seconds = DEADLINE_SECONDS
    results: list[dict] = []
    started = clock()
    db_down = False

    for op in ops:
        op_id = op.get("op_id") if isinstance(op, dict) else None
        out: dict = {"op_id": op_id if isinstance(op_id, str) else None}
        results.append(out)

        if db_down:
            out.update(status="retry", code="database_unavailable")
            continue
        if clock() - started > deadline_seconds:
            out.update(status="retry", code="deadline")
            continue

        try:
            if not isinstance(op, dict):
                raise _Reject("invalid_op")
            _identifier(op, "op_id")
            op_type = op.get("type")
            if op_type not in _OP_TYPES:
                raise _Reject("invalid_type")
            session_id = _identifier(op, "session_id")
            current = now()

            if op_type == "create_session":
                status = store.apply_create_session(
                    device_id,
                    session_id,
                    _text(op, "sanford_id", _MAX_SANFORD_ID),
                    _text(op, "location", _MAX_LOCATION),
                    _timestamp(op, "created_at", current, retention),
                )
            elif op_type == "end_session":
                status = store.apply_end_session_op(
                    device_id, session_id, _timestamp(op, "ended_at", current, retention)
                )
            else:
                status = _apply_scan(
                    device_id, op, session_id, current,
                    store=store, resolve=resolve, retention=retention,
                )
            out["status"] = status
        except _Reject as exc:
            out.update(status="rejected", code=exc.code)
        except SyncRejected as exc:
            out.update(status="rejected", code=exc.code)
        except SyncRetry as exc:
            out.update(status="retry", code=str(exc) or "retry")
        except Exception as exc:  # noqa: BLE001 — one bad op must not sink the batch
            if is_connectivity_error(exc):
                db_down = True
                out.update(status="retry", code="database_unavailable")
            else:
                logger.exception("Unexpected error applying op %s", safe_log_value(op_id))
                out.update(status="retry", code="server_error")
    return results


def _apply_scan(device_id, op, session_id, current, *, store, resolve, retention) -> str:
    raw_scan = _text(op, "raw_scan", _MAX_RAW_SCAN, allow_gs=True)
    scanned_at = _timestamp(op, "scanned_at", current, retention)
    gtin = extract_gtin(raw_scan)
    if len(gtin) > _MAX_GTIN:
        raise _Reject("invalid_raw_scan")

    session = store.get_session(session_id)
    if session is None:
        raise _Reject("unknown_session")
    if session.get("device_id") != device_id:
        raise _Reject("session_not_owned")

    result = None
    if not store.scan_exists(session_id, gtin):
        result = resolve(raw_scan)
        if _is_transient_lookup_failure(result):
            raise SyncRetry("lookup_unavailable")
    return store.apply_scan_op(device_id, op["op_id"], session_id, gtin, result, scanned_at)
