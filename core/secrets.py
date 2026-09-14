"""
core/secrets.py
~~~~~~~~~~~~~~~
Layered secret lookup, preferring the strongest storage actually available.

Order used by callers (env var > keyring > Streamlit secrets) is deliberate:

  1. Environment variable — how a deploy/CI pipeline injects a secret; the
     process's own env is already as private as the host lets it be, and
     nothing this app does can improve on that.
  2. OS keychain, via the `keyring` package — the best option for a human
     running this app interactively on their own machine. Same mechanism
     data/loader.py already trusts for the Fabric AAD token cache
     (azure-identity's TokenCachePersistenceOptions); this extends the same
     idea to the one plaintext secret that wasn't going through it yet (the
     Neon connection string / Fabric service-principal secret).
  3. Streamlit secrets (.streamlit/secrets.toml locally, or Streamlit
     Cloud's managed secrets store in production) — kept as the fallback
     because it's how this app is actually deployed today, and Streamlit
     Cloud's secrets store is itself a legitimate managed secret store for
     that target. Nothing here removes support for it.

This module only ever reads at runtime. Writing a secret into the keychain
is a one-time operator action — see scripts/store_secret.py.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Keychain entries for this app all live under one service name, keyed by a
# short label per secret (see scripts/store_secret.py for the labels used).
SERVICE_NAME = "gtin-scanner"


def from_keyring(key: str) -> str | None:
    """The keychain-stored value for `key`, or None if unavailable.

    Every failure mode here — `keyring` not installed, no OS backend
    available (e.g. a headless Linux container with no Secret Service
    running), the keychain locked — is treated as "not found" rather than
    raised, so callers fall through to the next source. That matches every
    other optional-config lookup in this app (e.g.
    data.loader._resolve_mock_dataset's candidate-path fallback): a missing
    optional source is not an error.
    """
    try:
        import keyring  # noqa: PLC0415
    except ImportError:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, key)
    except Exception:  # noqa: BLE001 — a locked/unavailable keychain isn't fatal
        logger.debug("Keyring lookup for %r failed; falling through.", key, exc_info=True)
        return None


def store_in_keyring(key: str, value: str) -> None:
    """Write `value` into the OS keychain under SERVICE_NAME/key.

    Not called by the app itself at runtime — this is what
    scripts/store_secret.py uses for the one-time "move this secret out of
    the plaintext config file" operator action. Raises ImportError if
    `keyring` isn't installed and lets any backend error propagate, since a
    failed write here should be loud, unlike a failed read.
    """
    import keyring  # noqa: PLC0415

    keyring.set_password(SERVICE_NAME, key, value)
