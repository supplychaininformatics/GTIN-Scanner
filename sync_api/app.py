"""
sync_api/app.py
~~~~~~~~~~~~~~~
The HTTP surface handhelds talk to. Deliberately small:

  GET  /healthz                       liveness, unauthenticated, reveals nothing
  GET  /v1/reference/version          cheap "has the data changed?" check
  GET  /v1/reference/contract-lines   paged contract-line mirror for offline lookup
  GET  /v1/lookup?code=...            online resolve (contract line, then goodID)
  POST /v1/sync                       upload a batch of queued session/scan ops

Security posture (this service is the new network-reachable surface):
  * Every /v1 route needs a per-device bearer token (sync_api/auth.py).
  * Nothing here queries the lakehouse; reference data comes from the shared
    loader's own cached, breaker-guarded refresh (sync_api/reference.py).
  * Request bodies are size-capped, all input is validated (sync_api/sync.py),
    and responses are never cached.
  * A per-device rate limit bounds what one (possibly stolen) token can do.
Serve it over HTTPS only — tokens are bearer credentials.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from core import store as default_store
from core.connectivity import is_connectivity_error
from core.logsafe import safe_log_value

from .auth import RateLimiter, TokenVerifier
from .reference import ReferenceData
from .sync import MAX_OPS_PER_BATCH, process_ops

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 256 * 1024
MAX_PAGE_SIZE = 5000
DEFAULT_PAGE_SIZE = 2000
RATE_LIMIT_REQUESTS = 300
RATE_LIMIT_WINDOW_SECONDS = 60.0
_TOUCH_INTERVAL_SECONDS = 300.0
_MAX_CODE_LENGTH = 256


def _json(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(
        data,
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _error(code: str, status: int, **headers: str) -> JSONResponse:
    response = _json({"error": code}, status)
    response.headers.update(headers)
    return response


class _BodyTooLarge(Exception):
    pass


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _BodyTooLarge
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _BodyTooLarge
    return bytes(body)


def create_app(
    *,
    store=default_store,
    reference: ReferenceData | None = None,
    verifier: TokenVerifier | None = None,
    limiter: RateLimiter | None = None,
    resolve=None,
) -> Starlette:
    if reference is None:
        from data import load_contract_data  # noqa: PLC0415

        reference = ReferenceData(load_contract_data)
    verifier = verifier or TokenVerifier(store.device_for_token_hash)
    limiter = limiter or RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS)
    if resolve is None:
        from core.lookup import resolve_scan  # noqa: PLC0415

        def resolve(raw: str) -> dict:
            return resolve_scan(raw, reference.get().engine)

    retention = timedelta(days=store.RETENTION_DAYS)
    last_touch: dict[str, float] = {}

    async def authenticate(request: Request) -> tuple[dict | None, Response | None]:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return None, _error("unauthorized", 401, **{"WWW-Authenticate": "Bearer"})
        try:
            device = await run_in_threadpool(verifier.verify, token.strip())
        except Exception as exc:  # noqa: BLE001
            if is_connectivity_error(exc):
                return None, _error("service_unavailable", 503)
            logger.exception("Token verification failed")
            return None, _error("server_error", 500)
        if device is None:
            return None, _error("unauthorized", 401, **{"WWW-Authenticate": "Bearer"})
        if not limiter.allow(device["device_id"]):
            return None, _error("rate_limited", 429, **{"Retry-After": "30"})
        return device, None

    def touch(device_id: str) -> None:
        now = time.monotonic()
        if now - last_touch.get(device_id, -_TOUCH_INTERVAL_SECONDS) < _TOUCH_INTERVAL_SECONDS:
            return
        last_touch[device_id] = now
        try:
            store.touch_device(device_id)
        except Exception:  # noqa: BLE001 — bookkeeping only
            logger.warning("Could not update last_seen for a device.", exc_info=True)

    async def healthz(request: Request) -> Response:
        return _json({"status": "ok"})

    async def reference_version(request: Request) -> Response:
        device, failure = await authenticate(request)
        if failure:
            return failure
        try:
            snapshot = await run_in_threadpool(reference.get)
        except Exception:  # noqa: BLE001
            logger.exception("Reference data unavailable")
            return _error("reference_unavailable", 503)
        return _json(
            {
                "version": snapshot.version,
                "generated_at": snapshot.generated_at,
                "row_count": len(snapshot.rows),
            }
        )

    async def reference_pages(request: Request) -> Response:
        device, failure = await authenticate(request)
        if failure:
            return failure
        try:
            limit = int(request.query_params.get("limit", DEFAULT_PAGE_SIZE))
        except ValueError:
            return _error("invalid_limit", 400)
        if not 1 <= limit <= MAX_PAGE_SIZE:
            return _error("invalid_limit", 400)
        after = request.query_params.get("after") or None
        if after is not None and len(after) > _MAX_CODE_LENGTH:
            return _error("invalid_after", 400)
        try:
            snapshot = await run_in_threadpool(reference.get)
        except Exception:  # noqa: BLE001
            logger.exception("Reference data unavailable")
            return _error("reference_unavailable", 503)
        pinned = request.query_params.get("version")
        if pinned and pinned != snapshot.version:
            return _json({"error": "version_changed", "version": snapshot.version}, 409)
        rows, next_after = snapshot.page(after, limit)
        return _json({"version": snapshot.version, "rows": rows, "next": next_after})

    async def lookup(request: Request) -> Response:
        device, failure = await authenticate(request)
        if failure:
            return failure
        code = request.query_params.get("code", "").strip()
        if not code or len(code) > _MAX_CODE_LENGTH or any(
            (ord(c) < 0x20 or ord(c) == 0x7F) and c != "\x1d" for c in code
        ):
            return _error("invalid_code", 400)
        try:
            result = await run_in_threadpool(resolve, code)
        except Exception:  # noqa: BLE001
            logger.exception("Lookup failed for %s", safe_log_value(code))
            return _error("lookup_failed", 503)
        api = result.get("api_result")
        if api is not None and not api.success and (
            api.status_code is None or api.status_code == 429 or api.status_code >= 500
        ):
            return _error("upstream_unavailable", 503)
        return _json(
            {
                "gtin": result["gtin"],
                "status_key": result["status_key"],
                "status_label": result["status_label"],
                "source_label": result["source_label"],
                "on_hold": bool(result["on_hold"]),
                "miss_reason": result.get("miss_reason"),
                "miss_detail": result.get("miss_detail"),
                "record": result["full_record"],
            }
        )

    async def sync(request: Request) -> Response:
        device, failure = await authenticate(request)
        if failure:
            return failure
        try:
            body = await _read_body(request)
        except _BodyTooLarge:
            return _error("payload_too_large", 413)
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return _error("invalid_json", 400)
        ops = payload.get("ops") if isinstance(payload, dict) else None
        if not isinstance(ops, list):
            return _error("invalid_ops", 400)
        if len(ops) > MAX_OPS_PER_BATCH:
            return _error("too_many_ops", 413)

        results = await run_in_threadpool(
            process_ops,
            device["device_id"],
            ops,
            store=store,
            resolve=resolve,
            retention=retention,
        )
        touch(device["device_id"])
        return _json(
            {
                "server_time": datetime.now(UTC).replace(microsecond=0).isoformat(),
                "results": results,
            }
        )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        # Build the snapshot before the first handheld asks for it; at
        # production size that build takes several seconds.
        try:
            await run_in_threadpool(reference.get)
        except Exception:  # noqa: BLE001 — requests will retry and report 503
            logger.exception("Initial reference snapshot failed; will retry on demand.")
        yield

    return Starlette(
        lifespan=lifespan,
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/v1/reference/version", reference_version, methods=["GET"]),
            Route("/v1/reference/contract-lines", reference_pages, methods=["GET"]),
            Route("/v1/lookup", lookup, methods=["GET"]),
            Route("/v1/sync", sync, methods=["POST"]),
        ],
        middleware=[Middleware(GZipMiddleware, minimum_size=1024)],
    )
