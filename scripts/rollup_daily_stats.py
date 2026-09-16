"""
scripts/rollup_daily_stats.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Compute yesterday's row in daily_usage_stats and upsert it, so the usage
dashboard (pages/usage_dashboard.py) has a durable baseline that outlives
the retention purge on `session`/`scan` — see migrations/004_usage_dashboard.sql
for why that table exists.

Run daily by .github/workflows/rollup-daily-stats.yml, scheduled before the
purge workflow so there's always a comfortable multi-day buffer:

    python scripts/rollup_daily_stats.py

Also safe to run by hand for a backfill (rollup_day is an upsert, so re-running
for an already-computed day just recomputes it):

    python scripts/rollup_daily_stats.py 2026-09-10

Needs the same NEON_DATABASE_URL / DATABASE_URL environment variable
core/store.py reads — see that module's _conninfo().
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta

from core.usage_stats import rollup_day


def _target_day(argv: list[str]) -> date:
    if len(argv) > 1:
        return date.fromisoformat(argv[1])
    # Default: yesterday (UTC) — the most recent day guaranteed to be
    # complete, so an early-morning run never rolls up a partial today.
    return (datetime.now(UTC) - timedelta(days=1)).date()


def main() -> None:
    day = _target_day(sys.argv)
    row = rollup_day(day)
    print(
        f"{row['day']}: {row['unique_users']} unique users, "
        f"{row['session_count']} sessions, {row['scan_count']} scans, "
        f"{row['goodid_failures']}/{row['goodid_lookups']} GoodID lookups failed."
    )


if __name__ == "__main__":
    main()
