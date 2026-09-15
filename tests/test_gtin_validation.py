"""Tests for engine.gtin's validation primitives, and for core.lookup.resolve_scan
refusing to send an invalid scan to the GUDID API (ASVS-AUDIT.md finding #3)."""

from __future__ import annotations

import pandas as pd
import pytest

from core.lookup import resolve_scan
from engine.gtin import check_digit, check_digit_valid, normalize
from engine.lookup import LookupEngine


# ── engine.gtin primitives ───────────────────────────────────────────────────
def test_normalize_pads_short_gtins():
    assert normalize("801741030024") == "00801741030024"


def test_normalize_rejects_non_digits():
    assert normalize("ABC123") == ""


def test_normalize_rejects_out_of_range_length():
    assert normalize("1234567") == ""  # 7 digits, below MIN_LEN
    assert normalize("1" * 15) == ""  # 15 digits, above MAX_LEN


def test_check_digit_valid_true_for_real_gtin():
    # 00841098765432's check digit recomputed for correctness.
    payload = "0084109876543"
    gtin = payload + check_digit(payload)
    assert check_digit_valid(gtin)


def test_check_digit_valid_false_for_tampered_gtin():
    payload = "0084109876543"
    good = payload + check_digit(payload)
    bad_digit = "0" if good[-1] != "0" else "1"
    tampered = good[:-1] + bad_digit
    assert not check_digit_valid(tampered)


def test_check_digit_valid_false_for_garbage():
    assert not check_digit_valid("not-a-gtin-at-all")
    assert not check_digit_valid("")
    assert not check_digit_valid(None)


# ── resolve_scan: invalid scans never reach the network ─────────────────────
@pytest.fixture
def empty_engine() -> LookupEngine:
    df = pd.DataFrame(
        {
            "global_trade_item_number": pd.Series(dtype=str),
            "low_uom_code_gtin": pd.Series(dtype=str),
        }
    )
    return LookupEngine(df)


def test_invalid_scan_never_calls_goodid(empty_engine, monkeypatch):
    called = []
    monkeypatch.setattr(
        "core.lookup.query_goodid", lambda gtin: called.append(gtin) or None
    )
    result = resolve_scan("not-a-real-barcode!!", empty_engine)
    assert called == [], "query_goodid must not be called for a structurally invalid scan"
    assert result["status_key"] == "notfound"
    assert result["source_label"] == "Invalid Barcode"
    assert result["miss_reason"] == "bad_gtin"


def test_bad_check_digit_never_calls_goodid(empty_engine, monkeypatch):
    called = []
    monkeypatch.setattr(
        "core.lookup.query_goodid", lambda gtin: called.append(gtin) or None
    )
    payload = "0084109876543"
    good = payload + check_digit(payload)
    bad_digit = "0" if good[-1] != "0" else "1"
    tampered = good[:-1] + bad_digit

    result = resolve_scan(tampered, empty_engine)
    assert called == []
    assert result["miss_reason"] == "bad_gtin"


def test_valid_but_unknown_gtin_still_calls_goodid(empty_engine, monkeypatch):
    """A well-formed GTIN that just isn't on contract must still hit the API
    fallback — only structurally-invalid scans are short-circuited."""
    called = []

    class _FakeResult:
        success = False
        payload = {}

    monkeypatch.setattr(
        "core.lookup.query_goodid",
        lambda gtin: (called.append(gtin), _FakeResult())[1],
    )
    payload = "0084109876543"
    good_gtin = payload + check_digit(payload)

    resolve_scan(good_gtin, empty_engine)
    assert called == [good_gtin]
