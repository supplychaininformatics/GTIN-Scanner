"""Tests for api.goodid_client's retry/circuit-breaker behavior
(ASVS-AUDIT.md item 6) — separate from tests/test_egress.py, which covers
the allowlist check on the same call path."""

from __future__ import annotations

import httpx
import pytest

import api.goodid_client as goodid_client


@pytest.fixture(autouse=True)
def _fresh_breaker(monkeypatch):
    """Each test gets its own breaker instance, not the process-wide
    singleton, so tests can't leak open/closed state between each other."""
    monkeypatch.setattr(goodid_client, "_breaker", None)
    # No real waiting in tests.
    monkeypatch.setattr(goodid_client.time, "sleep", lambda seconds: None)
    yield


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = "error body"

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://accessgudid.nlm.nih.gov/x")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._json


def test_successful_call_closes_breaker_and_returns_payload(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get", lambda self, url, params=None: _FakeResponse(200, {"gudid": {}})
    )
    result = goodid_client.query_goodid("00801741030024")
    assert result.success is True
    assert not goodid_client._get_breaker().is_open


def test_timeout_retries_once_then_fails(monkeypatch):
    calls = []

    def _get(self, url, params=None):
        calls.append(1)
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.Client, "get", _get)
    result = goodid_client.query_goodid("00801741030024")

    assert result.success is False
    assert len(calls) == goodid_client._MAX_ATTEMPTS


def test_http_error_response_does_not_retry(monkeypatch):
    """A definitive HTTP response (even an error one) is not a connectivity
    failure — retrying it would just add latency for the same answer."""
    calls = []

    def _get(self, url, params=None):
        calls.append(1)
        return _FakeResponse(404)

    monkeypatch.setattr(httpx.Client, "get", _get)
    result = goodid_client.query_goodid("00801741030024")

    assert result.success is False
    assert len(calls) == 1
    assert not goodid_client._get_breaker().is_open, (
        "an HTTP error response must not trip the breaker"
    )


def test_breaker_opens_after_repeated_connectivity_failures(monkeypatch):
    def _refused(self, url, params=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.Client, "get", _refused)
    for _ in range(3):
        goodid_client.query_goodid("00801741030024")

    assert goodid_client._get_breaker().is_open


def test_breaker_open_short_circuits_without_network_call(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, params=None: calls.append(1))

    breaker = goodid_client._get_breaker()
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_failure()  # now open

    result = goodid_client.query_goodid("00801741030024")

    assert result.success is False
    assert calls == [], "no network call should be attempted while the breaker is open"
