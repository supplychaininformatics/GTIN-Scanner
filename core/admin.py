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
from cryptography.fernet import Fernet, InvalidToken

from data.loader import CACHE_PATH, invalidate_data_cache

from . import secrets
from .lookup import get_lookup_engine

logger = logging.getLogger(__name__)

# Shared across every gated page (admin, board) so a supervisor who has
# already typed their email on one doesn't have to do it again on the other.
_SESSION_KEY = "admin_email"

# How long "Refresh data now" stays disabled after a successful refresh. Keeps
# a well-meaning admin (or several, in different tabs) from re-triggering a
# full dataset fetch — and on Fabric, a fresh ODBC round-trip — back to back.
ADMIN_COOLDOWN_SECONDS = 300

# Sidecar recording who last refreshed and when. Lives next to the Parquet
# cache (data/cache/), which is already git-ignored, and is the source of
# truth for both the banner and the cooldown — st.session_state would only
# be visible to the admin who clicked, not to a second admin in a different
# session, so the cooldown would be trivially bypassable without it.
#
# Encrypted at rest (Fernet, same keychain-backed pattern as
# core/offline_queue.py and data/loader.py's contract cache) — this file
# records admin email addresses and refresh timestamps, which shouldn't sit
# in plaintext on the server's disk any more than the other cached state
# does. See ASVS-AUDIT.md finding #13.
_META_PATH = CACHE_PATH.parent / "refresh_meta.enc"

# Audit trail of every access attempt and refresh, stored as one encrypted
# JSON array rather than append-only JSON Lines — whole-file encryption
# means "append" is decrypt/add/re-encrypt, which is the right tradeoff for
# a low-volume admin log, not a high-throughput one. Capped at
# _AUDIT_LOG_MAX_RECORDS so it can't grow unbounded either.
_AUDIT_LOG_PATH = CACHE_PATH.parent / "admin_audit.enc"
_AUDIT_LOG_MAX_RECORDS = 2000

_KEYRING_KEY_NAME = "admin_log_key"
_FALLBACK_KEY_PATH = CACHE_PATH.parent / ".admin_log_key"


def _log_key() -> bytes:
    """Fernet key for the audit log / refresh-meta files — OS keychain
    first, a local 0600 key file only if no keyring backend exists at all.
    Same pattern as core.offline_queue._get_or_create_key and
    data.loader._cache_key."""
    existing = secrets.from_keyring(_KEYRING_KEY_NAME)
    if existing:
        return existing.encode()

    key = Fernet.generate_key()
    try:
        secrets.store_in_keyring(_KEYRING_KEY_NAME, key.decode())
        return key
    except Exception:  # noqa: BLE001 — no keyring backend; use the file fallback
        logger.warning(
            "No OS keychain backend available; falling back to a local key "
            "file for the admin audit log."
        )
    if _FALLBACK_KEY_PATH.exists():
        return _FALLBACK_KEY_PATH.read_bytes()
    _FALLBACK_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FALLBACK_KEY_PATH.write_bytes(key)
    _FALLBACK_KEY_PATH.chmod(0o600)
    return key


def _write_encrypted(path, data) -> None:
    token = Fernet(_log_key()).encrypt(json.dumps(data).encode())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_bytes(token)
    tmp_path.replace(path)


def _read_encrypted(path, default):
    """Decrypt and parse `path`, or return `default` on any failure (missing
    file, wrong/rotated key, corrupted write) — a lost audit-log entry is a
    cost, never a reason to break the page it's watching."""
    if not path.exists():
        return default
    try:
        raw = Fernet(_log_key()).decrypt(path.read_bytes())
        return json.loads(raw)
    except (InvalidToken, OSError, ValueError, json.JSONDecodeError):
        logger.warning("%s is unreadable; treating it as absent.", path.name, exc_info=True)
        return default


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
    """Append one record to the (encrypted) admin audit log.

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
        records = _read_encrypted(_AUDIT_LOG_PATH, default=[])
        if not isinstance(records, list):
            records = []
        records.append(record)
        if len(records) > _AUDIT_LOG_MAX_RECORDS:
            records = records[-_AUDIT_LOG_MAX_RECORDS:]
        _write_encrypted(_AUDIT_LOG_PATH, records)
    except OSError:
        logger.warning("Failed to write admin audit log entry: %r", record)


def read_audit_log(limit: int = 50) -> list[dict]:
    """Most-recent-first audit entries, up to `limit`. [] if none logged yet."""
    records = _read_encrypted(_AUDIT_LOG_PATH, default=[])
    if not isinstance(records, list):
        return []
    return list(reversed(records[-limit:]))


def read_refresh_meta() -> dict | None:
    """Return {'ts': float, 'by': str} from the last refresh, or None if the
    data has never been manually refreshed."""
    return _read_encrypted(_META_PATH, default=None)


def _write_refresh_meta(email: str) -> None:
    _write_encrypted(_META_PATH, {"ts": time.time(), "by": email})


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


def render_access_gate(page_label: str) -> str | None:
    """Render the typed-email allowlist gate; return the verified email once
    granted, else render the sign-in form and return None.

    Callers must treat a None return as "stop rendering the rest of the
    page" (e.g. `st.stop()`) — this function only draws the form, it does
    not halt execution itself, since Streamlit pages need to keep control
    of their own layout (nav links above the gate, etc.).

    Session state key is shared (`admin_email`) across every page that calls
    this, so verifying on the admin page also unlocks the monitor board and
    vice versa — one sign-in per browser session, not per page. See
    core/admin.py's module docstring for why this is a typed-email allowlist
    rather than a verified login, and its limits.
    """
    if _SESSION_KEY not in st.session_state:
        st.session_state[_SESSION_KEY] = None

    if st.session_state[_SESSION_KEY]:
        return st.session_state[_SESSION_KEY]

    st.markdown(f"### {page_label} Access")
    st.write(
        "This page is restricted to managers and supervisors. Enter your "
        "email to continue — every attempt is logged."
    )
    with st.form(f"{page_label.lower().replace(' ', '_')}_access_form"):
        typed_email = st.text_input(
            "Email", placeholder="you@example.org", label_visibility="collapsed"
        )
        submitted = st.form_submit_button("Continue", type="primary")

    if submitted:
        candidate = typed_email.strip()
        if candidate and is_admin(candidate):
            log_audit_event("access_granted", candidate, page=page_label)
            st.session_state[_SESSION_KEY] = candidate.lower()
            st.rerun()
        else:
            log_audit_event("access_denied", candidate, page=page_label)
            st.error(
                "That email isn't on the admin allowlist. Ask Supply Chain "
                "Informatics to add you to allowed emails (or your group's "
                "domain to allowed emails)."
            )
    return None
