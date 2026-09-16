"""
core/usage_stats.py
~~~~~~~~~~~~~~~~~~~
Persistence for the owner-only usage/security dashboard
(pages/usage_dashboard.py): GoodID lookup logging, the daily rollup those
logs feed into, and the read queries the dashboard renders.

Two different tables, two different lifetimes:

  * goodid_lookup_log — one row per api.goodid_client.query_goodid() call.
    Written live, from the app process, on the same request that made the
    call. See record_goodid_lookup().
  * daily_usage_stats  — one row per calendar day, written once by a nightly
    batch job (scripts/rollup_daily_stats.py, run by
    .github/workflows/rollup-daily-stats.yml), never by the app itself. It is
    the durable history `session`/`scan` can't be, because those are purged
    after core.store.RETENTION_DAYS — see migrations/004_usage_dashboard.sql
    for why this table exists at all. rollup_day() here is exposed for that
    script (and for backfilling by hand), not called from the Streamlit app.

Every write in this module is best-effort: a lost lookup-log row or a failed
rollup degrades the dashboard, never a scan. See record_goodid_lookup()'s
docstring for how that's enforced on the live-write path.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from core.store import _cursor, _iso

logger = logging.getLogger(__name__)

# How far back the dashboard's baseline looks by default. Long enough to
# smooth over weekday/weekend patterns, short enough that a genuine, lasting
# change in staffing shows up in the baseline within a couple of weeks rather
# than being permanently diluted by months of stale history.
DEFAULT_TREND_DAYS = 30


def record_goodid_lookup(
    success: bool, status_code: int | None, error_type: str | None
) -> None:
    """Log one AccessGUDID fallback call. Called from api.goodid_client at
    every return point of query_goodid().

    Swallows every failure beyond a warning — the same contract
    core.admin.log_audit_event makes for its own log. A scan must never fail,
    or even slow down waiting on a retry, because the usage dashboard's
    logging couldn't reach Neon. That's why the `except` below is broad: it
    has to cover "Neon is unreachable" (core.store._get_pool raising on first
    use) just as much as "the INSERT failed".

    api.goodid_client imports this module lazily, inside query_goodid()
    itself, matching that file's existing pattern for every other core.*
    import — see its module docstring for why a top-level import there is
    unsafe.
    """
    try:
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO goodid_lookup_log "
                "(queried_at, success, status_code, error_type) "
                "VALUES (%s, %s, %s, %s)",
                (datetime.now(UTC).replace(microsecond=0), success, status_code, error_type),
            )
    except Exception:  # noqa: BLE001 — logging must never break a lookup
        logger.warning("Failed to record GoodID lookup outcome.", exc_info=True)


def today_snapshot() -> dict:
    """Live counts for the current UTC day, read directly from `session`/
    `scan` (today's rows are always inside the 3-day retention window, so
    there's no need to wait for the nightly rollup to see today's numbers).

    Returns:
        {"unique_users": int, "session_count": int, "scan_count": int}
    """
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    with _cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT sanford_id) AS unique_users, count(*) AS session_count "
            "FROM session WHERE created_at >= %s AND created_at < %s",
            (day_start, day_end),
        )
        session_row = cur.fetchone()
        cur.execute(
            "SELECT count(*) AS scan_count FROM scan "
            "WHERE scanned_at >= %s AND scanned_at < %s",
            (day_start, day_end),
        )
        scan_row = cur.fetchone()
    return {
        "unique_users": session_row["unique_users"] or 0,
        "session_count": session_row["session_count"] or 0,
        "scan_count": scan_row["scan_count"] or 0,
    }


def today_goodid_stats() -> dict:
    """Live GoodID lookup volume/failure count for the current UTC day.

    Returns:
        {"lookups": int, "failures": int}
    """
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    with _cursor() as cur:
        cur.execute(
            "SELECT count(*) AS lookups, "
            "count(*) FILTER (WHERE NOT success) AS failures "
            "FROM goodid_lookup_log WHERE queried_at >= %s AND queried_at < %s",
            (day_start, day_end),
        )
        row = cur.fetchone()
    return {"lookups": row["lookups"] or 0, "failures": row["failures"] or 0}


def rollup_day(day: date) -> dict:
    """Compute and upsert `day`'s row in daily_usage_stats from the raw
    session/scan/goodid_lookup_log tables.

    Idempotent (INSERT ... ON CONFLICT DO UPDATE) — safe to re-run for the
    same day, which is what makes both the scheduled cron and a manual
    workflow_dispatch backfill safe to overlap.

    Not called by the Streamlit app — invoked by scripts/rollup_daily_stats.py,
    which the nightly workflow runs. Kept here rather than inline in that
    script so the query logic has one home and can be unit tested directly.

    Returns the row that was written, with `day` as an ISO string (matching
    core.store's ISO-string convention for timestamp-shaped columns).
    """
    day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    with _cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT sanford_id) AS unique_users, count(*) AS session_count "
            "FROM session WHERE created_at >= %s AND created_at < %s",
            (day_start, day_end),
        )
        session_row = cur.fetchone()
        cur.execute(
            "SELECT count(*) AS scan_count FROM scan "
            "WHERE scanned_at >= %s AND scanned_at < %s",
            (day_start, day_end),
        )
        scan_row = cur.fetchone()
        cur.execute(
            "SELECT count(*) AS lookups, count(*) FILTER (WHERE NOT success) AS failures "
            "FROM goodid_lookup_log WHERE queried_at >= %s AND queried_at < %s",
            (day_start, day_end),
        )
        goodid_row = cur.fetchone()

        computed_at = datetime.now(UTC).replace(microsecond=0)
        cur.execute(
            "INSERT INTO daily_usage_stats "
            "(day, unique_users, session_count, scan_count, goodid_lookups, "
            "goodid_failures, computed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (day) DO UPDATE SET "
            "unique_users = EXCLUDED.unique_users, "
            "session_count = EXCLUDED.session_count, "
            "scan_count = EXCLUDED.scan_count, "
            "goodid_lookups = EXCLUDED.goodid_lookups, "
            "goodid_failures = EXCLUDED.goodid_failures, "
            "computed_at = EXCLUDED.computed_at "
            "RETURNING *",
            (
                day,
                session_row["unique_users"] or 0,
                session_row["session_count"] or 0,
                scan_row["scan_count"] or 0,
                goodid_row["lookups"] or 0,
                goodid_row["failures"] or 0,
                computed_at,
            ),
        )
        row = cur.fetchone()
    row["day"] = row["day"].isoformat()
    row["computed_at"] = _iso(row["computed_at"])
    return row


HIGH_RATIO = 1.75  # today >= baseline * this → "high"
HIGH_ABS_MARGIN = 15  # ...or today >= baseline + this many, whichever fires first
LOW_RATIO = 0.4  # today <= baseline * this → "low" (only once baseline clears LOW_MIN_BASELINE)
LOW_MIN_BASELINE = 10
MIN_HISTORY_DAYS = 5


def classify_anomaly(today: int, history: list[int]) -> str:
    """Classify `today` against `history` (oldest-first daily counts, not
    including today) as "high", "low", or "normal".

    A ratio against the plain average of `history`, not a stdev-based
    z-score: with only a few weeks of daily data available (see
    DEFAULT_TREND_DAYS), a standard deviation is noisy enough to produce
    false confidence. The thresholds are the same "well outside the usual
    range" judgement call the user described wanting when they asked for
    this dashboard (30-50/day normally, 200 obviously not) — deliberately
    simple and explainable over statistically precise.

    "low" only fires once the baseline itself is large enough
    (LOW_MIN_BASELINE) for a drop to be meaningful — a baseline of 2 dropping
    to 0 is not a signal worth a flag.

    Returns "insufficient_history" if `history` has fewer than
    MIN_HISTORY_DAYS entries — the rollup needs a couple of weeks to run
    before a baseline means anything, and a flag on day two would be noise,
    not signal.
    """
    if len(history) < MIN_HISTORY_DAYS:
        return "insufficient_history"
    baseline = sum(history) / len(history)
    if today >= baseline * HIGH_RATIO or today >= baseline + HIGH_ABS_MARGIN:
        return "high"
    if baseline >= LOW_MIN_BASELINE and today <= baseline * LOW_RATIO:
        return "low"
    return "normal"


def trend(days: int = DEFAULT_TREND_DAYS) -> list[dict]:
    """The last `days` rows of daily_usage_stats, oldest first — the
    dashboard's trend chart and baseline are both built from this.

    Only ever as long as the rollup has been running; a fresh install
    returns []; not an error, just "no history yet".
    """
    with _cursor() as cur:
        cur.execute(
            "SELECT * FROM daily_usage_stats "
            "WHERE day >= (current_date - %s::int) "
            "ORDER BY day ASC",
            (days,),
        )
        rows = cur.fetchall()
    for row in rows:
        row["day"] = row["day"].isoformat()
        row["computed_at"] = _iso(row["computed_at"])
    return rows
