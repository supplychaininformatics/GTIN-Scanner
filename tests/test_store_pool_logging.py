"""Tests that core.store._get_pool logs the Neon host (never the full
connection string / password) on open and on failure (ASVS-AUDIT.md item 7)."""

from __future__ import annotations

import pytest

from core import store


@pytest.fixture(autouse=True)
def _reset_pool(monkeypatch):
    monkeypatch.setattr(store, "_pool", None)
    monkeypatch.setenv(
        "NEON_DATABASE_URL",
        "postgresql://user:supersecretpassword@ep-example.us-east-2.aws.neon.tech/neondb?sslmode=require",
    )
    yield
    monkeypatch.setattr(store, "_pool", None)


def test_pool_open_logs_host_not_password(monkeypatch, caplog):
    class _FakePool:
        check_connection = staticmethod(lambda *a, **kw: None)

        def __init__(self, *a, **kw):
            pass

        def open(self):
            pass

    monkeypatch.setattr(store, "ConnectionPool", _FakePool)
    monkeypatch.setattr(store, "atexit", store.atexit)  # no-op, just avoid surprises

    with caplog.at_level("INFO"):
        store._get_pool()

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "ep-example.us-east-2.aws.neon.tech" in logged
    assert "supersecretpassword" not in logged


def test_pool_open_failure_logs_host_and_reraises(monkeypatch, caplog):
    class _FakePool:
        check_connection = staticmethod(lambda *a, **kw: None)

        def __init__(self, *a, **kw):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(store, "ConnectionPool", _FakePool)

    with caplog.at_level("INFO"), pytest.raises(RuntimeError, match="connection refused"):
        store._get_pool()

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "ep-example.us-east-2.aws.neon.tech" in logged
    assert "supersecretpassword" not in logged
