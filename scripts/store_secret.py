#!/usr/bin/env python3
"""
scripts/store_secret.py
~~~~~~~~~~~~~~~~~~~~~~~
One-time operator action: move a secret out of a plaintext config file
(.env, .streamlit/secrets.toml) and into the OS keychain, where
core/secrets.py will find it automatically on every future run.

Usage:
    python scripts/store_secret.py neon_database_url
    python scripts/store_secret.py fabric_client_secret

The value is read from a hidden prompt (getpass), never from argv or an env
var, so it never lands in shell history or a process list. Storing it does
not remove it from wherever it currently lives (.env/secrets.toml) — the app
prefers the keychain automatically once it's there, but delete the plaintext
copy yourself once you've confirmed the app still starts.
"""

from __future__ import annotations

import getpass
import sys

_KNOWN_KEYS = ("neon_database_url", "fabric_client_secret")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in _KNOWN_KEYS:
        print(f"Usage: {sys.argv[0]} <{'|'.join(_KNOWN_KEYS)}>", file=sys.stderr)
        return 1

    key = sys.argv[1]
    try:
        import keyring  # noqa: F401
    except ImportError:
        print(
            "The 'keyring' package isn't installed. Run: pip install keyring",
            file=sys.stderr,
        )
        return 1

    from core.secrets import SERVICE_NAME, store_in_keyring

    value = getpass.getpass(f"Value for {key!r}: ").strip()
    if not value:
        print("Empty value — nothing stored.", file=sys.stderr)
        return 1

    store_in_keyring(key, value)
    print(f"Stored under service {SERVICE_NAME!r}, key {key!r}.")
    print(
        "The app will now prefer this over .env/.streamlit/secrets.toml. "
        "Once you've confirmed it starts correctly, remove the plaintext "
        "copy from wherever it currently lives."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
