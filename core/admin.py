"""
core/admin.py
~~~~~~~~~~~~~
Admin-only data refresh: a typed-email allowlist check, refresh
orchestration, and the cross-session cooldown/last-refresh state and audit
trail backing the admin page.

Access control here is a typed-email allowlist, NOT verified identity: a
visitor types their email and it's checked against a list, the way a sign-in
sheet works rather than a badge reader. It only gates access as long as the
allowlist stays specific and private — anyone who learns an allowlisted
address could type it in and get through. That's why every attempt, granted
or denied, is written to the audit log: it can't prevent misuse up front,
but it makes it visible after the fact. A verified login (e.g. Microsoft
Entra via st.login) would close that gap if it's ever needed — see
README.md → "Admin refresh page".

See core/session.py for the (unrelated) per-browser-session scan history
model; this module's state is cross-session by design, stored on disk,
because the cooldown and audit trail must hold across every admin/session,
not just the one that clicked.
"""

from __future__ import annotations

import json
import logging
import time

import streamlit as st

from data.loader import CACHE_PATH, invalidate_data_cache

from .lookup import get_lookup_engine

logger = logging.getLogger(__name__)

# How long "Refresh data now" stays disabled after a successful refresh. Keeps
# a well-meaning admin (or several, in different tabs) from re-triggering a
# full dataset fetch — and on Fabric, a fresh ODBC round-trip — back to back.
ADMIN_COOLDOWN_SECONDS = 300

# Sidecar JSON recording who last refreshed and when. Lives next to the
# Parquet cache (data/cache/), which is already git-ignored, and is the
# source of truth for both the banner and the cooldown — st.session_state
# would only be visible to the admin who clicked, not to a second admin in a
# different session, so the cooldown would be trivially bypassable without it.
_META_PATH = CACHE_PATH.parent / "refresh_meta.json"

# Append-only audit trail (JSON Lines — one compact record per line) of every
# access attempt and refresh. Same directory as the meta sidecar, same
# git-ignore coverage.
_AUDIT_LOG_PATH = CACHE_PATH.parent / "admin_audit.log"


def _allowed_emails() -> frozenset[str]:
    """Admin allowlist, lower-cased, from .streamlit/secrets.toml [admin]."""
    try:
        emails = st.secrets["admin"]["allowed_emails"]
    except (KeyError, FileNotFoundError):
        return frozenset()
    return frozenset(e.strip().lower() for e in emails if e.strip())


def _allowed_domains() -> frozenset[str]:
    """Optional email-domain allowlist (e.g. 'sanfordhealth.org') so a whole
    group can be granted access without listing every address individually."""
    try:
        domains = st.secrets["admin"]["allowed_domains"]
    except (KeyError, FileNotFoundError):
        return frozenset()
    return frozenset(d.strip().lower().lstrip("@") for d in domains if d.strip())


def is_admin(email: str) -> bool:
    """True if the typed `email` is on the admin allowlist.

    This checks the string a visitor typed, not a verified identity — see
    the module docstring. Every call site should pair the result with
    log_audit_event() so both grants and denials stay traceable.
    """
    email = (email or "").strip().lower()
    if not email:
        return False
    if email in _allowed_emails():
        return True
    domain = email.rsplit("@", 1)[-1]
    return domain in _allowed_domains()


def log_audit_event(event: str, email: str, **extra: object) -> None:
    """Append one record to the admin audit log.

    `event` is a short label — "access_granted", "access_denied", "refresh".
    Logging failures are swallowed (beyond a warning): the audit trail must
    never be able to break the page it's watching.
    """
    record = {
        "ts": time.time(),
        "event": event,
        "email": (email or "").strip().lower() or "(blank)",
        **extra,
    }
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        logger.warning("Failed to write admin audit log entry: %r", record)


def read_audit_log(limit: int = 50) -> list[dict]:
    """Most-recent-first audit entries, up to `limit`. [] if none logged yet."""
    if not _AUDIT_LOG_PATH.exists():
        return []
    try:
        lines = _AUDIT_LOG_PATH.read_text().splitlines()
    except OSError:
        return []
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    records.reverse()
    return records


def read_refresh_meta() -> dict | None:
    """Return {'ts': float, 'by': str} from the last refresh, or None if the
    data has never been manually refreshed."""
    if not _META_PATH.exists():
        return None
    try:
        return json.loads(_META_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("refresh_meta.json is unreadable; treating as absent.")
        return None


def _write_refresh_meta(email: str) -> None:
    _META_PATH.parent.mkdir(parents=True, exist_ok=True)
    _META_PATH.write_text(json.dumps({"ts": time.time(), "by": email}))


def cooldown_remaining() -> int:
    """Seconds until the next refresh is allowed; 0 if none is in effect."""
    meta = read_refresh_meta()
    if meta is None:
        return 0
    elapsed = time.time() - meta["ts"]
    return max(0, int(ADMIN_COOLDOWN_SECONDS - elapsed))


def refresh_now(email: str) -> int:
    """Invalidate every cache layer and rebuild the lookup index immediately.

    Clears, in order: the on-disk Parquet + both @st.cache_data layers (via
    data.invalidate_data_cache) and finally get_lookup_engine's
    @st.cache_resource — the fourth cache layer, which has no TTL and would
    otherwise keep serving the old index for the rest of the app's lifetime.
    Records who refreshed and when for the banner/cooldown, logs a "refresh"
    audit event, then rebuilds so the caller can report a fresh row count
    immediately.

    Returns:
        The row count of the freshly loaded dataset.
    """
    invalidate_data_cache()
    get_lookup_engine.clear()
    _write_refresh_meta(email)

    engine = get_lookup_engine()
    log_audit_event("refresh", email, rows=engine.size)
    logger.info("Manual data refresh by %s: %d contract lines loaded.", email, engine.size)
    return engine.size
