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
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_GUDID_LOOKUP_URL = "https://accessgudid.nlm.nih.gov/api/v2/devices/lookup.json"
_TIMEOUT_SECONDS = 10.0


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

    Args:
        gtin: The GTIN string to look up. Leading zeros are preserved and
              passed directly to the API as the 'di' query parameter.

    Returns:
        GoodIDResult with the API response payload or a structured error.

    Example URL constructed:
        https://accessgudid.nlm.nih.gov/api/v2/devices/lookup.json?di=00841098765432
    """
    url = f"{_GUDID_LOOKUP_URL}?di={gtin}"
    logger.info("AccessGUDID fallback query: GET %s", url)

    try:
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            resp = client.get(url)
            resp.raise_for_status()
            payload = resp.json()
            logger.info("AccessGUDID returned HTTP %d for GTIN %s", resp.status_code, gtin)
            return GoodIDResult(
                success=True,
                gtin=gtin,
                payload=payload,
                status_code=resp.status_code,
                error_message=None,
            )

    except httpx.TimeoutException:
        msg = f"AccessGUDID request timed out after {_TIMEOUT_SECONDS}s."
        logger.warning(msg)
        return GoodIDResult(
            success=False, gtin=gtin, payload={}, status_code=None, error_message=msg
        )

    except httpx.HTTPStatusError as exc:
        msg = f"AccessGUDID returned HTTP {exc.response.status_code}."
        logger.warning("%s Body: %s", msg, exc.response.text[:300])
        return GoodIDResult(
            success=False,
            gtin=gtin,
            payload={},
            status_code=exc.response.status_code,
            error_message=msg,
        )

    except httpx.RequestError as exc:
        msg = f"Network error contacting AccessGUDID: {exc}"
        logger.warning(msg)
        return GoodIDResult(
            success=False, gtin=gtin, payload={}, status_code=None, error_message=msg
        )
