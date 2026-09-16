"""
pages/usage_dashboard.py
~~~~~~~~~~~~~~~~~~~~~~~~
Owner-only usage/security dashboard: today's usage against a daily baseline,
so an abnormal spike (or drop) in traffic is visible at a glance instead of
requiring a manual database query.

Access is two checks stacked, not one:

  1. The same typed-email allowlist every gated page uses (core.admin.
     render_access_gate / is_admin) — a supervisor's email works here too.
  2. A second, narrower check against [dashboard] owner_email in
     .streamlit/secrets.toml. This page surfaces security-relevant signals
     (traffic anomalies, GoodID failure bursts) that other admins/supervisors
     have no operational need to see — unlike the refresh button or Force
     End, nobody but the app's owner acts on what's shown here. See
     core/admin.py's module docstring for the allowlist's own limits
     (typed-email, not verified identity).

Data sources:
  * Today's counts are read live from `session`/`scan` (core.usage_stats.
    today_snapshot / today_goodid_stats) — always available, never purged
    same-day.
  * The trend/baseline comes from daily_usage_stats (core.usage_stats.trend),
    populated by the nightly rollup — see that module's docstring for why
    this table has to exist separately from `session`/`scan`.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.admin import log_audit_event, read_audit_log, render_access_gate
from core.usage_stats import (
    DEFAULT_TREND_DAYS,
    classify_anomaly,
    today_goodid_stats,
    today_snapshot,
    trend,
)
from ui import components as C
from ui.theme import inject_theme

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title=f"Usage Dashboard · {C.APP_TITLE}",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_theme()

st.markdown(C.identity_header_html(page_name="Usage Dashboard"), unsafe_allow_html=True)
with st.container(key="sf_navlink"):
    st.page_link("pages/board.py", label="← Monitor Board", icon=None)

email = render_access_gate("Usage Dashboard")
if email is None:
    st.stop()


def _owner_email() -> str | None:
    try:
        return str(st.secrets["dashboard"]["owner_email"]).strip().lower()
    except (KeyError, FileNotFoundError):
        return None


owner_email = _owner_email()
if owner_email is None:
    st.error(
        "This page has no owner configured yet. Add "
        "`[dashboard]\\nowner_email = \"you@example.org\"` to "
        ".streamlit/secrets.toml — see .streamlit/secrets.toml.example."
    )
    st.stop()

if email.strip().lower() != owner_email:
    # Passed the general admin allowlist but isn't the configured owner —
    # log it once per grant rather than on every rerun (this page reruns on
    # every widget interaction while it's open).
    if not st.session_state.get("usage_dashboard_denied_logged"):
        log_audit_event("dashboard_access_denied", email, page="Usage Dashboard")
        st.session_state["usage_dashboard_denied_logged"] = True
    st.error("This dashboard is restricted to its configured owner.")
    st.stop()

# ── Today vs. baseline ──────────────────────────────────────────────────────
st.markdown(C.section_html("Today"), unsafe_allow_html=True)

snapshot = today_snapshot()
goodid_today = today_goodid_stats()
history = trend(DEFAULT_TREND_DAYS)

users_history = [row["unique_users"] for row in history]
sessions_history = [row["session_count"] for row in history]
failure_rate_history = [
    row["goodid_failures"] / row["goodid_lookups"] for row in history if row["goodid_lookups"]
]

users_flag = classify_anomaly(snapshot["unique_users"], users_history)
today_failure_rate = (
    goodid_today["failures"] / goodid_today["lookups"] if goodid_today["lookups"] else 0.0
)

_FLAG_LABEL = {
    "high": "🔴 Well above normal",
    "low": "🔵 Well below normal",
    "normal": "🟢 Normal range",
    "insufficient_history": "⚪ Not enough history yet",
}

col1, col2, col3, col4 = st.columns(4)
col1.metric("Unique users", snapshot["unique_users"])
col2.metric("Sessions", snapshot["session_count"])
col3.metric("Scans", snapshot["scan_count"])
col4.metric(
    "GoodID failure rate",
    f"{today_failure_rate:.0%}",
    help=f"{goodid_today['failures']} of {goodid_today['lookups']} fallback lookups today.",
)

if users_flag == "insufficient_history":
    st.info(
        f"{_FLAG_LABEL[users_flag]} — the nightly rollup needs a few more days "
        "of history before today's count can be judged against a baseline."
    )
else:
    baseline_avg = sum(users_history) / len(users_history)
    detail = (
        f"{_FLAG_LABEL[users_flag]} — today's **{snapshot['unique_users']}** unique "
        f"users vs. a **{baseline_avg:.0f}**/day average over the last "
        f"{len(users_history)} days (range {min(users_history)}–{max(users_history)})."
    )
    if users_flag == "high":
        st.error(detail)
    elif users_flag == "low":
        st.warning(detail)
    else:
        st.success(detail)

# ── Trend ────────────────────────────────────────────────────────────────────
st.markdown(
    C.section_html("Trend", count=f"last {DEFAULT_TREND_DAYS} days"),
    unsafe_allow_html=True,
)

if not history:
    st.caption(
        "No rollup history yet — .github/workflows/rollup-daily-stats.yml "
        "writes the first row after its next scheduled run (or run it now "
        "from the Actions tab)."
    )
else:
    trend_df = pd.DataFrame(history).set_index("day")
    st.line_chart(trend_df[["unique_users", "session_count"]])

    failure_df = pd.DataFrame(
        {
            "day": [row["day"] for row in history if row["goodid_lookups"]],
            "failure_rate": failure_rate_history,
        }
    )
    if not failure_df.empty:
        st.caption("GoodID fallback failure rate")
        st.line_chart(failure_df.set_index("day"))

# ── Recent admin activity ───────────────────────────────────────────────────
with st.expander("Recent admin activity"):
    entries = read_audit_log(limit=30)
    if not entries:
        st.caption("No activity logged yet.")
    else:
        rows = [
            {
                "Time": datetime.fromtimestamp(e["ts"]).strftime("%b %d, %H:%M"),
                "Event": e["event"],
                "Email": e["email"],
            }
            for e in entries
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

st.divider()
if st.button("Switch email"):
    st.session_state.admin_email = None
    st.rerun()
