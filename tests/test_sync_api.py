"""Tests for the handheld sync REST service (sync_api/).

The store is an in-memory fake that mirrors core.store's device-API contract
(ownership checks, exactly-once scan ops) — the SQL itself is exercised only
against a real Postgres, not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import psycopg
import pytest
from starlette.testclient import TestClient

from api import GoodIDResult
from core.lookup import resolve_scan
from engine.gtin import check_digit
from sync_api.app import create_app
from sync_api.auth import RateLimiter, TokenVerifier, hash_token
from sync_api.memory_store import InMemoryStore as FakeStore
from sync_api.reference import ReferenceData


def gtin14(payload13: str) -> str:
    return payload13 + check_digit(payload13)


HIT_A = gtin14("0084109876543")
HIT_B = gtin14("0084109876550")
HIT_C = gtin14("0084109876567")
MISS = gtin14("0099999999999")


def contract_df() -> pd.DataFrame:
    def row(gtin, item, hold=False):
        return {
            "global_trade_item_number": gtin,
            "low_uom_code_gtin": None,
            "vendor_item": item,
            "manufacturer_name": "ACME MEDICAL",
            "manufacturer_number": "B-" + item,
            "item_description": "Widget " + item,
            "item_description2": None,
            "item_description3": None,
            "item_number": "L" + item,
            "uom_unit_of_measure": "BX",
            "low_uom_code_unit_of_measure": "EA",
            "on_hold": hold,
        }

    return pd.DataFrame([row(HIT_A, "1"), row(HIT_B, "2", hold=True), row(HIT_C, "3")])


TOKEN = "good-token-for-dev1"
OTHER_TOKEN = "good-token-for-dev2"


def make_verifier():
    devices = {
        hash_token(TOKEN): {"device_id": "dev1", "label": "one"},
        hash_token(OTHER_TOKEN): {"device_id": "dev2", "label": "two"},
    }
    return TokenVerifier(devices.get)


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def goodid(monkeypatch):
    """Scriptable goodID: set .result to a GoodIDResult to control fallbacks."""

    class Ctl:
        calls: list[str] = []
        result = GoodIDResult(False, "", {}, 404, "HTTP 404")

    Ctl.calls = []

    def fake(gtin):
        Ctl.calls.append(gtin)
        return Ctl.result

    monkeypatch.setattr("core.lookup.query_goodid", fake)
    return Ctl


@pytest.fixture
def client(store, goodid):
    app = create_app(
        store=store,
        reference=ReferenceData(contract_df),
        verifier=make_verifier(),
        limiter=RateLimiter(1000, 60),
    )
    return TestClient(app)


def auth(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def now_iso(delta=timedelta(0)):
    return (datetime.now(UTC) + delta).replace(microsecond=0).isoformat()


def create_op(session="sess00000001", op="op-create-0001"):
    return {
        "type": "create_session", "op_id": op, "session_id": session,
        "sanford_id": "S123", "location": "DOCK-3", "created_at": now_iso(),
    }


def scan_op(raw, op, session="sess00000001", at=None):
    return {
        "type": "scan", "op_id": op, "session_id": session,
        "raw_scan": raw, "scanned_at": at or now_iso(),
    }


def sync(client, ops, token=TOKEN):
    return client.post("/v1/sync", json={"ops": ops}, headers=auth(token))


def statuses(response):
    return [r["status"] for r in response.json()["results"]]


# ── auth ─────────────────────────────────────────────────────────────────────
def test_healthz_is_open_and_minimal(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "path", ["/v1/reference/version", "/v1/reference/contract-lines", "/v1/lookup?code=1"]
)
def test_v1_routes_require_a_token(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth("wrong")).status_code == 401
    assert client.get(path, headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.post("/v1/sync", json={"ops": []}).status_code == 401


def test_valid_token_is_accepted(client):
    assert client.get("/v1/reference/version", headers=auth()).status_code == 200


def test_rate_limit_returns_429(store, goodid):
    app = create_app(
        store=store, reference=ReferenceData(contract_df),
        verifier=make_verifier(), limiter=RateLimiter(2, 60),
    )
    c = TestClient(app)
    assert c.get("/v1/reference/version", headers=auth()).status_code == 200
    assert c.get("/v1/reference/version", headers=auth()).status_code == 200
    r = c.get("/v1/reference/version", headers=auth())
    assert r.status_code == 429
    assert r.headers["retry-after"]
    # Limit is per device, not global.
    assert c.get("/v1/reference/version", headers=auth(OTHER_TOKEN)).status_code == 200


def test_database_down_during_auth_is_503_not_401(store, goodid):
    def boom(_digest):
        raise psycopg.OperationalError("db down")

    app = create_app(
        store=store, reference=ReferenceData(contract_df),
        verifier=TokenVerifier(boom), limiter=RateLimiter(100, 60),
    )
    assert TestClient(app).get("/v1/reference/version", headers=auth()).status_code == 503


def test_responses_are_not_cacheable(client):
    r = client.get("/v1/reference/version", headers=auth())
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"


# ── reference snapshot ───────────────────────────────────────────────────────
def test_reference_version(client):
    body = client.get("/v1/reference/version", headers=auth()).json()
    assert body["row_count"] == 3
    assert len(body["version"]) == 16


def test_reference_paging_walks_every_row_once(client):
    seen, after, version = [], None, None
    while True:
        params = {"limit": 2}
        if after:
            params["after"] = after
        if version:
            params["version"] = version
        body = client.get(
            "/v1/reference/contract-lines", params=params, headers=auth()
        ).json()
        version = body["version"]
        seen += [r["gtin"] for r in body["rows"]]
        after = body["next"]
        if after is None:
            break
    assert seen == sorted([HIT_A, HIT_B, HIT_C])


def test_reference_rows_match_what_the_server_would_display(client):
    body = client.get("/v1/reference/contract-lines", headers=auth()).json()
    rows = {r["gtin"]: r for r in body["rows"]}
    engine = ReferenceData(contract_df).get().engine
    for gtin in (HIT_A, HIT_B):
        expected = resolve_scan(gtin, engine)
        full, row = expected["full_record"], rows[gtin]
        assert row["item"] == full["Item"]
        assert row["company"] == full["Company"]
        assert row["description"] == full["Description"]
        assert row["lawson_id"] == full["LAWSON ID"]
        assert row["on_hold"] == expected["on_hold"]
    assert rows[HIT_B]["on_hold"] is True


def test_reference_version_pin_mismatch_is_409(client):
    r = client.get(
        "/v1/reference/contract-lines", params={"version": "stale"}, headers=auth()
    )
    assert r.status_code == 409
    assert r.json()["error"] == "version_changed"


@pytest.mark.parametrize("limit", ["0", "-1", "5001", "abc"])
def test_reference_rejects_bad_limit(client, limit):
    r = client.get("/v1/reference/contract-lines", params={"limit": limit}, headers=auth())
    assert r.status_code == 400


def _ref_with(loads, ttl=10):
    """A ReferenceData whose loader yields `loads` in turn (an Exception is
    raised), driven by a manual clock and a synchronous refresh."""
    it = iter(loads)
    now = {"t": 0.0}

    def load():
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    ref = ReferenceData(load, ttl_seconds=ttl, clock=lambda: now["t"], spawn=lambda fn: fn())
    return ref, now


def test_reference_stale_snapshot_is_served_while_refreshing_then_replaced():
    changed = contract_df().iloc[:1]
    ref, now = _ref_with([contract_df(), changed])
    first = ref.get()
    assert len(first.rows) == 3
    now["t"] = 100.0
    assert ref.get() is first  # served immediately; refresh ran behind it
    assert len(ref.get().rows) == 1


def test_reference_keeps_serving_last_snapshot_if_refresh_fails():
    ref, now = _ref_with([contract_df(), RuntimeError("lakehouse down")])
    first = ref.get()
    now["t"] = 100.0
    assert ref.get() is first
    assert ref.get() is first  # and doesn't retry on every request


def test_reference_first_build_failure_propagates():
    ref, _ = _ref_with([RuntimeError("lakehouse down")])
    with pytest.raises(RuntimeError):
        ref.get()


# ── lookup ───────────────────────────────────────────────────────────────────
def test_lookup_contract_hit(client):
    body = client.get("/v1/lookup", params={"code": HIT_A}, headers=auth()).json()
    assert body["status_key"] == "cache"
    assert body["record"]["Item"] == "1"


def test_lookup_composite_gs1_barcode(client):
    body = client.get("/v1/lookup", params={"code": "01" + HIT_A + "10LOT"}, headers=auth()).json()
    assert body["gtin"] == HIT_A


def test_lookup_rejects_empty_and_oversized_codes(client):
    assert client.get("/v1/lookup", params={"code": ""}, headers=auth()).status_code == 400
    assert client.get("/v1/lookup", params={"code": "1" * 300}, headers=auth()).status_code == 400
    assert client.get("/v1/lookup", params={"code": "12\x0034"}, headers=auth()).status_code == 400


def test_lookup_goodid_unreachable_is_503_not_a_false_not_found(client, goodid):
    goodid.result = GoodIDResult(False, MISS, {}, None, "timed out")
    r = client.get("/v1/lookup", params={"code": MISS}, headers=auth())
    assert r.status_code == 503


def test_lookup_goodid_404_is_a_real_not_found(client, goodid):
    r = client.get("/v1/lookup", params={"code": MISS}, headers=auth())
    assert r.status_code == 200
    assert r.json()["status_key"] == "notfound"


# ── sync: happy path and idempotency ─────────────────────────────────────────
def test_full_session_lifecycle(client, store):
    ops = [
        create_op(),
        scan_op(HIT_A, "op-scan-0001"),
        {"type": "end_session", "op_id": "op-end-00001", "session_id": "sess00000001",
         "ended_at": now_iso()},
    ]
    r = sync(client, ops)
    assert r.status_code == 200
    assert statuses(r) == ["applied", "applied", "applied"]
    assert store.sessions["sess00000001"]["status"] == "ended"
    assert store.scans[("sess00000001", HIT_A)]["result"]["status_key"] == "cache"
    assert "server_time" in r.json()


def test_resending_a_batch_does_not_double_count(client, store):
    ops = [create_op(), scan_op(HIT_A, "op-scan-0001")]
    assert statuses(sync(client, ops)) == ["applied", "applied"]
    assert statuses(sync(client, ops)) == ["duplicate", "duplicate"]
    assert store.scans[("sess00000001", HIT_A)]["scan_count"] == 1


def test_a_genuine_rescan_increments_the_count(client, store):
    sync(client, [create_op(), scan_op(HIT_A, "op-scan-0001")])
    sync(client, [scan_op(HIT_A, "op-scan-0002")])
    assert store.scans[("sess00000001", HIT_A)]["scan_count"] == 2


def test_rescan_does_not_call_goodid_again(client, goodid):
    sync(client, [create_op(), scan_op(MISS, "op-scan-0001")])
    sync(client, [scan_op(MISS, "op-scan-0002")])
    assert goodid.calls == [MISS]


def test_server_resolves_scans_and_ignores_client_supplied_records(client, store):
    forged = scan_op(HIT_A, "op-scan-0001")
    forged["record"] = {"Item": "FORGED"}
    forged["result"] = {"status_key": "cache", "full_record": {"Item": "FORGED"}}
    sync(client, [create_op(), forged])
    stored = store.scans[("sess00000001", HIT_A)]["result"]
    assert stored["full_record"]["Item"] == "1"


def test_goodid_resolves_contract_misses_at_sync_time(client, store, goodid):
    goodid.result = GoodIDResult(
        True, MISS, {"gudid": {"device": {"brandName": "FDA Brand"}}}, 200, None
    )
    sync(client, [create_op(), scan_op(MISS, "op-scan-0001")])
    assert store.scans[("sess00000001", MISS)]["result"]["status_key"] == "api"


def test_goodid_outage_yields_retry_and_stores_nothing(client, store, goodid):
    goodid.result = GoodIDResult(False, MISS, {}, None, "network down")
    r = sync(client, [create_op(), scan_op(MISS, "op-scan-0001")])
    assert statuses(r) == ["applied", "retry"]
    assert ("sess00000001", MISS) not in store.scans
    goodid.result = GoodIDResult(False, MISS, {}, 404, "not found")
    assert statuses(sync(client, [scan_op(MISS, "op-scan-0001")])) == ["applied"]


def test_future_timestamp_is_clamped_not_refused(client, store):
    future = now_iso(timedelta(hours=6))
    sync(client, [create_op(), scan_op(HIT_A, "op-scan-0001", at=future)])
    stored_at = store.scans[("sess00000001", HIT_A)]["scanned_at"]
    assert stored_at <= datetime.now(UTC)


# ── sync: authorization ──────────────────────────────────────────────────────
def test_device_cannot_write_into_another_devices_session(client, store):
    sync(client, [create_op()])
    r = sync(client, [scan_op(HIT_A, "op-scan-0001")], token=OTHER_TOKEN)
    assert statuses(r) == ["rejected"]
    assert r.json()["results"][0]["code"] == "session_not_owned"
    assert store.scans == {}


def test_device_cannot_claim_an_existing_session_id(client):
    sync(client, [create_op()])
    r = sync(client, [create_op(op="op-create-9999")], token=OTHER_TOKEN)
    assert r.json()["results"][0]["code"] == "session_not_owned"


def test_device_cannot_end_another_devices_session(client, store):
    sync(client, [create_op()])
    end = {"type": "end_session", "op_id": "op-end-00001", "session_id": "sess00000001",
           "ended_at": now_iso()}
    assert statuses(sync(client, [end], token=OTHER_TOKEN)) == ["rejected"]
    assert store.sessions["sess00000001"]["status"] == "active"


def test_scan_for_unknown_session_is_rejected_without_a_goodid_call(client, goodid):
    r = sync(client, [scan_op(MISS, "op-scan-0001", session="nosuchsession")])
    assert r.json()["results"][0]["code"] == "unknown_session"
    assert goodid.calls == []


# ── sync: validation ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda o: o.update(op_id="x"), "invalid_op_id"),
        (lambda o: o.update(op_id="has space id"), "invalid_op_id"),
        (lambda o: o.update(session_id="../../etc"), "invalid_session_id"),
        (lambda o: o.update(type="drop_table"), "invalid_type"),
        (lambda o: o.update(raw_scan=""), "invalid_raw_scan"),
        (lambda o: o.update(raw_scan="12\x0034"), "invalid_raw_scan"),
        (lambda o: o.update(raw_scan="1" * 300), "invalid_raw_scan"),
        (lambda o: o.update(raw_scan=12345), "invalid_raw_scan"),
        (lambda o: o.update(scanned_at="2026-01-01T00:00:00"), "invalid_scanned_at"),
        (lambda o: o.update(scanned_at="yesterday"), "invalid_scanned_at"),
        (lambda o: o.update(scanned_at=now_iso(timedelta(days=-30))), "too_old"),
        (lambda o: o.pop("scanned_at"), "invalid_scanned_at"),
    ],
)
def test_malformed_scan_ops_are_rejected(client, mutate, code):
    op = scan_op(HIT_A, "op-scan-0001")
    mutate(op)
    result = sync(client, [create_op(), op]).json()["results"][1]
    assert (result["status"], result["code"]) == ("rejected", code)


@pytest.mark.parametrize(
    ("field", "value"),
    [("sanford_id", ""), ("sanford_id", "x" * 65), ("location", "a\nb"), ("location", 5)],
)
def test_malformed_create_ops_are_rejected(client, field, value):
    op = create_op()
    op[field] = value
    assert statuses(sync(client, [op])) == ["rejected"]


def test_one_bad_op_does_not_sink_the_batch(client, store):
    bad = scan_op(HIT_A, "op-scan-0001")
    bad["type"] = "bogus"
    r = sync(client, [create_op(), bad, scan_op(HIT_B, "op-scan-0002")])
    assert statuses(r) == ["applied", "rejected", "applied"]
    assert ("sess00000001", HIT_B) in store.scans


def test_non_object_op_is_rejected(client):
    assert statuses(sync(client, ["nope", 5, None])) == ["rejected"] * 3


def test_invalid_barcode_is_recorded_not_dropped(client, store):
    r = sync(client, [create_op(), scan_op("not-a-barcode", "op-scan-0001")])
    assert statuses(r) == ["applied", "applied"]
    assert store.scans[("sess00000001", "not-a-barcode")]["result"]["miss_reason"] == "bad_gtin"


def test_gs1_group_separator_is_allowed_in_raw_scan(client):
    r = sync(client, [create_op(), scan_op("01" + HIT_A + "\x1d10LOT", "op-scan-0001")])
    assert statuses(r) == ["applied", "applied"]


# ── sync: request-level limits ───────────────────────────────────────────────
def test_invalid_json_is_400(client):
    r = client.post("/v1/sync", content=b"{nope", headers=auth())
    assert r.status_code == 400


@pytest.mark.parametrize("body", [{}, {"ops": "x"}, [], {"ops": {"a": 1}}])
def test_ops_must_be_a_list(client, body):
    assert client.post("/v1/sync", json=body, headers=auth()).status_code == 400


def test_too_many_ops_is_413(client):
    ops = [scan_op(HIT_A, f"op-scan-{i:05d}") for i in range(101)]
    assert sync(client, ops).status_code == 413


def test_oversized_body_is_413(client):
    r = client.post("/v1/sync", content=b"x" * (300 * 1024), headers=auth())
    assert r.status_code == 413


# ── sync: failure handling ───────────────────────────────────────────────────
def test_database_outage_marks_remaining_ops_retry(client, store):
    sync(client, [create_op()])
    store.fail_with = psycopg.OperationalError("down")
    r = sync(client, [scan_op(HIT_A, "op-scan-0001"), scan_op(HIT_B, "op-scan-0002")])
    assert r.status_code == 200
    assert statuses(r) == ["retry", "retry"]
    assert {x["code"] for x in r.json()["results"]} == {"database_unavailable"}


def test_unexpected_error_is_retry_and_does_not_leak_details(client, store):
    sync(client, [create_op()])
    store.fail_with = RuntimeError("secret internal detail")
    r = sync(client, [scan_op(HIT_A, "op-scan-0001")])
    assert statuses(r) == ["retry"]
    assert "secret" not in r.text


def test_deadline_stops_resolution_and_asks_for_retry(store, goodid, monkeypatch):
    monkeypatch.setattr("sync_api.sync.DEADLINE_SECONDS", -1.0)
    app = create_app(
        store=store, reference=ReferenceData(contract_df),
        verifier=make_verifier(), limiter=RateLimiter(100, 60),
    )
    r = sync(TestClient(app), [create_op()])
    assert statuses(r) == ["retry"]
    assert r.json()["results"][0]["code"] == "deadline"


def test_last_seen_is_recorded_but_throttled(client, store):
    sync(client, [])
    sync(client, [])
    assert store.touched == ["dev1"]
