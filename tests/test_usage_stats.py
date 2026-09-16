"""Tests for core.usage_stats: the anomaly classifier (pure, no DB) and
record_goodid_lookup's must-never-break-a-scan contract."""

from __future__ import annotations

from contextlib import contextmanager

from core import usage_stats


# ── classify_anomaly ─────────────────────────────────────────────────────────
def test_insufficient_history_below_minimum():
    assert usage_stats.classify_anomaly(40, [30, 40, 50]) == "insufficient_history"


def test_normal_within_range():
    history = [30, 35, 40, 45, 50, 38, 42]
    assert usage_stats.classify_anomaly(40, history) == "normal"


def test_high_flags_a_large_spike():
    # Matches the user's own example: ~30-50/day normally, 200 in one day.
    history = [30, 35, 40, 45, 50, 38, 42]
    assert usage_stats.classify_anomaly(200, history) == "high"


def test_high_flags_via_absolute_margin_on_a_small_baseline():
    history = [2, 3, 2, 3, 2]
    # Ratio alone (1.75x) would only demand ~4-5 here; the absolute margin
    # guards against a tiny baseline making "high" trivially easy to hit.
    assert usage_stats.classify_anomaly(20, history) == "high"


def test_low_flags_a_large_drop_on_a_meaningful_baseline():
    history = [30, 35, 40, 45, 50, 38, 42]
    assert usage_stats.classify_anomaly(2, history) == "low"


def test_low_does_not_fire_on_a_tiny_baseline():
    # Baseline under LOW_MIN_BASELINE: a drop from ~2/day to 0 isn't a signal.
    history = [2, 3, 2, 1, 2]
    assert usage_stats.classify_anomaly(0, history) == "normal"


# ── record_goodid_lookup ─────────────────────────────────────────────────────
def test_record_goodid_lookup_writes_expected_row(monkeypatch):
    executed = []

    class _FakeCursor:
        def execute(self, sql, params):
            executed.append((sql, params))

    @contextmanager
    def _fake_cursor():
        yield _FakeCursor()

    monkeypatch.setattr(usage_stats, "_cursor", _fake_cursor)

    usage_stats.record_goodid_lookup(success=True, status_code=200, error_type=None)

    assert len(executed) == 1
    sql, params = executed[0]
    assert "INSERT INTO goodid_lookup_log" in sql
    _queried_at, success, status_code, error_type = params
    assert (success, status_code, error_type) == (True, 200, None)


def test_record_goodid_lookup_swallows_db_failure(monkeypatch, caplog):
    """A scan must never fail because this logging call couldn't reach
    Neon — see the function's docstring."""

    @contextmanager
    def _broken_cursor():
        raise RuntimeError("no database configured")
        yield  # pragma: no cover — unreachable, keeps this a generator

    monkeypatch.setattr(usage_stats, "_cursor", _broken_cursor)

    with caplog.at_level("WARNING"):
        usage_stats.record_goodid_lookup(success=False, status_code=None, error_type="timeout")

    assert "Failed to record GoodID lookup outcome" in caplog.text


def test_goodid_client_lookup_failure_never_raises_even_if_logging_is_broken(monkeypatch):
    """End-to-end: query_goodid() must still return a normal result even if
    core.usage_stats can't write to the database at all."""
    import httpx

    import api.goodid_client as goodid_client

    monkeypatch.setattr(goodid_client, "_breaker", None)
    monkeypatch.setattr(goodid_client.time, "sleep", lambda seconds: None)

    @contextmanager
    def _broken_cursor():
        raise RuntimeError("no database configured")
        yield  # pragma: no cover

    monkeypatch.setattr(usage_stats, "_cursor", _broken_cursor)

    def _refused(self, url, params=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.Client, "get", _refused)

    result = goodid_client.query_goodid("00801741030024")

    assert result.success is False
