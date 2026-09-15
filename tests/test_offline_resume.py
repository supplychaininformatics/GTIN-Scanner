"""Tests for resuming a session whose create_session write is still queued
(the residual gap noted in ASVS-COMPLIANCE.md's offline-queue section)."""

from __future__ import annotations

import streamlit as st

from core import offline_queue, session


def _reset_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(offline_queue, "_QUEUE_PATH", tmp_path / "pending_writes.enc")
    monkeypatch.setattr(offline_queue, "_FALLBACK_KEY_PATH", tmp_path / ".offline_queue_key")
    monkeypatch.setattr(offline_queue.secrets, "from_keyring", lambda key: None)
    monkeypatch.setattr(
        offline_queue.secrets,
        "store_in_keyring",
        lambda key, value: (_ for _ in ()).throw(RuntimeError("no keychain in tests")),
    )
    monkeypatch.setattr(offline_queue, "_last_flush_attempt", 0.0)


def _clean_session_state():
    for key in ("session_id", "sanford_id", "warehouse_location", "scan_history", "last_result"):
        st.session_state.pop(key, None)
    st.session_state.scan_nonce = 0


def test_find_pending_session_returns_none_when_absent(tmp_path, monkeypatch):
    _reset_queue(tmp_path, monkeypatch)
    assert offline_queue.find_pending_session("nonexistent") is None


def test_find_pending_session_reconstructs_row(tmp_path, monkeypatch):
    _reset_queue(tmp_path, monkeypatch)
    offline_queue.enqueue(
        "create_session",
        {"sanford_id": "jdoe", "location": "Sioux Falls GS1", "session_id": "abc123"},
    )
    pending = offline_queue.find_pending_session("abc123")
    assert pending is not None
    assert pending["sanford_id"] == "jdoe"
    assert pending["location"] == "Sioux Falls GS1"
    assert pending["status"] == "active"
    assert pending["ended_at"] is None


def test_pending_scans_for_session_filters_by_session_id(tmp_path, monkeypatch):
    _reset_queue(tmp_path, monkeypatch)
    offline_queue.enqueue(
        "create_session", {"sanford_id": "jdoe", "location": "SF", "session_id": "sess1"}
    )
    offline_queue.enqueue(
        "record_scan", {"session_id": "sess1", "result": {"gtin": "111"}}
    )
    offline_queue.enqueue(
        "record_scan", {"session_id": "other-session", "result": {"gtin": "999"}}
    )
    offline_queue.enqueue(
        "record_scan", {"session_id": "sess1", "result": {"gtin": "222"}}
    )

    results = offline_queue.pending_scans_for_session("sess1")
    assert [r["gtin"] for r in results] == ["111", "222"]


def test_resume_pending_session_rehydrates_state(tmp_path, monkeypatch):
    _reset_queue(tmp_path, monkeypatch)
    _clean_session_state()

    offline_queue.enqueue(
        "create_session",
        {"sanford_id": "jdoe", "location": "Sioux Falls GS1", "session_id": "sess1"},
    )
    offline_queue.enqueue(
        "record_scan",
        {
            "session_id": "sess1",
            "result": {
                "gtin": "00801741030024",
                "time": "10:00:00",
                "source": "cache",
                "source_label": "Contract Line",
                "status_key": "cache",
                "on_hold": False,
                "miss_reason": None,
                "miss_label": None,
                "miss_detail": None,
                "full_record": {"Scan": "00801741030024", "Item": "x"},
            },
        },
    )

    result = session.resume_pending_session("sess1")

    assert result is not None
    assert st.session_state.session_id == "sess1"
    assert st.session_state.sanford_id == "jdoe"
    assert st.session_state.warehouse_location == "Sioux Falls GS1"
    assert len(st.session_state.scan_history) == 1
    assert st.session_state.scan_history[0]["gtin"] == "00801741030024"
    assert st.session_state.scan_history[0]["pending_sync"] is True


def test_resume_pending_session_returns_none_for_unknown_id(tmp_path, monkeypatch):
    _reset_queue(tmp_path, monkeypatch)
    _clean_session_state()
    assert session.resume_pending_session("does-not-exist") is None
