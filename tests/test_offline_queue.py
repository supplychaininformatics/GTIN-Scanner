"""Tests for core.offline_queue — the encrypted, integrity-checked, auto-
expiring buffer for a transient Neon outage (ASVS-AUDIT.md findings #5/#8,
V1/V8)."""

from __future__ import annotations

import json
import time

import pytest

from core import offline_queue


@pytest.fixture(autouse=True)
def _isolated_queue(tmp_path, monkeypatch):
    """Every test gets its own queue file/key, never the real one, and never
    touches the real OS keychain."""
    monkeypatch.setattr(offline_queue, "_QUEUE_PATH", tmp_path / "pending_writes.enc")
    monkeypatch.setattr(offline_queue, "_FALLBACK_KEY_PATH", tmp_path / ".offline_queue_key")
    monkeypatch.setattr(offline_queue.secrets, "from_keyring", lambda key: None)
    monkeypatch.setattr(offline_queue.secrets, "store_in_keyring", lambda key, value: (_ for _ in ()).throw(RuntimeError("no keychain in tests")))
    monkeypatch.setattr(offline_queue, "_last_flush_attempt", 0.0)
    yield


def test_enqueue_then_pending_count():
    assert offline_queue.pending_count() == 0
    offline_queue.enqueue("record_scan", {"session_id": "abc", "result": {"gtin": "1"}})
    assert offline_queue.pending_count() == 1


def test_queue_file_is_encrypted_at_rest():
    offline_queue.enqueue("record_scan", {"session_id": "abc", "result": {"gtin": "00801741030024"}})
    raw_bytes = offline_queue._QUEUE_PATH.read_bytes()
    # The GTIN and session id must not appear in plaintext on disk, and the
    # file must not itself parse as JSON (i.e. it really is encrypted, not
    # just differently formatted).
    assert b"00801741030024" not in raw_bytes
    assert b"abc" not in raw_bytes
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw_bytes)


def test_flush_replays_queued_write_and_removes_it_on_success(monkeypatch):
    calls = []
    import core.store as real_store

    monkeypatch.setattr(real_store, "record_scan", lambda **kw: calls.append(kw))

    offline_queue.enqueue("record_scan", {"session_id": "abc", "result": {"gtin": "1"}})
    applied = offline_queue.flush()

    assert applied == 1
    assert calls == [{"session_id": "abc", "result": {"gtin": "1"}}]
    assert offline_queue.pending_count() == 0


def test_flush_keeps_entry_on_connectivity_error(monkeypatch):
    import psycopg

    import core.store as real_store

    def _boom(**kw):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(real_store, "record_scan", _boom)

    offline_queue.enqueue("record_scan", {"session_id": "abc", "result": {"gtin": "1"}})
    applied = offline_queue.flush()

    assert applied == 0
    assert offline_queue.pending_count() == 1


def test_flush_drops_entry_on_non_connectivity_error(monkeypatch):
    import core.store as real_store

    def _boom(**kw):
        raise ValueError("this GTIN column doesn't exist anymore")

    monkeypatch.setattr(real_store, "record_scan", _boom)

    offline_queue.enqueue("record_scan", {"session_id": "abc", "result": {"gtin": "1"}})
    applied = offline_queue.flush()

    assert applied == 0
    # Dropped, not retried forever — a bug in the replayed call would
    # otherwise loop on every rerun.
    assert offline_queue.pending_count() == 0


def test_flush_respects_cooldown(monkeypatch):
    import core.store as real_store

    calls = []
    monkeypatch.setattr(real_store, "record_scan", lambda **kw: calls.append(kw))
    offline_queue.enqueue("record_scan", {"session_id": "abc", "result": {"gtin": "1"}})

    first = offline_queue.flush()
    second = offline_queue.flush()  # immediately again — should be a no-op

    assert first == 1
    assert second == 0
    assert len(calls) == 1


def test_expired_entries_are_pruned(monkeypatch):
    offline_queue.enqueue("record_scan", {"session_id": "abc", "result": {"gtin": "1"}})
    # Fast-forward past _MAX_AGE_SECONDS without waiting in real time.
    future = time.time() + offline_queue._MAX_AGE_SECONDS + 1
    monkeypatch.setattr(offline_queue.time, "time", lambda: future)
    assert offline_queue.pending_count() == 0


def test_tampered_checksum_is_dropped_not_replayed(monkeypatch):
    import core.store as real_store

    calls = []
    monkeypatch.setattr(real_store, "record_scan", lambda **kw: calls.append(kw))

    offline_queue.enqueue("record_scan", {"session_id": "abc", "result": {"gtin": "1"}})

    # Tamper with the entry after enqueueing, as if the on-disk file (or the
    # key) had been altered/corrupted — load, mutate, re-save with the wrong
    # checksum left in place.
    entries = offline_queue._load()
    entries[0]["args"]["result"]["gtin"] = "9999999999999"  # payload changed
    offline_queue._save(entries)  # checksum on disk no longer matches args

    applied = offline_queue.flush()

    assert applied == 0
    assert calls == [], "a tampered entry must never be replayed"
    assert offline_queue.pending_count() == 0


def test_corrupted_queue_file_is_treated_as_empty():
    offline_queue._QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    offline_queue._QUEUE_PATH.write_bytes(b"not a valid fernet token")
    assert offline_queue.pending_count() == 0


def test_unknown_op_is_dropped(monkeypatch):
    offline_queue.enqueue("delete_everything", {"session_id": "abc"})
    applied = offline_queue.flush()
    assert applied == 0
    assert offline_queue.pending_count() == 0
