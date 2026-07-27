"""
core/autosave.py
~~~~~~~~~~~~~~~~~
Disk-backed persistence for an in-progress scan session.

Each browser session that has clicked "Start New Session" gets its own JSON
file, named by session id, under data/cache/sessions/ (a subdirectory of the
already git-ignored data/cache/ used by data.loader's Parquet cache — see
core/admin.py for the same sidecar-file convention applied to admin state).

This exists so a dropped connection, idle timeout, or server restart doesn't
erase a warehouse worker's scan history: app.py carries the session id in the
URL query params, and rehydrates from here if st.session_state comes back
empty. See core/session.py for the session-state model this backs.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path

from data.loader import CACHE_PATH

logger = logging.getLogger(__name__)

SESSIONS_DIR = CACHE_PATH.parent / "sessions"


def new_session_id() -> str:
    """A short, URL-friendly id — enough entropy that collisions never matter."""
    return uuid.uuid4().hex[:12]


def _path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def save_session(session_id: str, location: str | None, history: list[dict]) -> None:
    """Persist the current history to disk, overwriting any prior save.

    Written via a temp file + os.replace so a mid-write crash never leaves a
    half-written (unreadable) session file behind.
    """
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"location": location, "history": history, "updated_ts": time.time()}
    target = _path(session_id)
    tmp = target.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, target)
    except OSError:
        logger.warning("Failed to autosave session %s", session_id)


def load_session(session_id: str) -> dict | None:
    """Return {'location', 'history'} for `session_id`, or None if unrecoverable."""
    path = _path(session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Session file for %s is unreadable; treating as absent.", session_id)
        return None
    return {"location": data.get("location"), "history": data.get("history", [])}


def delete_session(session_id: str) -> None:
    """Remove a session's autosave file. Safe to call even if it never saved."""
    _path(session_id).unlink(missing_ok=True)
