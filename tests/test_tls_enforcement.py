"""Regression guards for ASVS-AUDIT.md item 4: TLS certificate validation
must stay enforced, with no disabled-verification flag, on every network
call this app makes (GUDID, Fabric, Neon).

These are deliberately redundant with each other (source-scan + behavioral)
so a future refactor that moves code around still gets caught by at least
one of them."""

from __future__ import annotations

import inspect
import re

import pytest

import api.goodid_client as goodid_client
import core.store as store
import data.loader as loader

# Any of these appearing in the three network-call modules means TLS/cert
# validation has been disabled somewhere — see ASVS-AUDIT.md "no disabled
# TLS verification patterns" grep from the audit.
_DANGEROUS_PATTERNS = re.compile(
    r"verify\s*=\s*False|CERT_NONE|_create_unverified|disable_warnings|"
    r"InsecureRequestWarning|check_hostname\s*=\s*False|TrustServerCertificate=Yes",
    re.IGNORECASE,
)


@pytest.mark.parametrize("module", [goodid_client, store, loader])
def test_no_disabled_tls_verification_in_source(module):
    source = inspect.getsource(module)
    match = _DANGEROUS_PATTERNS.search(source)
    assert match is None, f"Found disabled-TLS pattern {match.group() if match else ''!r} in {module.__name__}"


def test_httpx_client_created_with_no_verify_override():
    """query_goodid must never pass verify= to httpx.Client — its absence is
    what keeps httpx's default (certificate validation on) in effect."""
    source = inspect.getsource(goodid_client.query_goodid)
    assert "verify" not in source


def test_fabric_connection_string_enforces_encryption(monkeypatch):
    monkeypatch.setenv("FABRIC_SQL_ENDPOINT", "myworkspace.datawarehouse.fabric.microsoft.com")
    monkeypatch.setenv("FABRIC_DATABASE", "mylakehouse")
    conn_str = loader._fabric_connection_string()
    assert "Encrypt=Yes" in conn_str
    assert "TrustServerCertificate=No" in conn_str


def test_neon_conninfo_requires_tls(monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://user:pass@host/db?sslmode=require")
    assert "sslmode=require" in store._conninfo()


def test_neon_conninfo_rejects_disabled_tls(monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://user:pass@host/db?sslmode=disable")
    with pytest.raises(RuntimeError, match="sslmode"):
        store._conninfo()
