"""
sync_api/memory_store.py
~~~~~~~~~~~~~~~~~~~~~~~~
In-memory stand-in for core.store's device-API functions.

Not for production: state is lost on restart and there is no database behind
it. It exists so the service can be run (sync_api/dev_server.py) and tested
without Postgres, and it mirrors the contract the real store keeps — device
ownership of sessions, exactly-once scan ops, duplicate detection.
"""

from __future__ import annotations

from core.store import SYNC_APPLIED, SYNC_DUPLICATE, SyncRejected, SyncRetry


class InMemoryStore:
    RETENTION_DAYS = 3
    SyncRejected = SyncRejected
    SyncRetry = SyncRetry

    def __init__(self, devices: dict[str, dict] | None = None):
        self.devices = devices or {}
        self.sessions: dict[str, dict] = {}
        self.scans: dict[tuple[str, str], dict] = {}
        self.ops: set[tuple[str, str]] = set()
        self.touched: list[str] = []
        self.fail_with: Exception | None = None

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            raise self.fail_with

    def device_for_token_hash(self, token_hash: str) -> dict | None:
        return self.devices.get(token_hash)

    def get_session(self, session_id):
        self._maybe_fail()
        return self.sessions.get(session_id)

    def scan_exists(self, session_id, gtin):
        return (session_id, gtin) in self.scans

    def touch_device(self, device_id):
        self.touched.append(device_id)

    def _owned(self, device_id, session_id):
        session = self.sessions.get(session_id)
        if session is None:
            raise SyncRejected("unknown_session")
        if session["device_id"] != device_id:
            raise SyncRejected("session_not_owned")
        return session

    def apply_create_session(self, device_id, session_id, sanford_id, location, created_at):
        self._maybe_fail()
        if session_id in self.sessions:
            self._owned(device_id, session_id)
            return SYNC_DUPLICATE
        self.sessions[session_id] = {
            "device_id": device_id, "sanford_id": sanford_id, "location": location,
            "created_at": created_at, "status": "active", "ended_at": None,
        }
        return SYNC_APPLIED

    def apply_scan_op(self, device_id, op_id, session_id, gtin, result, at):
        self._maybe_fail()
        self._owned(device_id, session_id)
        if (device_id, op_id) in self.ops:
            return SYNC_DUPLICATE
        self.ops.add((device_id, op_id))
        key = (session_id, gtin)
        if key in self.scans:
            self.scans[key]["scan_count"] += 1
        else:
            if result is None:
                raise SyncRetry("scan disappeared")
            self.scans[key] = {"scan_count": 1, "result": result, "scanned_at": at}
        return SYNC_APPLIED

    def apply_end_session_op(self, device_id, session_id, at):
        self._maybe_fail()
        session = self._owned(device_id, session_id)
        if session["status"] != "active":
            return SYNC_DUPLICATE
        session.update(status="ended", ended_at=at)
        return SYNC_APPLIED
