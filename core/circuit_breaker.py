"""
core/circuit_breaker.py
~~~~~~~~~~~~~~~~~~~~~~~~
A minimal, in-process circuit breaker for outbound calls that can hang or
retry-storm against a struggling endpoint (GUDID, Fabric) — poor warehouse
connectivity should degrade to a fast, predictable failure on every scan
during a sustained outage, not a slow one repeated on every single scan.

Not distributed: each Streamlit server process tracks its own breaker state
in memory (a module-level instance per endpoint — see api/goodid_client.py
and data/loader.py). That's the right scope here — there's normally exactly
one such process, and this exists to stop it from hammering a struggling
endpoint, not to coordinate breaker state across a fleet.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class CircuitOpenError(RuntimeError):
    """Raised by before_call() instead of letting a call through while the
    breaker is open — the caller should treat this exactly like any other
    "couldn't reach it" failure, just one that cost no network round trip."""


class CircuitBreaker:
    """Opens after `failure_threshold` consecutive failures and refuses
    calls (before_call() raises immediately, no network attempt) until
    `cooldown_seconds` have passed. Once the cooldown elapses, the next
    before_call() succeeds (half-open) and that call's own
    record_success()/record_failure() decides whether the breaker closes
    for good or reopens for another full cooldown.
    """

    def __init__(self, name: str, failure_threshold: int = 3, cooldown_seconds: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def _is_open_unlocked(self) -> bool:
        if self._opened_at is None:
            return False
        return time.time() - self._opened_at < self.cooldown_seconds

    def before_call(self) -> None:
        """Raise CircuitOpenError if the breaker is currently open."""
        with self._lock:
            if self._is_open_unlocked():
                raise CircuitOpenError(
                    f"Circuit {self.name!r} is open after {self._failure_count} "
                    f"consecutive failures — refusing another attempt for now."
                )

    def record_success(self) -> None:
        with self._lock:
            if self._failure_count or self._opened_at is not None:
                logger.info("Circuit %r closed after a successful call.", self.name)
            self._failure_count = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                # Always (re)stamp opened_at to now, not just on the first
                # transition into "open" — a half-open trial call (allowed
                # through after the previous cooldown elapsed, so is_open was
                # already False) that fails must restart a fresh cooldown
                # window. Without this, opened_at would stay at its old,
                # already-elapsed timestamp and is_open would incorrectly
                # read as closed.
                self._opened_at = time.time()
                logger.warning(
                    "Circuit %r opened after %d consecutive failures — "
                    "refusing calls for %.0fs.",
                    self.name, self._failure_count, self.cooldown_seconds,
                )

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._is_open_unlocked()
