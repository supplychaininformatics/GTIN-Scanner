"""Tests that the admin audit log and refresh metadata are encrypted at rest
(ASVS-AUDIT.md finding #13, V8)."""

from __future__ import annotations

import pytest

from core import admin


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "_AUDIT_LOG_PATH", tmp_path / "admin_audit.enc")
    monkeypatch.setattr(admin, "_META_PATH", tmp_path / "refresh_meta.enc")
    monkeypatch.setattr(admin, "_FALLBACK_KEY_PATH", tmp_path / ".admin_log_key")
    monkeypatch.setattr(admin.secrets, "from_keyring", lambda key: None)
    monkeypatch.setattr(
        admin.secrets,
        "store_in_keyring",
        lambda key, value: (_ for _ in ()).throw(RuntimeError("no keychain in tests")),
    )
    yield


def test_audit_log_round_trips():
    admin.log_audit_event("access_granted", "supervisor@example.org")
    entries = admin.read_audit_log()
    assert len(entries) == 1
    assert entries[0]["email"] == "supervisor@example.org"
    assert entries[0]["event"] == "access_granted"


def test_audit_log_file_is_encrypted_at_rest():
    admin.log_audit_event("access_granted", "supervisor@example.org")
    raw = admin._AUDIT_LOG_PATH.read_bytes()
    assert b"supervisor@example.org" not in raw
    assert b"access_granted" not in raw


def test_audit_log_most_recent_first_and_respects_limit():
    for i in range(5):
        admin.log_audit_event("refresh", f"user{i}@example.org")
    entries = admin.read_audit_log(limit=3)
    assert len(entries) == 3
    assert entries[0]["email"] == "user4@example.org"  # most recent first


def test_audit_log_caps_at_max_records(monkeypatch):
    monkeypatch.setattr(admin, "_AUDIT_LOG_MAX_RECORDS", 3)
    for i in range(5):
        admin.log_audit_event("refresh", f"user{i}@example.org")
    entries = admin.read_audit_log(limit=100)
    assert len(entries) == 3
    assert entries[0]["email"] == "user4@example.org"
    assert entries[-1]["email"] == "user2@example.org"


def test_corrupted_audit_log_is_treated_as_empty():
    admin._AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    admin._AUDIT_LOG_PATH.write_bytes(b"not a valid fernet token")
    assert admin.read_audit_log() == []


def test_refresh_meta_round_trips():
    assert admin.read_refresh_meta() is None
    admin._write_refresh_meta("supervisor@example.org")
    meta = admin.read_refresh_meta()
    assert meta["by"] == "supervisor@example.org"
    assert "ts" in meta


def test_refresh_meta_file_is_encrypted_at_rest():
    admin._write_refresh_meta("supervisor@example.org")
    raw = admin._META_PATH.read_bytes()
    assert b"supervisor@example.org" not in raw


def test_cooldown_uses_encrypted_meta():
    assert admin.cooldown_remaining() == 0
    admin._write_refresh_meta("supervisor@example.org")
    assert admin.cooldown_remaining() > 0
