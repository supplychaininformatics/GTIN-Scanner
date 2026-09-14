"""Tests for core.secrets — layered secret lookup (env > keychain > Streamlit
secrets). Uses an in-memory fake keyring backend so these tests never touch
the real OS keychain."""

from __future__ import annotations

import pytest

from core import secrets


class _FakeKeyring:
    """Minimal in-memory stand-in for the `keyring` module's public API."""

    def __init__(self):
        self._store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self._store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self._store[(service, key)] = value


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = _FakeKeyring()
    import sys

    monkeypatch.setitem(sys.modules, "keyring", fake)
    return fake


def test_from_keyring_returns_none_when_unset(fake_keyring):
    assert secrets.from_keyring("does_not_exist") is None


def test_store_and_read_round_trip(fake_keyring):
    secrets.store_in_keyring("neon_database_url", "postgresql://example")
    assert secrets.from_keyring("neon_database_url") == "postgresql://example"


def test_from_keyring_returns_none_when_module_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "keyring":
            raise ImportError("no keyring in this environment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    assert secrets.from_keyring("neon_database_url") is None


def test_from_keyring_swallows_backend_errors(monkeypatch):
    import sys

    class _BrokenKeyring:
        def get_password(self, service, key):
            raise RuntimeError("keychain locked")

    monkeypatch.setitem(sys.modules, "keyring", _BrokenKeyring())
    assert secrets.from_keyring("neon_database_url") is None
