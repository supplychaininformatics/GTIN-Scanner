"""Tests for core.egress — the application-level outbound-host allowlist."""

from __future__ import annotations

import pytest

from core import egress


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with no Fabric/Neon config, so allowed_hosts() is
    deterministic (just GUDID) unless a test opts in."""
    monkeypatch.delenv("FABRIC_SQL_ENDPOINT", raising=False)
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


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
    # No NEON_DATABASE_URL set — allowed_hosts() must degrade gracefully
    # (falling through to st.secrets if configured, or just GUDID/Fabric if
    # not) rather than raising. Local dev machines commonly have a real
    # .streamlit/secrets.toml, so this only asserts GUDID is always present,
    # not that Neon is absent.
    hosts = egress.allowed_hosts()
    assert egress.GUDID_HOST in hosts


def test_assert_allowed_host_rejects_empty():
    with pytest.raises(egress.EgressBlocked):
        egress.assert_allowed_host("")
    with pytest.raises(egress.EgressBlocked):
        egress.assert_allowed_host(None)
