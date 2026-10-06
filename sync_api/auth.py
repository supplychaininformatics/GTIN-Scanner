"""
sync_api/auth.py
~~~~~~~~~~~~~~~~
Per-device bearer tokens and a per-device rate limit.

A token is 32 random bytes; only its SHA-256 is stored (core.store.api_device),
so a database leak does not yield usable credentials, and a lost handheld is
cut off individually by revoking its row. A positive lookup is cached briefly
so the auth check is not a database round trip per request — which also means
a revocation takes up to _AUTH_CACHE_SECONDS to bite.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import deque

_AUTH_CACHE_SECONDS = 60.0
_TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenVerifier:
    def __init__(self, lookup, *, cache_seconds: float = _AUTH_CACHE_SECONDS, clock=time.monotonic):
        self._lookup = lookup
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def verify(self, token: str) -> dict | None:
        """The device dict for a valid token, else None. Lets a database
        error propagate (the caller turns it into a 503, not a 401)."""
        digest = hash_token(token)
        now = self._clock()
        with self._lock:
            hit = self._cache.get(digest)
            if hit and now - hit[0] < self._cache_seconds:
                return hit[1]
            self._cache.pop(digest, None)
        device = self._lookup(digest)
        if device is not None:
            with self._lock:
                self._cache[digest] = (now, device)
        return device


class RateLimiter:
    """Sliding-window limiter keyed by device id (in-process; the service is
    meant to run as one process, like the rest of this app)."""

    def __init__(self, max_requests: int, window_seconds: float, clock=time.monotonic):
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(now)
            return True
