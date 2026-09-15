"""Tests for the contract-data cache's at-rest encryption and hard expiry
ceiling (ASVS-AUDIT.md finding #8, V8)."""

from __future__ import annotations

import time

import pandas as pd
import pytest

import data.loader as loader


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "CACHE_PATH", tmp_path / "contract_lines.parquet")
    monkeypatch.setattr(loader, "_CACHE_FALLBACK_KEY_PATH", tmp_path / ".contract_cache_key")
    yield


@pytest.fixture(autouse=True)
def _no_real_keyring(monkeypatch):
    """Force the local-key-file fallback path so these tests never touch the
    real OS keychain (and stay deterministic across machines/CI)."""
    import core.secrets as secrets_module

    monkeypatch.setattr(secrets_module, "from_keyring", lambda key: None)

    def _boom(key, value):
        raise RuntimeError("no keychain in tests")

    monkeypatch.setattr(secrets_module, "store_in_keyring", _boom)
    yield


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "global_trade_item_number": ["00801741030024"],
            "manufacturer_name": ["ACME SURGICAL SUPPLY CO"],
        }
    )


def test_write_then_read_round_trips():
    df = _sample_df()
    loader._write_cache(df)
    result = loader._read_cache(enforce_max_age=False)
    assert result is not None
    assert result["global_trade_item_number"].tolist() == ["00801741030024"]


def test_cache_file_is_encrypted_at_rest():
    loader._write_cache(_sample_df())
    raw_bytes = loader.CACHE_PATH.read_bytes()
    assert b"ACME SURGICAL SUPPLY CO" not in raw_bytes
    assert b"00801741030024" not in raw_bytes


def test_missing_cache_returns_none():
    assert loader._read_cache(enforce_max_age=False) is None
    assert loader._read_cache(enforce_max_age=True) is None


def test_corrupted_cache_is_treated_as_absent():
    loader.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    loader.CACHE_PATH.write_bytes(b"not a valid fernet token")
    assert loader._read_cache(enforce_max_age=False) is None


def test_plaintext_legacy_cache_is_treated_as_absent():
    """A pre-encryption plaintext Parquet file (from before this change
    shipped) must not crash the app — it should just look like no cache."""
    import io

    buf = io.BytesIO()
    _sample_df().to_parquet(buf)
    loader.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    loader.CACHE_PATH.write_bytes(buf.getvalue())
    assert loader._read_cache(enforce_max_age=False) is None


def test_cache_older_than_ceiling_is_refused_when_enforced(monkeypatch):
    loader._write_cache(_sample_df())
    old_time = time.time() - loader._MAX_CACHE_AGE_SECONDS - 3600
    import os

    os.utime(loader.CACHE_PATH, (old_time, old_time))

    assert loader._read_cache(enforce_max_age=True) is None
    # Without enforcement (the "still fresh enough, use instantly" path)
    # it's still readable — enforcement only applies to the stale-fallback
    # path, not to a hard read failure.
    assert loader._read_cache(enforce_max_age=False) is not None


def test_cache_just_under_ceiling_is_still_usable():
    loader._write_cache(_sample_df())
    recent_time = time.time() - loader._MAX_CACHE_AGE_SECONDS + 3600
    import os

    os.utime(loader.CACHE_PATH, (recent_time, recent_time))
    assert loader._read_cache(enforce_max_age=True) is not None
