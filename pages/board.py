"""
pages/board.py
~~~~~~~~~~~~~~
Monitor master board — the passive, wide-layout surface described in
PLAN.md. It never scans and never owns normal session lifecycle; its only
lifecycle action is the force-end escape hatch for a dead/dropped handheld
(mirrored in pages/admin.py — see core/store.force_end_session).

Shows: the static app URL for device onboarding (provisioning/fallback, not
per-session — see PLAN.md "Device onboarding"), today's sessions by default
with a filter for the full 3-day retention window, a drill-in to any
session's full scan list, and a per-session Excel export.
"""

from __future__ import annotations

import logging
import os

import streamlit as st
from dotenv import load_dotenv

from core import store
from core.admin import log_audit_event
from core.export import EXPORT_MIME, build_workbook, export_filename
from core.session import history_for_session
from ui import components as C
from ui.theme import inject_theme

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title=f"Monitor · {C.APP_TITLE}",
    page_icon="🖥️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_theme()
store.purge_old_sessions()

st.markdown(C.identity_header_html(page_name="Monitor Board"), unsafe_allow_html=True)
with st.container(key="sf_navlink"):
    st.page_link("pages/admin.py", label="Admin →", icon=None)

# ── Device onboarding: static link, not per-session ─────────────────────────
# See PLAN.md "Device onboarding": open this URL directly on the handheld's
# browser → Add to Home Screen. The link never
# carries a session id, so provisioning a new handheld is a one-time action,
# not a per-shift one.
deploy_url = os.getenv("DEPLOY_URL", "").strip()
with st.expander("Add a new handheld", expanded=False):
    if deploy_url:
        st.write(
            "On the handheld open this link directly, then **Add to Home "
            "Screen**. This only needs to be done once per device."
        )
        st.code(deploy_url, language=None)
        st.caption(
            "The first load on a newly added handheld can take 3–5 minutes "
            "to start. This is normal; scanning once it's up will be fast "
            "from then on."
        )
    else:
        st.info(
            "No deploy URL is configured yet. Set `DEPLOY_URL` in `.env` once "
            "this app has a real address, and it will show here for handheld "
            "onboarding."
        )
        st.caption(
            "Heads up: if the app has been idle, it goes to sleep — the "
            "first load on a newly added handheld can take 3–5 minutes to "
            "wake back up. This is normal."
        )

st.markdown(C.section_html("Sessions"), unsafe_allow_html=True)

# ── Filter: today (default) vs the full 3-day retention window ──────────────
filter_col, _ = st.columns([1, 3])
with filter_col:
    show_all = st.toggle(
        "Show full 3-day window",
        value=False,
        help="Default view is today's sessions only. Turn this on to reach a "
        "session from yesterday or the day before — anything older has "
        "already been purged.",
    )

sessions = store.list_sessions(since_days=None if show_all else 1)
for s in sessions:
    s["is_stale"] = store.session_is_stale(s, s.get("last_scanned"))

if not sessions:
    st.caption(
        "No sessions yet today." if not show_all
        else "No sessions in the last 3 days."
    )
else:
    st.markdown(C.session_list_table_html(sessions), unsafe_allow_html=True)

st.divider()
st.markdown(C.section_html("Session Detail"), unsafe_allow_html=True)

if not sessions:
    st.caption("Nothing to drill into yet.")
    st.stop()


def _session_label(s: dict) -> str:
    tag = " · STALE" if s["is_stale"] else (" · ended" if s["status"] == "ended" else "")
    sanford_id = s.get("sanford_id") or "—"
    location = s.get("location") or "—"
    return f'{sanford_id} — {location} ({s["created_at"][:16]}){tag}'


by_id = {s["session_id"]: s for s in sessions}
selected_id = st.selectbox(
    "Select a session to view its full scan list",
    options=list(by_id.keys()),
    format_func=lambda sid: _session_label(by_id[sid]),
)
selected = by_id[selected_id]

detail_col, action_col = st.columns([3, 1], gap="small", vertical_alignment="center")
with detail_col:
    st.markdown(
        C.session_status_pill_html(C.session_row_status_key(selected)),
        unsafe_allow_html=True,
    )
with action_col:
    if selected["status"] == store.STATUS_ACTIVE and st.button(
        "Force End",
        key="board_force_end",
        use_container_width=True,
        help="Escape hatch for a dropped/dead handheld — the picker's "
        "own device should normally end its session instead. Logged to "
        "the admin audit trail.",
    ):
        ok = store.force_end_session(selected_id)
        if ok:
            log_audit_event(
                "force_end_session",
                "monitor-board",
                session_id=selected_id,
                sanford_id=selected.get("sanford_id"),
            )
            st.toast("Session force-ended.", icon="✅")
            st.rerun()

history = history_for_session(selected_id)

if not history:
    st.caption("No scans recorded for this session yet.")
else:
    n = len(history)
    with st.container(key="sf_histhead"):
        head, action = st.columns([3, 1], gap="small", vertical_alignment="center")
        with head:
            st.markdown(
                C.section_html("", f"{n} item{'s' if n != 1 else ''}"),
                unsafe_allow_html=True,
            )
        with action:
            st.download_button(
                label="Export Session to Excel",
                data=build_workbook(
                    history,
                    location=selected.get("location"),
                    sanford_id=selected.get("sanford_id"),
                    session_id=selected_id,
                ),
                file_name=export_filename(
                    selected.get("location"),
                    selected.get("sanford_id"),
                    selected_id,
                    selected["created_at"],
                ),
                mime=EXPORT_MIME,
                use_container_width=True,
            )
    st.markdown(C.history_table_html(history), unsafe_allow_html=True)
