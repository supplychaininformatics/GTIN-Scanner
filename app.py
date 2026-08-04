"""
app.py
~~~~~~
GTIN Barcode Scanner — Handheld scan page, Streamlit entry point.

One of two surfaces (see PLAN.md): this is the picker-facing handheld —
opens to a start form (Sanford ID + location), then the scan loop. Session
lifecycle is owned entirely here: a session is minted on submit and can only
be normal-ended from here (the monitor board, pages/board.py, is a passive
viewer with a force-end escape hatch for a dropped device, not a normal-end
control). Stacked mobile layout — the scan field, result and history all run
down one column, top to bottom, sized for a phone/handheld screen rather
than a desktop monitor. KPI counters live in the header's chip row (see
ui.components.header_html's kpi_stats), not a separate strip in this column.

  * Lookup / API / caching  → engine/, api/, data/  (unchanged)
  * Scan orchestration      → core/lookup.py
  * Session + history model → core/session.py (backed by core/store.py)
  * Excel export            → core/export.py
  * Every pixel             → ui/theme.py, ui/components.py

The scan form still uses st.form(clear_on_submit=True). That is load-bearing:
barcode scanners are keyboard emulators, and scanning the same GTIN twice in a
row would not change the widget value — so without the form, Streamlit would not
rerun on the second scan. The form clears the field and forces a rerun every time.
"""

from __future__ import annotations

import logging
import os

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from core import store
from core.export import EXPORT_MIME, build_workbook, export_filename
from core.lookup import extract_gtin, get_lookup_engine, resolve_scan
from core.session import (
    clear_result,
    compute_stats,
    end_session,
    find_duplicate,
    init_session,
    record_duplicate_scan,
    record_scan,
    resume_session,
    start_session,
)
from ui import components as C
from ui.theme import inject_theme, scanner_runtime

# ── Bootstrap ─────────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title=f"{C.APP_TITLE} · Supply Chain Informatics",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_theme()
init_session()

# ── Pre-scan gate: capture Sanford ID + location once per browser session ─────
# A resumed session (refresh, reconnect, server restart) carries its session id
# in the URL — session_state itself may have been wiped, but the URL survives
# all of those, so this is the only durable pointer back to the right store row.
if not st.session_state.session_id:
    resume_sid = st.query_params.get("sid")
    if resume_sid:
        saved = store.get_session(resume_sid)
        if saved and saved["status"] == store.STATUS_ACTIVE:
            resume_session(resume_sid, saved)
            st.rerun()
        else:
            # Unknown, already-ended, or force-ended session — drop the dead
            # param and fall through to a normal start gate instead of
            # looping on it.
            del st.query_params["sid"]

    st.markdown(C.identity_header_html(page_name="Handheld"), unsafe_allow_html=True)
    # Set when a supervisor force-ended this device's session out from under it
    # (see the liveness check below). Shown once, on the gate the picker lands
    # on, so the bounce reads as a deliberate action rather than a crash.
    if st.session_state.pop("force_ended_notice", False):
        st.warning(
            "This session was ended from the monitor board or admin page. "
            "Any scans you had already made were saved and can still be "
            "exported from the board. Start a new session to keep scanning."
        )
    st.markdown(C.section_html("Start New Session"), unsafe_allow_html=True)
    st.markdown(
        '<p class="sf-section-subtext">Scan your badge or type your Sanford Id/ Name, '
        "then enter the current warehouse location.</p>",
        unsafe_allow_html=True,
    )
    with st.form("start_form"):
        sanford_id_input = st.text_input(
            "Sanford Id/ Name",
            placeholder="Scan badge or type Sanford Id/ Name",
        )
        location_input = st.text_input(
            "Warehouse Location",
            placeholder="e.g. Sioux Falls GS1",
        )
        start_submitted = st.form_submit_button("Start Session", type="primary")

    if start_submitted:
        sanford_id_candidate = sanford_id_input.strip()
        location_candidate = location_input.strip()
        if sanford_id_candidate and location_candidate:
            start_session(sanford_id_candidate, location_candidate)
            # st.query_params only does history.replaceState under the hood —
            # a client-side URL rewrite with no real navigation. Mobile
            # browsers routinely restore the *originally loaded* URL (no
            # ?sid) on a hard refresh or after the tab is backgrounded/
            # evicted, which was dropping the picker back to the start gate
            # mid-session. A real navigation to the ?sid URL makes it the
            # document the browser actually reloads.
            components.html(
                f"""<script>
                    window.parent.location.replace(
                        window.parent.location.pathname + "?sid={st.session_state.session_id}"
                    );
                </script>""",
                height=0,
            )
            st.stop()
        elif not sanford_id_candidate:
            st.error("Enter or scan a Sanford Id/ Name to continue.")
        else:
            st.error("Enter a warehouse location to continue.")
    st.stop()

# ── Liveness: has this session been force-ended out from under this device? ───
# The resume gate above only runs when session_state was empty, so a handheld
# already in the scan loop would never notice a board/admin Force End — it
# would keep scanning against an ended session, and those scans would keep
# landing on it (core.store.record_scan does not check status). Re-reading the
# row once per rerun is what makes Force End actually reach the device it is
# meant to stop.
#
# Local state is cleared directly rather than via end_session(): the store row
# is already ended, and calling end_session() would overwrite the supervisor's
# ended_at with a later timestamp, corrupting the audit trail of when the
# force-end actually happened.
current = store.get_session(st.session_state.session_id)
if current is None or current["status"] != store.STATUS_ACTIVE:
    st.session_state.session_id = None
    st.session_state.sanford_id = None
    st.session_state.warehouse_location = None
    st.session_state.scan_history = []
    st.session_state.last_result = None
    st.session_state.force_ended_notice = True
    st.query_params.clear()
    st.rerun()

engine = get_lookup_engine()

# ── Header ────────────────────────────────────────────────────────────────────
# The KPI counters render as a 2x2 grid in the header (see .sf-kpi-grid) —
# computed from the session's history-so-far, so this render reflects any
# scan just recorded.
st.markdown(
    C.header_html(
        location=st.session_state.warehouse_location,
        sanford_id=st.session_state.sanford_id,
        page_name="Handheld",
        kpi_stats=compute_stats(st.session_state.scan_history),
    ),
    unsafe_allow_html=True,
)


@st.dialog("End Session?")
def _confirm_end_session() -> None:
    """Gate on the one moment data could be lost for good: forgetting to
    export before clearing state. Cancel leaves the session untouched."""
    n = len(st.session_state.scan_history)
    st.write(
        f"This will end this session and clear its {n} scan{'s' if n != 1 else ''} "
        "from this device. Make sure you've downloaded the Excel export first — "
        "the session stays reachable from the monitor board for 3 days, but this "
        "device's view of it can't be undone."
    )
    cancel_col, end_col = st.columns(2)
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.rerun()
    with end_col:
        if st.button("End Session", type="primary", use_container_width=True):
            end_session()
            st.query_params.clear()
            st.rerun()


with st.container(key="sf_endsession"):
    if st.button("End Session", key="sf_end_session_btn", use_container_width=True):
        _confirm_end_session()

# The slot lives above the workspace but is filled after the scan resolves, so
# the in-flight bar appears directly under the header where it belongs.
progress_slot = st.empty()

# ── Scan lane ──────────────────────────────────────────────────────────────────
# Stacked mobile layout: scan field, result and history all run down one
# column top to bottom (see PLAN.md — the handheld is a phone/handheld
# screen, not a desktop monitor, so there is no side-by-side rail/stage split).
with st.container(key="sf_rail"):
    with st.container(key="sf_lane"):
        st.markdown('<div class="sf-eyebrow">Scan Lane</div>', unsafe_allow_html=True)

        with st.container(key="sf_scan"), st.form("scan_form", clear_on_submit=True):
            gtin_input = st.text_input(
                label="GTIN",
                placeholder="Scan or type a GTIN",
                label_visibility="collapsed",
                max_chars=50,
            )
            submitted = st.form_submit_button("Look Up", use_container_width=True)

        warn_slot = st.empty()

    with st.container(key="sf_sound"):
        st.toggle("Audible alerts", key="sound_on")

    # Esc bridges to session state by clicking this (visually hidden) button.
    with st.container(key="sf_clear"):
        st.button("Clear", key="sf_clear_btn", on_click=clear_result)

# ── Resolve the scan ──────────────────────────────────────────────────────────
if submitted and gtin_input.strip():
    raw_gtin = gtin_input.strip()
    # A GTIN already in this session's history is a rescan of the same item —
    # resolved instantly from what we already know, with no cache/API lookup,
    # so it can never inflate the API-hit KPI either.
    duplicate = find_duplicate(extract_gtin(raw_gtin))
    if duplicate is not None:
        record_duplicate_scan(raw_gtin, duplicate["gtin"], duplicate)
    else:
        result = resolve_scan(
            raw_gtin,
            engine,
            # Cache hits are instant and show nothing. Only the network call raises
            # the in-flight bar — and Streamlit streams the delta, so it is visible
            # for the duration of the blocking request.
            before_api=lambda: progress_slot.markdown(
                C.progress_bar_html(), unsafe_allow_html=True
            ),
            after_api=progress_slot.empty,
        )
        record_scan(result)
    # The header above (with its KPI chip row) was already drawn earlier in
    # this same script run, from history-before-this-scan — st.markdown has
    # no way to go back and redraw it. Rerunning is the only way to get the
    # header to reflect the scan just recorded, matching every other
    # state-mutating action on this page (start_session, end_session).
    st.rerun()
elif submitted:
    warn_slot.markdown(
        '<div class="sf-hint" style="margin-top:.6rem">'
        '<span class="sf-hint-k">Empty</span>'
        "<span>No GTIN received. Scan again.</span></div>",
        unsafe_allow_html=True,
    )

last = st.session_state.last_result
history = st.session_state.scan_history

# ── Result stage ───────────────────────────────────────────────────────────────
with st.container(key="sf_stage"):
    if last:
        st.markdown(
            C.scan_result_card_html(last, last.get("full_record", {})),
            unsafe_allow_html=True,
        )

    else:
        st.markdown(C.empty_hero_html(), unsafe_allow_html=True)

    if history:
        n = len(history)
        with st.container(key="sf_histhead"):
            head, action = st.columns([3, 1], gap="small", vertical_alignment="center")
            with head:
                st.markdown(
                    C.section_html("Session History", f"{n} item{'s' if n != 1 else ''}"),
                    unsafe_allow_html=True,
                )
            with action:
                st.download_button(
                    label="Export to Excel",
                    data=build_workbook(
                        history,
                        location=st.session_state.warehouse_location,
                        sanford_id=st.session_state.sanford_id,
                        session_id=st.session_state.session_id,
                    ),
                    file_name=export_filename(
                        st.session_state.warehouse_location,
                        st.session_state.sanford_id,
                        st.session_state.session_id,
                        store.get_session(st.session_state.session_id)["created_at"],
                    ),
                    mime=EXPORT_MIME,
                    use_container_width=True,
                )
        # Absorbs the remaining viewport height and scrolls internally.
        with st.container(key="sf_hist"):
            st.markdown(C.handheld_history_table_html(history), unsafe_allow_html=True)

# ── Client runtime: autofocus, alert tones, Esc, clock, copy, count-up ────────
scanner_runtime(
    nonce=st.session_state.scan_nonce,
    kind=last["status_key"] if last else None,
    sound_on=st.session_state.sound_on,
)
