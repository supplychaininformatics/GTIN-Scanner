"""Tests for core.store._conninfo — TLS enforcement on the Neon connection
string (ASVS-AUDIT.md finding #9 / V9)."""

from __future__ import annotations

import pytest

from core import store


def test_missing_sslmode_is_rejected(monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://user:pass@host/db")
    with pytest.raises(RuntimeError, match="sslmode"):
        store._conninfo()


def test_sslmode_require_is_accepted(monkeypatch):
    url = "postgresql://user:pass@host/db?sslmode=require&channel_binding=require"
    monkeypatch.setenv("NEON_DATABASE_URL", url)
    assert store._conninfo() == url


def test_sslmode_verify_full_is_accepted(monkeypatch):
    url = "postgresql://user:pass@host/db?sslmode=verify-full"
    monkeypatch.setenv("NEON_DATABASE_URL", url)
    assert store._conninfo() == url


def test_database_url_env_var_also_enforced(monkeypatch):
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db?sslmode=disable")
    with pytest.raises(RuntimeError, match="sslmode"):
        store._conninfo()


def test_keyring_is_preferred_over_streamlit_secrets(monkeypatch):
    """env var absent, keychain has a value -> keychain wins without ever
    touching st.secrets (which isn't even importable in this test)."""
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    keychain_url = "postgresql://user:pass@keychain-host/db?sslmode=require"
    monkeypatch.setattr(store.secrets, "from_keyring", lambda key: keychain_url)
    assert store._conninfo() == keychain_url
