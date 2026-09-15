"""Integration tests: core.session's write paths degrade to the offline
queue on a Neon connectivity failure, instead of crashing the handheld scan
loop (ASVS-AUDIT.md finding #5)."""

from __future__ import annotations

import psycopg
import pytest
import streamlit as st

from core import offline_queue, session, store


@pytest.fixture(autouse=True)
def _isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(offline_queue, "_QUEUE_PATH", tmp_path / "pending_writes.enc")
    monkeypatch.setattr(offline_queue, "_FALLBACK_KEY_PATH", tmp_path / ".offline_queue_key")
    monkeypatch.setattr(offline_queue.secrets, "from_keyring", lambda key: None)
    monkeypatch.setattr(
        offline_queue.secrets,
        "store_in_keyring",
        lambda key, value: (_ for _ in ()).throw(RuntimeError("no keychain in tests")),
    )
    monkeypatch.setattr(offline_queue, "_last_flush_attempt", 0.0)
    yield


@pytest.fixture(autouse=True)
def _clean_session_state():
    for key in ("session_id", "sanford_id", "warehouse_location", "scan_history", "last_result"):
        st.session_state.pop(key, None)
    st.session_state.scan_nonce = 0
    yield


def _neon_down(*a, **kw):
    raise psycopg.OperationalError("connection refused")


def test_start_session_queues_on_connectivity_failure(monkeypatch):
    monkeypatch.setattr(store, "create_session", _neon_down)

    session.start_session("jdoe", "Sioux Falls GS1")

    assert st.session_state.session_id is not None, "a session id must exist locally even offline"
    assert offline_queue.pending_count() == 1


def test_start_session_succeeds_normally_when_neon_is_up(monkeypatch):
    calls = []
    monkeypatch.setattr(
        store,
        "create_session",
        lambda sanford_id, location, session_id=None: calls.append(session_id) or session_id,
    )

    session.start_session("jdoe", "Sioux Falls GS1")

    assert calls == [st.session_state.session_id]
    assert offline_queue.pending_count() == 0


def test_record_scan_queues_and_shows_pending_locally(monkeypatch):
    st.session_state.session_id = "sess1"
    st.session_state.scan_history = []
    monkeypatch.setattr(store, "record_scan", _neon_down)

    result = {
        "gtin": "00801741030024",
        "time": "10:00:00",
        "source": "cache",
        "source_label": "Contract Line",
        "status_key": "cache",
        "on_hold": False,
        "miss_reason": None,
        "miss_label": None,
        "miss_detail": None,
        "full_record": {"Scan": "00801741030024", "Item": "x", "GTIN": "00801741030024"},
    }
    session.record_scan(result)

    assert offline_queue.pending_count() == 1
    assert st.session_state.last_result["persisted"] is False
    assert len(st.session_state.scan_history) == 1
    assert st.session_state.scan_history[0]["pending_sync"] is True
    assert st.session_state.scan_history[0]["gtin"] == "00801741030024"


def test_record_scan_non_connectivity_error_still_raises(monkeypatch):
    st.session_state.session_id = "sess1"
    st.session_state.scan_history = []

    def _bug(*a, **kw):
        raise ValueError("programming error, not a network issue")

    monkeypatch.setattr(store, "record_scan", _bug)

    result = {
        "gtin": "1", "time": "10:00:00", "source": "cache", "source_label": "Contract Line",
        "status_key": "cache", "on_hold": False, "miss_reason": None, "miss_label": None,
        "miss_detail": None, "full_record": {},
    }
    with pytest.raises(ValueError):
        session.record_scan(result)

    # A real bug must not be swallowed into "offline" — nothing should be
    # queued for it, since replaying the identical buggy call would never
    # succeed.
    assert offline_queue.pending_count() == 0


def test_end_session_queues_on_connectivity_failure(monkeypatch):
    st.session_state.session_id = "sess1"
    st.session_state.sanford_id = "jdoe"
    st.session_state.warehouse_location = "Sioux Falls GS1"
    st.session_state.scan_history = []
    st.session_state.last_result = None
    monkeypatch.setattr(store, "end_session", _neon_down)

    session.end_session()

    assert offline_queue.pending_count() == 1
    # Local state resets to the start gate regardless — see end_session's
    # docstring for why there's nothing useful to keep around locally.
    assert st.session_state.session_id is None
