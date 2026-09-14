"""
core/egress.py
~~~~~~~~~~~~~~~
Application-level egress allowlist.

This is a code-level choke point, not a network firewall — a compromised
dependency could still open a raw socket to anywhere the OS/container
permits, and this module cannot stop that. What it does buy:

  * A single, auditable source of truth for every host this app is meant
    to talk to (GUDID, Fabric, Neon), instead of that knowledge being
    implicit in three different modules.
  * A hard failure — not a silent connection — if a future code change
    tries to reach an outbound host that isn't one of the three, or if a
    misconfigured endpoint resolves to something unexpected.

The actual network-level restriction ("this device/container can reach
only these hosts, full stop") has to be enforced by IT at the firewall/
proxy/NSG layer — see ASVS-COMPLIANCE.md's "Needs infra action" list. This
module is the corresponding application-side control ASVS V1 (secure
architecture) expects to sit alongside it.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class EgressBlocked(RuntimeError):
    """Raised when code attempts to reach a host outside the allowlist."""


# The FDA AccessGUDID host. Hardcoded and deliberately NOT read from .env or
# any other config — unlike Fabric/Neon there is no legitimate deployment
# where this should point anywhere else, so making it configurable would
# only add a way to route around the allowlist.
GUDID_HOST = "accessgudid.nlm.nih.gov"


def _fabric_host() -> str | None:
    host = os.environ.get("FABRIC_SQL_ENDPOINT", "").strip().lower()
    return host or None


def _neon_host() -> str | None:
    # Local import: core.store imports this module to validate its own
    # connection string, so importing store at module load time here would
    # be a cycle. By the time this actually runs, core.store is fully loaded.
    from core.store import _conninfo  # noqa: PLC0415

    try:
        return (urlparse(_conninfo()).hostname or "").lower() or None
    except RuntimeError:
        # No connection string configured yet (e.g. mock-only dev, or a
        # unit test that never touches the store) — nothing to allow.
        return None


def allowed_hosts() -> frozenset[str]:
    """Hosts this app may contact right now, given current configuration.

    Recomputed on every call rather than cached: FABRIC_SQL_ENDPOINT and the
    Neon secret can differ per environment (and per test), so caching would
    risk allowlisting a stale host after a config change mid-process.
    """
    hosts = {GUDID_HOST}
    fabric = _fabric_host()
    if fabric:
        hosts.add(fabric)
    neon = _neon_host()
    if neon:
        hosts.add(neon)
    return frozenset(hosts)


def assert_allowed_host(host: str | None) -> None:
    """Raise EgressBlocked unless `host` is on the current allowlist."""
    normalized = (host or "").strip().lower()
    if not normalized or normalized not in allowed_hosts():
        logger.error("Egress blocked: %r is not an allowed destination.", host)
        raise EgressBlocked(f"{host!r} is not an allowed egress destination.")


def assert_allowed_url(url: str) -> None:
    """Raise EgressBlocked unless `url`'s host is on the current allowlist.

    Call this immediately before any outbound HTTP request is sent.
    """
    assert_allowed_host(urlparse(url).hostname)
