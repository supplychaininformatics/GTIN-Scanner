"""Tests for core.logsafe (ASVS-AUDIT.md item 7 — no log injection via a
crafted scan payload)."""

from __future__ import annotations

from core.logsafe import safe_log_value


def test_plain_value_passes_through():
    assert safe_log_value("00801741030024") == "00801741030024"


def test_none_becomes_empty_string():
    assert safe_log_value(None) == ""


def test_newlines_and_control_chars_are_stripped():
    malicious = "00801741030024\n2026-01-01 00:00:00 [INFO] fake log line injected"
    cleaned = safe_log_value(malicious)
    assert "\n" not in cleaned
    assert "\r" not in cleaned


def test_long_value_is_truncated():
    long_value = "1" * 500
    cleaned = safe_log_value(long_value, max_length=10)
    assert cleaned.startswith("1" * 10)
    assert len(cleaned) < len(long_value)
    assert "truncated" in cleaned


def test_non_string_values_are_stringified():
    assert safe_log_value(12345) == "12345"
