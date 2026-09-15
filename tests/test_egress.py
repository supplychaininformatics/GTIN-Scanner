"""Tests for core.egress — the application-level outbound-host allowlist."""

from __future__ import annotations

import pytest

from core import egress


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with no Fabric/Neon config, so allowed_hosts() is
    deterministic (just GUDID) unless a test opts in.

    Also blocks the real OS-keychain fallback: without NEON_DATABASE_URL set,
    core.store._conninfo() falls through to secrets.from_keyring(), which
    hits the actual keychain — on macOS that can raise a first-use
    authorization prompt for whatever Python binary is running the tests,
    which blocks forever in a non-interactive run (confirmed: this hung two
    separate CI-prep attempts before being tracked down here). Every test in
    this file must be isolated from real system state, not just real env
    vars.
    """
    monkeypatch.delenv("FABRIC_SQL_ENDPOINT", raising=False)
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("core.secrets.from_keyring", lambda key: None)


def test_gudid_host_always_allowed():
    assert egress.GUDID_HOST in egress.allowed_hosts()


def test_gudid_url_passes():
    egress.assert_allowed_url("https://accessgudid.nlm.nih.gov/api/v2/devices/lookup.json")


def test_unknown_host_blocked():
    with pytest.raises(egress.EgressBlocked):
        egress.assert_allowed_url("https://evil.example.com/steal")


def test_fabric_endpoint_is_allowlisted_when_configured(monkeypatch):
    monkeypatch.setenv("FABRIC_SQL_ENDPOINT", "myworkspace.datawarehouse.fabric.microsoft.com")
    hosts = egress.allowed_hosts()
    assert "myworkspace.datawarehouse.fabric.microsoft.com" in hosts
    assert egress.GUDID_HOST in hosts


def test_neon_host_is_allowlisted_when_configured(monkeypatch):
    monkeypatch.setenv(
        "NEON_DATABASE_URL",
        "postgresql://user:pass@ep-example.us-east-2.aws.neon.tech/neondb?sslmode=require",
    )
    hosts = egress.allowed_hosts()
    assert "ep-example.us-east-2.aws.neon.tech" in hosts


def test_no_neon_env_var_does_not_crash_allowlist():
    # No NEON_DATABASE_URL, keychain mocked out (see _clean_env) — allowed_
    # hosts() must degrade gracefully (falling through to st.secrets, which
    # in this test env has no [neon] section either) rather than raising.
    hosts = egress.allowed_hosts()
    assert hosts == {egress.GUDID_HOST}


def test_assert_allowed_host_rejects_empty():
    with pytest.raises(egress.EgressBlocked):
        egress.assert_allowed_host("")
    with pytest.raises(egress.EgressBlocked):
        egress.assert_allowed_host(None)
