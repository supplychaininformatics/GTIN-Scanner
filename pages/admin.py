"""
pages/admin.py
~~~~~~~~~~~~~~
Admin-only manual data refresh.

The scan page (app.py) is untouched and stays open to everyone — this page
is purely additive, and is where a manager/supervisor can force an
immediate re-fetch of the contract-line dataset instead of waiting on the
passive 24h cache. See core/admin.py for the allowlist and
cache-invalidation logic this page is a thin UI wrapper around.

Access is a typed-email allowlist, not a verified login: a visitor enters
their email, and it's checked against [admin] allowed_emails /
allowed_domains in .streamlit/secrets.toml. This is the software equivalent
of a sign-in sheet — it only gates access as long as the allowlist stays
private and specific, since anyone who learns an allowlisted address could
type it in. Every attempt (granted or denied) and every refresh is written
to the audit log via core.admin.log_audit_event, so access stays traceable
even though it can't be prevented outright. See README.md → "Admin refresh
page" for the tradeoff and how to upgrade to a verified login later.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.admin import (
    cooldown_remaining,
    is_admin,
    log_audit_event,
    read_audit_log,
    read_refresh_meta,
    refresh_now,
)
from core.lookup import get_lookup_engine
from data.loader import CACHE_PATH
from ui import components as C
from ui.theme import inject_theme

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title=f"Admin · {C.APP_TITLE}",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_theme()

# Same identity banner as every other page (logo, wordmark, app title) — this
# page's own context ("Data Refresh") is conveyed by the section heading
# below, not by overriding the shared header.
st.markdown(C.identity_header_html(), unsafe_allow_html=True)

if "admin_email" not in st.session_state:
    st.session_state.admin_email = None

# ── Not yet verified this session ───────────────────────────────────────────
if not st.session_state.admin_email:
    st.markdown(C.section_html("Admin Access"), unsafe_allow_html=True)
    st.write(
        "This page is restricted to managers and supervisors. Enter your "
        "email to continue — every attempt is logged."
    )
    with st.form("admin_email_form"):
        typed_email = st.text_input(
            "Email", placeholder="you@example.org", label_visibility="collapsed"
        )
        submitted = st.form_submit_button("Continue", type="primary")

    if submitted:
        candidate = typed_email.strip()
        if candidate and is_admin(candidate):
            log_audit_event("access_granted", candidate)
            st.session_state.admin_email = candidate.lower()
            st.rerun()
        else:
            log_audit_event("access_denied", candidate)
            st.error(
                "That email isn't on the admin allowlist. Ask IT to add you to "
                "`allowed_emails` (or your group's domain to `allowed_domains`) "
                "in `.streamlit/secrets.toml`."
            )

# ── Verified this session ───────────────────────────────────────────────────
else:
    email = st.session_state.admin_email
    st.markdown(C.section_html("Data Refresh"), unsafe_allow_html=True)
    st.caption(f"Continuing as {email}")

    engine = get_lookup_engine()
    meta = read_refresh_meta()
    if meta is not None:
        # 24h clock, matching the scan-timestamp convention in core/lookup.py.
        when = datetime.fromtimestamp(meta["ts"]).strftime("%b %d, %H:%M")
        st.info(
            f"Data last refreshed **{when}** by **{meta['by']}** · "
            f"{engine.size:,} contract lines."
        )
    elif CACHE_PATH.exists():
        when = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime).strftime("%b %d, %H:%M")
        st.info(
            f"Never manually refreshed — currently serving the automatic cache "
            f"from **{when}** · {engine.size:,} contract lines."
        )
    else:
        st.info(f"{engine.size:,} contract lines loaded.")

    remaining = cooldown_remaining()
    if st.button(
        "Refresh data now",
        type="primary",
        disabled=remaining > 0,
        help="Re-fetches the full contract-line dataset immediately, "
        "bypassing the normal 24h cache.",
    ):
        with st.spinner("Refreshing contract data…"):
            count = refresh_now(email)
        st.toast(f"Refreshed — {count:,} contract lines loaded.", icon="✅")
        st.rerun()

    if remaining > 0:
        mins, secs = divmod(remaining, 60)
        st.caption(f"Available again in {mins}m {secs}s — recently refreshed.")

    with st.expander("Recent access log"):
        entries = read_audit_log(limit=20)
        if not entries:
            st.caption("No activity logged yet.")
        else:
            _EVENT_LABEL = {
                "access_granted": "Signed in",
                "access_denied": "Denied",
                "refresh": "Refreshed",
            }
            rows = [
                {
                    "Time": datetime.fromtimestamp(e["ts"]).strftime("%b %d, %H:%M"),
                    "Event": _EVENT_LABEL.get(e["event"], e["event"]),
                    "Email": e["email"],
                    "Rows": e.get("rows", ""),
                }
                for e in entries
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.divider()
    if st.button("Switch email"):
        st.session_state.admin_email = None
        st.rerun()
