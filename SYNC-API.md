# Handheld Sync API

REST service (`sync_api/`) that lets a handheld keep scanning with no network
and sync when it has one. It is the server half of the offline-first Android
client in [android/](android/README.md); the Streamlit app is unchanged and
runs alongside it. To develop a client without Neon or a registered device, run
`DATA_SOURCE=mock python -m sync_api.dev_server` (loopback only, in-memory,
token `dev-token`).

## Model

The handheld keeps two things on the device: a **mirror of the contract lines**
(for instant offline lookup) and a **queue of operations** (create session,
scan, end session). It uploads the queue whenever it can reach this service.

The device sends **raw facts only** — session identity, the raw barcode string,
and when it happened. The server derives everything else (GTIN extraction,
contract-line match, goodID fallback for items not on contract, miss reasons)
from its own data. So a scan made offline against the mirror is a *provisional
display*; the authoritative record is created at sync time. On the device, a
mirror miss should show "not on contract file — will be verified when online",
not a final Not Found (goodID can't be mirrored; it is queried server-side).

## Running it

```
# once: create the tables (needs NEON_DATABASE_URL)
psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/005_device_api.sql

# register a handheld — prints its token ONCE
python -m scripts.manage_devices add "Dock 3 handheld"
python -m scripts.manage_devices list
python -m scripts.manage_devices revoke <device_id>     # lost/stolen device

uvicorn sync_api.app:create_app --factory --host 0.0.0.0 --port 8080
```

Serve it over **HTTPS only** (terminate TLS at Sanford's reverse proxy or pass
`--ssl-keyfile/--ssl-certfile`); tokens are bearer credentials. Run a single
process — the rate limiter and reference snapshot are in-process. Revocation
takes up to ~60 s to take effect (auth cache).

## Auth

`Authorization: Bearer <token>` on every `/v1` call. Missing/invalid → `401`.
Per-device limit of 300 requests/minute → `429` with `Retry-After`.
A database outage during auth returns `503` (not `401`) so clients don't
mistake it for a revoked token.

## Endpoints

### `GET /healthz`
Unauthenticated liveness: `{"status":"ok"}`.

### `GET /v1/reference/version`
`{"version": "795154b03a5c4360", "generated_at": "...", "row_count": 87218}`
Poll this cheaply (e.g. on connect); download the mirror only if `version`
differs from what is stored on the device.

### `GET /v1/reference/contract-lines?version=&after=&limit=`
The mirror, in pages of `limit` rows (default 2000, max 5000) ordered by
`gtin`. Start with no `after`; pass the previous response's `next` as `after`
until `next` is `null`. Always pass the `version` you started with:

```
{"version": "...", "rows": [
  {"gtin": "10014566200757", "item": "V8515", "company": "...", "brand": "...",
   "description": "...", "gtin_uom": "CA", "uou": "-", "lawson_id": "6331779",
   "lawson_uom": "-", "on_hold": false}, ...], "next": "10705031057920"}
```

- The download is **resumable**: if the connection drops, resume from the last
  `next` cursor you saved. Gzip is supported (~3 MB total at ~87k rows).
- If the data refreshes mid-download the server answers `409
  {"error":"version_changed","version":"<new>"}` — discard the partial mirror
  and restart against the new version. Swap the mirror in only after the last
  page arrives.
- `gtin` is the exact string the server matches on (rows may be 12/13/14
  digits). Resolve a scan by extracting the GTIN (below) and doing an
  **exact string match**. No normalisation.

**GS1 extraction** (same as the server): strip whitespace; if the code matches
`^(\][A-Za-z0-9]{2})?01(\d{14})`, the GTIN is group 2; otherwise the whole
trimmed string is the GTIN.

### `GET /v1/lookup?code=<raw scan>`
Online resolve (contract line, then goodID). `200`:
`{"gtin","status_key","status_label","source_label","on_hold","miss_reason","miss_detail","record":{...}}`.
`503 upstream_unavailable` means goodID could not be reached — not a real
Not Found. Use it when online; offline, use the mirror.

### `POST /v1/sync`
Body (max 256 KB, max 100 ops), applied **in order**:

```
{"ops": [
  {"type":"create_session","op_id":"<id>","session_id":"<id>",
   "sanford_id":"S123","location":"DOCK-3","created_at":"2026-09-23T18:00:00+00:00"},
  {"type":"scan","op_id":"<id>","session_id":"<id>",
   "raw_scan":"0100841098765432 ...","scanned_at":"2026-09-23T18:00:05+00:00"},
  {"type":"end_session","op_id":"<id>","session_id":"<id>",
   "ended_at":"2026-09-23T18:30:00+00:00"}
]}
```

- `op_id`, `session_id`: 8–64 chars of `[A-Za-z0-9_-]`. **The device mints
  both** (a UUID is fine) so it can queue ops before it ever reaches the
  server. `op_id` must be unique per op and **reused verbatim on retry** —
  that is what makes a re-sent scan count once.
- Timestamps: ISO-8601 **with** offset. Older than 3 days (the retention
  window) → rejected `too_old`. A timestamp in the future is clamped to now.
- `raw_scan`: the barcode string exactly as scanned (≤256 chars; GS1 group
  separator `\x1d` allowed, other control characters rejected).
- A device can only modify sessions it created. Anything else is rejected.

Response `200`:

```
{"server_time":"...","results":[{"op_id":"...","status":"applied"}, ...]}
```

One result per op, same order. Per-op `status`:

| status      | meaning                                             | device should |
|-------------|-----------------------------------------------------|---------------|
| `applied`   | done                                                | remove from queue |
| `duplicate` | already applied on an earlier attempt               | remove from queue |
| `rejected`  | can never succeed as sent; `code` says why          | remove, log/surface |
| `retry`     | not possible right now (`database_unavailable`, `lookup_unavailable`, `deadline`, `server_error`) | keep, resend later with backoff |

`rejected` codes: `invalid_<field>`, `invalid_type`, `too_old`,
`unknown_session`, `session_not_owned`. Because `server_time` is returned,
the client can detect clock drift.

Request-level errors: `400 invalid_json|invalid_ops`, `413 payload_too_large|too_many_ops`,
`401`, `429`, `503`. Any non-`200` means *nothing in the batch was processed* —
resend the whole batch.

## Client rules that keep the data correct

1. Queue ops in the order they happen; upload in that order. Don't drop the
   `create_session` op before it is `applied`/`duplicate`.
2. Never edit a queued op; never reuse an `op_id` for a different op.
3. A rescan of the same GTIN in a session is just another `scan` op — the
   server increments the count.
4. Persist the queue transactionally on the device (SQLite) so a battery
   pull mid-scan cannot lose an acknowledged scan.

## Security properties

- Per-device tokens; only a SHA-256 is stored server-side; revocable.
- Requests never query the lakehouse. Reference data comes from the shared
  loader's cached, circuit-breaker-guarded refresh (24 h cache).
- Strict input validation, body-size cap, batch cap, per-device rate limit,
  responses `Cache-Control: no-store`.
- A device cannot write arbitrary product data (server-derived) or touch
  another device's sessions.
- The goodID egress allowlist (`core/egress.py`) still applies to server-side
  resolution.
