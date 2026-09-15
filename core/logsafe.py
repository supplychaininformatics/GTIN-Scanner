"""
core/logsafe.py
~~~~~~~~~~~~~~~~
Sanitizes attacker-controlled strings — a scanned barcode above all, since
it's the one input in this app reachable by anyone who can print a barcode
and get it scanned, with no keyboard access needed — before they reach a
log line.

Two things this guards against:
  * Log injection: a crafted scan containing newlines/control characters
    could otherwise forge what looks like additional log entries. Python's
    default log formatting doesn't execute anything from this, so the
    impact is a confusing log rather than code execution, but there's no
    reason to accept it when stripping is free.
  * A runaway-length payload flooding the log with a single line.

Deliberately has zero dependencies on the rest of this codebase, so it can
be imported anywhere (including api/goodid_client.py) without adding to the
import-order fragility documented in that module.
"""

from __future__ import annotations

_MAX_LOG_VALUE_LENGTH = 128


def safe_log_value(value: object, max_length: int = _MAX_LOG_VALUE_LENGTH) -> str:
    """A version of `value` safe to interpolate into a log message."""
    text = "" if value is None else str(value)
    cleaned = "".join(ch for ch in text if ch.isprintable())
    if len(cleaned) > max_length:
        return cleaned[:max_length] + "…(truncated)"
    return cleaned
