"""core package — scan orchestration, session model, export."""

from .lookup import extract_gtin, get_lookup_engine, resolve_scan
from .session import compute_stats, init_session, record_scan

__all__ = [
    "compute_stats",
    "extract_gtin",
    "get_lookup_engine",
    "init_session",
    "record_scan",
    "resolve_scan",
]
