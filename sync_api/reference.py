"""
sync_api/reference.py
~~~~~~~~~~~~~~~~~~~~~
The contract-line reference data handhelds mirror for offline lookup.

Built from the same load_contract_data() → LookupEngine path the Streamlit app
uses, so the lakehouse is only ever queried by that loader on its own 24h
cadence (behind its circuit breaker) — never by a device request. Requests
here are served entirely from memory.

The snapshot is paged so a download interrupted by a WiFi drop resumes from
the last page instead of restarting. Every page carries the snapshot
`version`; if the data refreshes mid-download the next page request 409s and
the client restarts against the new version.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from core.lookup import contract_display_fields
from engine import LookupEngine

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600


@dataclass(frozen=True)
class Snapshot:
    engine: LookupEngine
    rows: list[dict]
    keys: list[str]
    version: str
    generated_at: str

    def page(self, after: str | None, limit: int) -> tuple[list[dict], str | None]:
        """Up to `limit` rows whose key sorts after `after`, plus the cursor
        for the next page (None when this is the last one)."""
        start = bisect.bisect_right(self.keys, after) if after else 0
        chunk = self.rows[start:start + limit]
        more = start + limit < len(self.rows)
        return chunk, (chunk[-1]["gtin"] if chunk and more else None)


def _row_for(key: str, record: dict) -> dict:
    fields = contract_display_fields(record)
    return {
        "gtin": key,
        "item": fields["Item"],
        "company": fields["Company"],
        "brand": fields["Brand"],
        "description": fields["Description"],
        "gtin_uom": fields["GTIN UOM"],
        "uou": fields["UOU"],
        "lawson_id": fields["LAWSON ID"],
        "lawson_uom": fields["Lawson UOM"],
        "on_hold": bool(record.get("on_hold")),
    }


def build_snapshot(engine: LookupEngine) -> Snapshot:
    rows = [_row_for(key, record) for key, record in engine.entries()]
    digest = hashlib.sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True).encode())
    return Snapshot(
        engine=engine,
        rows=rows,
        keys=[r["gtin"] for r in rows],
        version=digest.hexdigest()[:16],
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )


class ReferenceData:
    """Snapshot holder: built once on first use, then refreshed in the
    background once older than the TTL while requests keep being served from
    the current copy (a rebuild takes several seconds at production size)."""

    def __init__(
        self,
        load_df,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock=time.monotonic,
        spawn=None,
    ):
        self._load_df = load_df
        self._ttl = ttl_seconds
        self._clock = clock
        self._spawn = spawn or self._spawn_thread
        self._snapshot: Snapshot | None = None
        self._built_at = 0.0
        self._refreshing = False
        self._lock = threading.Lock()
        self._first_build_lock = threading.Lock()

    @staticmethod
    def _spawn_thread(fn) -> None:
        threading.Thread(target=fn, name="reference-refresh", daemon=True).start()

    def get(self) -> Snapshot:
        with self._lock:
            current = self._snapshot
            start_refresh = (
                current is not None
                and not self._refreshing
                and self._clock() - self._built_at >= self._ttl
            )
            if start_refresh:
                self._refreshing = True
        if current is not None:
            # Outside the lock: _refresh() takes it, and a synchronous spawn
            # (tests) would otherwise deadlock against this frame.
            if start_refresh:
                self._spawn(self._refresh)
            return current
        # Nothing to serve yet: build synchronously, one caller at a time.
        with self._first_build_lock:
            with self._lock:
                if self._snapshot is not None:
                    return self._snapshot
            snapshot = build_snapshot(LookupEngine(self._load_df()))
            with self._lock:
                self._snapshot = snapshot
                self._built_at = self._clock()
            logger.info("Reference snapshot %s: %d rows.", snapshot.version, len(snapshot.rows))
            return snapshot

    def _refresh(self) -> None:
        try:
            snapshot = build_snapshot(LookupEngine(self._load_df()))
        except Exception:
            # Keep serving the last good copy: a lakehouse/cache hiccup must
            # not take lookups down for handhelds that are online. Retry soon.
            logger.warning("Reference refresh failed; serving stale snapshot.", exc_info=True)
            with self._lock:
                self._built_at = self._clock() - self._ttl + 60
                self._refreshing = False
            return
        with self._lock:
            changed = self._snapshot is None or snapshot.version != self._snapshot.version
            self._snapshot = snapshot
            self._built_at = self._clock()
            self._refreshing = False
        if changed:
            logger.info("Reference snapshot %s: %d rows.", snapshot.version, len(snapshot.rows))
