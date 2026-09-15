"""Tests for data.loader._load_from_lakehouse's connection retry/circuit
breaker (ASVS-AUDIT.md item 6)."""

from __future__ import annotations

import pyodbc
import pytest

import data.loader as loader


@pytest.fixture(autouse=True)
def _fabric_env(monkeypatch):
    monkeypatch.setenv("FABRIC_SQL_ENDPOINT", "myworkspace.datawarehouse.fabric.microsoft.com")
    monkeypatch.setenv("FABRIC_DATABASE", "mylakehouse")
    monkeypatch.setattr(loader, "_fabric_breaker", None)
    monkeypatch.setattr(loader.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(loader, "_fabric_access_token", lambda: b"fake-token")
    yield


def test_connection_error_retries_then_raises(monkeypatch):
    calls = []

    def _connect(conn_str, attrs_before=None):
        calls.append(1)
        raise pyodbc.OperationalError("08001", "connection refused")

    monkeypatch.setattr(pyodbc, "connect", _connect)

    with pytest.raises(pyodbc.OperationalError):
        loader._load_from_lakehouse()

    assert len(calls) == loader._FABRIC_MAX_ATTEMPTS


def test_driver_missing_error_is_not_retried(monkeypatch):
    calls = []

    def _connect(conn_str, attrs_before=None):
        calls.append(1)
        raise pyodbc.InterfaceError("IM002", "data source name not found")

    monkeypatch.setattr(pyodbc, "connect", _connect)

    with pytest.raises(RuntimeError, match="ODBC driver"):
        loader._load_from_lakehouse()

    assert len(calls) == 1, "a missing driver is a config problem, not worth retrying"


def test_breaker_opens_after_repeated_connection_failures(monkeypatch):
    def _connect(conn_str, attrs_before=None):
        raise pyodbc.OperationalError("08001", "connection refused")

    monkeypatch.setattr(pyodbc, "connect", _connect)

    for _ in range(2):  # failure_threshold=2 for the fabric breaker
        with pytest.raises(pyodbc.OperationalError):
            loader._load_from_lakehouse()

    assert loader._fabric_breaker.is_open


def test_breaker_open_short_circuits_without_connect_attempt(monkeypatch):
    calls = []
    monkeypatch.setattr(pyodbc, "connect", lambda *a, **kw: calls.append(1))

    from core.circuit_breaker import CircuitBreaker

    loader._fabric_breaker = CircuitBreaker("fabric", failure_threshold=1, cooldown_seconds=60.0)
    loader._fabric_breaker.record_failure()  # now open

    with pytest.raises(RuntimeError, match="Circuit"):
        loader._load_from_lakehouse()

    assert calls == [], "no connection attempt should be made while the breaker is open"
