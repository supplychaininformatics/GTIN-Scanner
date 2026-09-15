"""Tests for core.circuit_breaker (ASVS-AUDIT.md item 6)."""

from __future__ import annotations

import pytest

from core.circuit_breaker import CircuitBreaker, CircuitOpenError


def test_starts_closed():
    breaker = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=10)
    breaker.before_call()  # must not raise
    assert not breaker.is_open


def test_opens_after_threshold_failures():
    breaker = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=10)
    breaker.record_failure()
    breaker.record_failure()
    assert not breaker.is_open
    breaker.record_failure()
    assert breaker.is_open


def test_before_call_raises_when_open():
    breaker = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=10)
    breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        breaker.before_call()


def test_success_resets_failure_count():
    breaker = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=10)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    # Two more failures after a reset should not be enough to open a
    # threshold-3 breaker.
    assert not breaker.is_open


def test_cooldown_elapses_and_allows_a_trial(monkeypatch):
    breaker = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=5)
    breaker.record_failure()
    assert breaker.is_open

    import core.circuit_breaker as cb_module

    future = cb_module.time.time() + 6
    monkeypatch.setattr(cb_module.time, "time", lambda: future)

    assert not breaker.is_open
    breaker.before_call()  # must not raise once cooldown has elapsed


def test_failed_trial_after_cooldown_reopens(monkeypatch):
    breaker = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=5)
    breaker.record_failure()

    import core.circuit_breaker as cb_module

    future = cb_module.time.time() + 6
    monkeypatch.setattr(cb_module.time, "time", lambda: future)

    breaker.before_call()  # half-open trial allowed
    breaker.record_failure()  # trial failed
    assert breaker.is_open


def test_independent_breakers_do_not_share_state():
    a = CircuitBreaker("a", failure_threshold=1, cooldown_seconds=10)
    b = CircuitBreaker("b", failure_threshold=1, cooldown_seconds=10)
    a.record_failure()
    assert a.is_open
    assert not b.is_open
