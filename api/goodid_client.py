"""
api/goodid_client.py
~~~~~~~~~~~~~~~~~~~~
HTTP fallback client for the FDA AccessGUDID public API.

Endpoint: https://accessgudid.nlm.nih.gov/api/v2/devices/lookup.json?di=<GTIN>

This is a publicly accessible API maintained by the U.S. National Library of
Medicine. No authentication or API key is required.

Uses synchronous httpx.Client — deliberately NOT async to avoid
Streamlit/asyncio event-loop conflicts. Streamlit's execution model is
synchronous; wrapping async code with asyncio.run() inside a Streamlit
callback causes thread-safety errors and hangs.

Docs: https://accessgudid.nlm.nih.gov/api_docs
""" 

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_GUDID_LOOKUP_URL = "https://accessgudid.nlm.nih.gov/api/v2/devices/lookup.json"

# Per-attempt timeout. Lower than the old single-shot 10s specifically to
# make room for one retry (see _MAX_ATTEMPTS) without raising the worst-case
# time a single scan can be stuck waiting on a bad connection.
_TIMEOUT_SECONDS = 6.0
_MAX_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 0.5

# Lazily created on first call — see _get_breaker(). Held at module scope so
# breaker state (consecutive-failure count, open/closed) persists across
# scans within this process, which is the whole point of a circuit breaker.
_breaker = None


def _get_breaker():
    """The module-level circuit breaker, created on first use.

    Deferred import/construction rather than a module-level `from
    core.circuit_breaker import CircuitBreaker` — see the lazy import lower
    in this file for why a module-level `core.*` import here is unsafe
    regardless of which package a caller imports first.
    """
    global _breaker
    if _breaker is None:
        from core.circuit_breaker import CircuitBreaker  # noqa: PLC0415

        _breaker = CircuitBreaker("gudid", failure_threshold=3, cooldown_seconds=30.0)
    return _breaker


@dataclass(frozen=True)
class GoodIDResult:
    """Structured result from an AccessGUDID API call.

    Attributes:
        success: True if the API responded with usable data.
        gtin: The GTIN (device identifier) that was queried.
        payload: Raw JSON payload from the API, or an empty dict on failure.
        status_code: HTTP status code, or None on network/timeout error.
        error_message: Human-readable error description, or None on success.
    """

    success: bool
    gtin: str
    payload: dict
    status_code: int | None
    error_message: str | None


def query_goodid(gtin: str) -> GoodIDResult:
    """Look up a device identifier against the FDA AccessGUDID database.

    Falls back gracefully on any network or HTTP error — never raises
    an unhandled exception. The caller always receives a GoodIDResult,
    with success=False and a populated error_message on failure.

    Resilience against poor warehouse connectivity (ASVS-AUDIT.md item 6):
      * Up to _MAX_ATTEMPTS tries with a short backoff between them, but
        only for a timeout/connection-level failure — an HTTP error response
        (404, 500, ...) is a real answer from a reachable server, and
        retrying the identical request would just add latency for the same
        answer.
      * A circuit breaker (core.circuit_breaker) opens after 3 consecutive
        connectivity failures and short-circuits every call for the next
        30s — during a sustained GUDID/network outage this means a fast,
        predictable "unavailable" instead of every single scan separately
        paying the full timeout.

    Args:
        gtin: The GTIN string to look up. Leading zeros are preserved and
              passed directly to the API as the 'di' query parameter.

    Returns:
        GoodIDResult with the API response payload or a structured error.
    """
    # Lazy import: core.lookup imports `api` at module load, and core/__init__
    # eagerly imports core.lookup — a module-level `from core.egress import
    # ...` here would make api's own package import depend on core finishing
    # its package import first, which isn't guaranteed by import order (e.g.
    # `import api` before anything touches `core`). Deferring the import to
    # call time breaks that cycle; core.egress itself has no import-time
    # dependency on api, so this is safe regardless of who imports first.
    from core.circuit_breaker import CircuitOpenError  # noqa: PLC0415
    from core.egress import assert_allowed_url  # noqa: PLC0415
    from core.logsafe import safe_log_value  # noqa: PLC0415

    url = _GUDID_LOOKUP_URL
    assert_allowed_url(url)

    breaker = _get_breaker()
    try:
        breaker.before_call()
    except CircuitOpenError as exc:
        logger.warning(str(exc))
        return GoodIDResult(success=False, gtin=gtin, payload={}, status_code=None, error_message=str(exc))

    logger.info("AccessGUDID fallback query: GET %s", url)

    last_error: GoodIDResult | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                resp = client.get(url, params={"di": gtin})
                resp.raise_for_status()
                payload = resp.json()
                logger.info(
                    "AccessGUDID returned HTTP %d for GTIN %s", resp.status_code, safe_log_value(gtin)
                )
                breaker.record_success()
                return GoodIDResult(
                    success=True,
                    gtin=gtin,
                    payload=payload,
                    status_code=resp.status_code,
                    error_message=None,
                )

        except httpx.HTTPStatusError as exc:
            # A response, not a connectivity failure — does not count against
            # the breaker, and retrying it would not change the answer.
            msg = f"AccessGUDID returned HTTP {exc.response.status_code}."
            logger.warning("%s Body: %s", msg, exc.response.text[:300])
            breaker.record_success()
            return GoodIDResult(
                success=False,
                gtin=gtin,
                payload={},
                status_code=exc.response.status_code,
                error_message=msg,
            )

        except httpx.TimeoutException:
            last_error = GoodIDResult(
                success=False, gtin=gtin, payload={}, status_code=None,
                error_message=f"AccessGUDID request timed out after {_TIMEOUT_SECONDS}s.",
            )
        except httpx.RequestError as exc:
            last_error = GoodIDResult(
                success=False, gtin=gtin, payload={}, status_code=None,
                error_message=f"Network error contacting AccessGUDID: {exc}",
            )

        # Only a timeout/connection-level failure reaches here (an
        # HTTPStatusError already returned above).
        if attempt < _MAX_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF_SECONDS)

    breaker.record_failure()
    logger.warning(last_error.error_message)
    return last_error
