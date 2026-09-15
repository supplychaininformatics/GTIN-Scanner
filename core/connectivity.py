"""
core/connectivity.py
~~~~~~~~~~~~~~~~~~~~~
Classifies whether an exception from a core.store call means "Neon is
unreachable right now" (worth queuing and retrying later — see
core/offline_queue.py) versus some other database error (a bug, a
constraint violation, bad data) that retrying the identical write would
never fix and should instead surface normally.
"""

from __future__ import annotations

import psycopg
from psycopg_pool import PoolTimeout


def is_connectivity_error(exc: BaseException) -> bool:
    """True if `exc` represents a failure to reach/use the connection itself
    (DNS failure, refused connection, timeout, pool exhausted) rather than a
    failure in what was asked of a working connection."""
    return isinstance(exc, (psycopg.OperationalError, PoolTimeout))
