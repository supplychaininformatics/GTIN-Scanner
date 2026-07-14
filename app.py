"""
app.py
~~~~~~
GTIN Barcode Scanner — Streamlit entry point.

Composition only. Page config, the header, and the two-column workspace.
  * Lookup / API / caching  → engine/, api/, data/  (unchanged)
  * Scan orchestration      → core/lookup.py
  * Session + history model → core/session.py
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
from dotenv import load_dotenv

from core.export import EXPORT_FILENAME, EXPORT_MIME, build_workbook
from core.lookup import extract_gtin, get_lookup_engine, resolve_scan
from core.session import (
    clear_result,
    compute_stats,
    find_duplicate,
    init_session,
    record_duplicate_scan,
    record_scan,
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

engine = get_lookup_engine()

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown(
    C.header_html(
        data_source=os.getenv("DATA_SOURCE", "mock"),
        contract_lines=engine.size,
        cache_ttl="24h",
    ),
    unsafe_allow_html=True,
)

# The slot lives above the workspace but is filled after the scan resolves, so
# the in-flight bar appears directly under the header where it belongs.
progress_slot = st.empty()

left, right = st.columns([38, 62], gap="large")

# ── Left rail: the scan lane ──────────────────────────────────────────────────
with left, st.container(key="sf_rail"):
    # The card is a keyed container styled by CSS. A bare <div> in st.markdown
    # cannot wrap sibling widgets — Streamlit closes it inside its own block.
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

    kpi_slot = st.empty()

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
elif submitted:
    warn_slot.markdown(
        '<div class="sf-hint" style="margin-top:.6rem">'
        '<span class="sf-hint-k">Empty</span>'
        "<span>No GTIN received. Scan again.</span></div>",
        unsafe_allow_html=True,
    )

last = st.session_state.last_result
history = st.session_state.scan_history

# ── Right panel: the result stage ─────────────────────────────────────────────
with right, st.container(key="sf_stage"):
    if last:
        st.markdown(C.hero_card_html(last), unsafe_allow_html=True)
        st.markdown(
            C.full_record_table_html(last.get("full_record", {})),
            unsafe_allow_html=True,
        )

        if last.get("source") == "api" and last.get("api_result") is not None:
            with st.expander("Raw AccessGUDID response"):
                st.json(last["api_result"].payload)
    else:
        st.markdown(C.empty_hero_html(), unsafe_allow_html=True)

    if history:
        n = len(history)
        with st.container(key="sf_histhead"):
            head, action = st.columns([3, 1], gap="small", vertical_alignment="center")
            with head:
                st.markdown(
                    C.section_html("Session History", f"{n} scan{'s' if n != 1 else ''}"),
                    unsafe_allow_html=True,
                )
            with action:
                st.download_button(
                    label="Export Session to Excel",
                    data=build_workbook(history),
                    file_name=EXPORT_FILENAME,
                    mime=EXPORT_MIME,
                    use_container_width=True,
                )
        # Absorbs the remaining viewport height and scrolls internally.
        with st.container(key="sf_hist"):
            st.markdown(C.history_table_html(history), unsafe_allow_html=True)

# ── Fill the deferred slot ─────────────────────────────────────────────────────
kpi_slot.markdown(C.kpi_strip_html(compute_stats(history)), unsafe_allow_html=True)

# ── Client runtime: autofocus, alert tones, Esc, clock, copy, count-up ────────
scanner_runtime(
    nonce=st.session_state.scan_nonce,
    kind=last["status_key"] if last else None,
    sound_on=st.session_state.sound_on,
)
