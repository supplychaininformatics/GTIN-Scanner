"""
ui/theme.py
~~~~~~~~~~~
The single source of truth for brand colour, type and motion.

Everything visual is defined here exactly once:
  * PALETTE  — the approved Sanford Health colours, in Python.
  * :root    — the same colours re-emitted as CSS custom properties.
  * inject_theme() — the ONE stylesheet injected into the app.

No other module may hardcode a colour. Components reference `var(--sf-*)` or a
semantic class name. Derived tints/rings are computed with color-mix() from the
base tokens rather than being spelled out as new hexes.
"""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

# ── Approved palette (Sanford Health) ─────────────────────────────────────────
PALETTE: dict[str, str] = {
    "sf-blue": "#003C71",        # PMS 541 — primary
    "sf-light-blue": "#6CACE4",  # PMS 284 — primary
    "sf-gray": "#A7A8AA",        # Cool Gray 6 — secondary
    "sf-sand": "#CFC493",        # PMS 4535 — secondary, sparing
    "sf-ink": "#0B1F33",         # body copy
    "sf-surface": "#FFFFFF",
    "sf-canvas": "#F4F7FA",      # page background
    "sf-success": "#007F5F",     # status only
    "sf-amber": "#F2A900",       # status only — ON HOLD
    "sf-red": "#DA211C",         # status only — NOT FOUND
}

# ── Canonical statuses ────────────────────────────────────────────────────────
# One definition, used by the hero card, the history table and the KPI tiles so
# a status can never mean two different things in two places.
STATUS: dict[str, dict[str, str]] = {
    "cache":    {"label": "Cache Hit", "icon": "✓", "cls": "is-cache"},
    "api":      {"label": "API Found", "icon": "↗", "cls": "is-api"},
    "notfound": {"label": "Not Found", "icon": "✕", "cls": "is-notfound"},
    "hold":     {"label": "On Hold",   "icon": "⚠", "cls": "is-hold"},
}

HEADER_HEIGHT_PX = 72


def _root_vars() -> str:
    """Emit the palette as CSS custom properties, plus derived tokens."""
    base = "\n".join(f"    --{k}: {v};" for k, v in PALETTE.items())
    return f"""
:root {{
{base}

    /* Type */
    --sf-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
    --sf-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;

    /* Metrics */
    --sf-header-h: {HEADER_HEIGHT_PX}px;

    /* Derived tokens — never new colours, always mixes of the approved ones. */
    --sf-muted:        color-mix(in srgb, var(--sf-ink) 55%, var(--sf-gray));
    --sf-hairline:     color-mix(in srgb, var(--sf-gray) 45%, var(--sf-surface));
    --sf-zebra:        color-mix(in srgb, var(--sf-canvas) 70%, var(--sf-surface));
    --sf-hover:        color-mix(in srgb, var(--sf-light-blue) 12%, var(--sf-surface));
    --sf-focus-ring:   color-mix(in srgb, var(--sf-light-blue) 45%, transparent);

    --sf-success-tint: color-mix(in srgb, var(--sf-success) 10%, var(--sf-surface));
    --sf-lightblue-tint: color-mix(in srgb, var(--sf-light-blue) 16%, var(--sf-surface));
    --sf-amber-tint:   color-mix(in srgb, var(--sf-amber) 16%, var(--sf-surface));
    --sf-red-tint:     color-mix(in srgb, var(--sf-red) 9%, var(--sf-surface));

    --sf-success-edge: color-mix(in srgb, var(--sf-success) 35%, var(--sf-surface));
    --sf-lightblue-edge: color-mix(in srgb, var(--sf-light-blue) 55%, var(--sf-surface));
    --sf-amber-edge:   color-mix(in srgb, var(--sf-amber) 50%, var(--sf-surface));
    --sf-red-edge:     color-mix(in srgb, var(--sf-red) 35%, var(--sf-surface));

    --sf-blue-hover:   color-mix(in srgb, var(--sf-blue) 82%, var(--sf-light-blue));
    --sf-shadow:       color-mix(in srgb, var(--sf-ink) 10%, transparent);
    --sf-shadow-soft:  color-mix(in srgb, var(--sf-ink) 6%, transparent);
}}
"""


_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap');

__ROOT__

/* ── Reset Streamlit chrome ─────────────────────────────────────────────── */
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
#MainMenu,
footer { display: none !important; visibility: hidden !important; }

html, body, .stApp { background: var(--sf-canvas) !important; }
[data-testid="stAppViewContainer"] { background: var(--sf-canvas) !important; }

html, body, .stApp, [data-testid="stAppViewContainer"] {
    font-family: var(--sf-sans);
    color: var(--sf-ink);
    font-size: 16px;
}

/* Every pixel earns its place: full-bleed container, content starts under the bar. */
.block-container {
    max-width: 100% !important;
    padding: calc(var(--sf-header-h) + 1rem) 2rem 1.25rem 2rem !important;
}
[data-testid="stVerticalBlock"] { gap: 0.7rem !important; }
[data-testid="stHorizontalBlock"] { gap: 1.5rem !important; }

/* ── Fixed header ───────────────────────────────────────────────────────── */
.sf-header {
    position: fixed; top: 0; left: 0; right: 0;
    height: var(--sf-header-h);
    background: var(--sf-blue);
    z-index: 999990;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 2rem;
    box-shadow: 0 2px 12px var(--sf-shadow);
}
.sf-header-left { display: flex; align-items: center; gap: 1.5rem; }
/* The mark is two-tone on white and must never be recoloured — so it sits on
   its own white plate rather than being inverted onto the blue. */
.sf-logo-plate {
    background: var(--sf-surface);
    border-radius: 6px;
    padding: 7px 13px;
    display: flex; align-items: center;
}
.sf-logo-plate img { height: 30px; display: block; }
.sf-logo-fallback {
    height: 30px; min-width: 130px;
    display: flex; align-items: center; justify-content: center;
    border: 1px dashed var(--sf-gray);
    border-radius: 4px;
    color: var(--sf-muted);
    font-size: .625rem; letter-spacing: .08em; text-transform: uppercase; font-weight: 600;
    padding: 0 .75rem;
}
.sf-rule { width: 1px; height: 36px; background: rgb(255 255 255 / .25); }
.sf-wordmark {
    color: var(--sf-surface);
    font-weight: 600; font-size: 1.0625rem;
    letter-spacing: .04em; text-transform: uppercase; line-height: 1.2;
    white-space: nowrap;
}
/* The app's own name — the thing a user actually looks for in a row of
   header tabs, so it outweighs the department wordmark rather than
   deferring to it. */
.sf-apptitle {
    color: var(--sf-surface);
    font-weight: 800; font-size: 1.375rem;
    letter-spacing: .01em; line-height: 1.2;
    white-space: nowrap;
}
.sf-header-right { display: flex; align-items: center; gap: 1.75rem; }
.sf-chip { display: flex; flex-direction: column; gap: 2px; line-height: 1.15; }
.sf-chip-k {
    font-size: .625rem; text-transform: uppercase; letter-spacing: .09em;
    color: rgb(255 255 255 / .6); font-weight: 600;
}
.sf-chip-v {
    font-size: .875rem; color: rgb(255 255 255 / .95); font-weight: 600;
    font-family: var(--sf-mono); font-variant-numeric: tabular-nums;
}

/* ── API in-flight bar (cache hits never render this) ───────────────────── */
.sf-progress {
    position: relative; height: 3px; width: 100%;
    background: var(--sf-lightblue-tint);
    border-radius: 2px; overflow: hidden;
}
.sf-progress::after {
    content: ''; position: absolute; top: 0; bottom: 0; left: 0; width: 32%;
    background: var(--sf-light-blue);
    animation: sfIndet 900ms ease-in-out infinite;
}
@keyframes sfIndet {
    0%   { transform: translateX(-110%); }
    100% { transform: translateX(360%); }
}

/* ── Left rail: the scan lane ───────────────────────────────────────────── */
.st-key-sf_rail { position: sticky; top: calc(var(--sf-header-h) + 1rem); }

/* The card is a keyed container, not a bare <div> in st.markdown — Streamlit
   closes a stray div inside its own block, so it can never wrap the widgets. */
.st-key-sf_lane {
    background: var(--sf-surface);
    border: 1px solid var(--sf-hairline);
    border-radius: 12px;
    padding: 1rem 1.1rem .9rem;
    box-shadow: 0 1px 2px var(--sf-shadow-soft);
}
.sf-eyebrow {
    display: block;
    font-size: .6875rem; text-transform: uppercase; letter-spacing: .09em;
    font-weight: 700; color: var(--sf-blue);
    margin: 0 0 .5rem; line-height: 1;
}
.st-key-sf_lane [data-testid="stVerticalBlock"] { gap: .5rem !important; }

/* Streamlit's "Press Enter to submit form / 0/50" hint sits on top of the
   oversized placeholder. The hints below the field already say this. */
[data-testid="InputInstructions"] { display: none !important; }

/* The single most important control in the app.

   The height has to live on the BaseWeb wrapper, not on the <input>. Streamlit
   sizes that wrapper to ~40px, so a taller input simply overflows it and the
   text gets sheared off at the bottom. Size the wrapper, then let the input
   fill it and centre its own line box. */
.st-key-sf_scan div[data-baseweb="input"] {
    height: 64px !important;
    min-height: 64px !important;
    align-items: center !important;
    border: 2px solid var(--sf-light-blue) !important;
    border-radius: 10px !important;
    background: var(--sf-surface) !important;
    transition: border-color 160ms ease-out, box-shadow 160ms ease-out;
    overflow: hidden;
}
.st-key-sf_scan div[data-baseweb="input"] > div {
    height: 100% !important;
    align-items: center !important;
}
.st-key-sf_scan div[data-baseweb="input"]:focus-within {
    border-color: var(--sf-blue) !important;
    box-shadow: 0 0 0 4px var(--sf-focus-ring) !important;
}
.st-key-sf_scan input {
    height: 100% !important;
    line-height: 1 !important;
    font-size: 24px !important;
    font-family: var(--sf-mono) !important;
    font-variant-numeric: tabular-nums;
    letter-spacing: .06em !important;
    color: var(--sf-ink) !important;
    background: transparent !important;
    padding: 0 .85rem !important;
    font-weight: 600;
}
/* The scanned value stays 24px; the placeholder is only a prompt, so it drops
   to a size that fits the field comfortably instead of crowding it. */
.st-key-sf_scan input::placeholder {
    color: var(--sf-gray) !important;
    font-size: 1rem !important;
    letter-spacing: .03em;
    font-weight: 400;
}

/* Buttons — primary blue, 44px+ touch targets. */
[data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {
    background: var(--sf-blue) !important;
    color: var(--sf-surface) !important;
    border: 1px solid var(--sf-blue) !important;
    border-radius: 8px !important;
    min-height: 44px !important;
    font-weight: 600 !important;
    font-size: .9375rem !important;
    letter-spacing: .03em;
    transition: background 160ms ease-out, border-color 160ms ease-out;
}
[data-testid="stFormSubmitButton"] button:hover,
[data-testid="stDownloadButton"] button:hover {
    background: var(--sf-blue-hover) !important;
    border-color: var(--sf-blue-hover) !important;
    color: var(--sf-surface) !important;
}
[data-testid="stFormSubmitButton"] button:focus-visible,
[data-testid="stDownloadButton"] button:focus-visible {
    box-shadow: 0 0 0 4px var(--sf-focus-ring) !important;
}

/* Admin link and End Session button — pinned to the bottom-RIGHT corner of the
   viewport (not the document flow, so scrolling the history table never moves
   them), side by side.

   Streamlit wraps the keyed container in a full-width layout wrapper that
   carries the surface background — that wrapper is the white box. Pin it to the
   corner and strip every surface/box/padding from it AND the keyed block, so
   only the two blue buttons show. The wrapper is targeted three ways
   (:has on the parent, the parent-of-parent, and the keyed node itself) so the
   fix holds regardless of exactly which node Streamlit puts the class on. */
[data-testid="stLayoutWrapper"]:has(.st-key-sf_endsession),
[data-testid="stVerticalBlockBorderWrapper"]:has(.st-key-sf_endsession),
.st-key-sf_endsession {
    position: fixed !important;
    bottom: 1.25rem;
    right: 1.5rem;
    left: auto !important;
    width: 300px !important;
    max-width: none !important;
    z-index: 999980;
    background: transparent !important;
    background-color: transparent !important;
    box-shadow: none !important;
    border: none !important;
    padding: 0 !important;
    margin: 0 !important;
}
/* Two equal st.columns hold the buttons — keep them side by side (never
   Streamlit's narrow-viewport stacking) and strip every nested surface. */
.st-key-sf_endsession [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    gap: .5rem !important;
}
.st-key-sf_endsession [data-testid="stColumn"] {
    width: calc(50% - .25rem) !important;
    flex: 1 1 0 !important;
    min-width: 0 !important;
}
.st-key-sf_endsession [data-testid="stVerticalBlock"],
.st-key-sf_endsession [data-testid="stElementContainer"] {
    background: transparent !important;
    box-shadow: none !important;
    border: none !important;
    padding: 0 !important;
}
/* Both are real st.buttons now — identical styling, each fills its column, so
   the two columns being equal makes the two buttons equal. */
.st-key-sf_endsession [data-testid="stButton"] button {
    width: 100% !important;
    min-width: 0 !important;
    background: var(--sf-blue) !important;
    color: var(--sf-surface) !important;
    border: 1px solid var(--sf-blue) !important;
    border-radius: 6px !important;
    height: 34px !important;
    padding: 0 .75rem !important;
    box-sizing: border-box !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    white-space: nowrap !important;
    font-weight: 600 !important;
    font-size: .8125rem !important;
    letter-spacing: .03em;
    text-decoration: none !important;
    transition: background 160ms ease-out, border-color 160ms ease-out;
}
.st-key-sf_endsession [data-testid="stButton"] button * {
    color: inherit !important;
    font-weight: inherit !important;
    white-space: nowrap !important;
}
.st-key-sf_endsession [data-testid="stButton"] button:hover {
    background: var(--sf-blue-hover) !important;
    border-color: var(--sf-blue-hover) !important;
    color: var(--sf-surface) !important;
}
.st-key-sf_endsession [data-testid="stButton"] button:focus-visible {
    box-shadow: 0 0 0 4px var(--sf-focus-ring) !important;
}

[data-testid="stForm"] {
    border: none !important; padding: 0 !important; background: transparent !important;
}

/* Inline note shown when a scan submits an empty field. */
.sf-hint { display: flex; align-items: baseline; gap: .5rem; font-size: .8125rem; color: var(--sf-muted); }
.sf-hint-k {
    font-size: .625rem; text-transform: uppercase; letter-spacing: .08em;
    font-weight: 700; color: var(--sf-blue); white-space: nowrap; min-width: 62px;
}

/* Sound toggle — kept clear of the KPI tiles above it. */
.st-key-sf_sound { margin-top: 1.1rem !important; }
[data-testid="stToggle"] label, [data-testid="stCheckbox"] label {
    font-size: .75rem !important;
    text-transform: uppercase; letter-spacing: .07em; font-weight: 600 !important;
    color: var(--sf-muted) !important;
}

/* ── KPI strip — three across, then the two alert tiles on a wider row ──────
   A 6-column grid: the normal tiles span 2, the alert tiles span 3, so five
   tiles still fill both rows edge to edge with no orphan cell. */
.sf-kpi {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: .55rem;
}
.sf-kpi-tile {
    grid-column: span 2;
    background: var(--sf-surface);
    border: 1px solid var(--sf-hairline);
    border-radius: 10px;
    padding: .65rem .7rem;
    display: flex; flex-direction: column; gap: 1px;
    transition: border-color 200ms ease-out, background 200ms ease-out;
}
.sf-kpi-tile.is-wide { grid-column: span 3; }
.sf-kpi-num {
    font-family: var(--sf-mono); font-variant-numeric: tabular-nums;
    font-size: 1.6rem; font-weight: 700; line-height: 1.15;
    color: var(--sf-blue);
}
/* "Data Warehouse Hits" is long — let it wrap rather than overflow its tile.
   Grid stretches the row, so a two-line label keeps the tiles the same height. */
.sf-kpi-lab {
    font-size: .625rem; text-transform: uppercase; letter-spacing: .06em;
    font-weight: 700; color: var(--sf-muted);
    line-height: 1.25;
}
.sf-kpi-tile.is-amber { border-color: var(--sf-amber); background: var(--sf-amber-tint); }
.sf-kpi-tile.is-amber .sf-kpi-num { color: var(--sf-ink); }
.sf-kpi-tile.is-amber .sf-kpi-lab { color: var(--sf-ink); }
.sf-kpi-tile.is-red { border-color: var(--sf-red); background: var(--sf-red-tint); }
.sf-kpi-tile.is-red .sf-kpi-num { color: var(--sf-red); }
.sf-kpi-tile.is-red .sf-kpi-lab { color: var(--sf-red); }

/* ── Status pill — one look, everywhere ─────────────────────────────────── */
.sf-pill {
    display: inline-flex; align-items: center; gap: .35rem;
    padding: .25rem .55rem;
    border-radius: 999px;
    border: 1px solid;
    font-size: .6875rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: .05em;
    white-space: nowrap;
}
.sf-pill-glyph { font-size: .8125rem; line-height: 1; }
.sf-pill.is-cache    { color: var(--sf-success);    background: var(--sf-success-tint);    border-color: var(--sf-success-edge); }
.sf-pill.is-api      { color: var(--sf-blue);       background: var(--sf-lightblue-tint);  border-color: var(--sf-lightblue-edge); }
.sf-pill.is-notfound { color: var(--sf-red);        background: var(--sf-red-tint);        border-color: var(--sf-red-edge); }
.sf-pill.is-hold     { color: var(--sf-ink);        background: var(--sf-amber-tint);      border-color: var(--sf-amber); }

/* ── Hero result card ───────────────────────────────────────────────────── */
.sf-hero {
    background: var(--sf-surface);
    border-radius: 12px;
    border: 1px solid var(--sf-hairline);
    border-left: 4px solid var(--sf-gray);
    padding: 1.25rem 1.5rem;
    box-shadow: 0 1px 2px var(--sf-shadow-soft), 0 10px 28px var(--sf-shadow-soft);
    animation: sfFadeIn 180ms ease-out;
}
.sf-hero.is-cache    { border-left-color: var(--sf-success); }
.sf-hero.is-api      { border-left-color: var(--sf-light-blue); }
.sf-hero.is-notfound { border-left-color: var(--sf-red); }
.sf-hero.is-hold     { border-left-color: var(--sf-amber); }
/* Rescans keep their underlying status colour everywhere else (pill, left
   edge), but the sand accent — used nowhere else — flags this one as a
   repeat the moment it renders. */
.sf-hero.is-duplicate { border-left-color: var(--sf-sand); }
@keyframes sfFadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: none; }
}

.sf-hero-dup {
    display: inline-flex; align-items: center; gap: .4rem;
    font-size: .6875rem; text-transform: uppercase; letter-spacing: .08em;
    font-weight: 700; color: var(--sf-ink);
    background: color-mix(in srgb, var(--sf-sand) 40%, var(--sf-surface));
    border: 1px solid var(--sf-sand);
    border-radius: 999px;
    padding: .3rem .65rem;
    margin: 0 0 .75rem;
}

.sf-hero-top {
    display: flex; align-items: center; gap: .75rem;
}
.sf-hero-gtin-wrap { display: flex; align-items: baseline; gap: .4rem; }
.sf-hero-gtin-label {
    font-size: .6875rem; text-transform: uppercase; letter-spacing: .08em;
    font-weight: 700; color: var(--sf-muted);
}
.sf-hero-gtin {
    font-family: var(--sf-mono); font-variant-numeric: tabular-nums;
    font-size: 1.25rem; font-weight: 700; color: var(--sf-blue);
    letter-spacing: .04em;
}
.sf-hero-time {
    margin-left: auto;
    font-family: var(--sf-mono); font-size: .8125rem; color: var(--sf-muted);
}

.sf-empty {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: .5rem;
    background: var(--sf-surface);
    border: 1px dashed var(--sf-hairline);
    border-radius: 12px;
    padding: 3rem 1.5rem;
    text-align: center;
}
.sf-empty-h { font-size: 1.25rem; font-weight: 700; color: var(--sf-blue); }
.sf-empty-p { font-size: .9375rem; color: var(--sf-muted); }

/* ── Section headers ────────────────────────────────────────────────────── */
.sf-section {
    display: flex; align-items: baseline; gap: .6rem;
    margin: 0;
}
.sf-section .sf-section-h {
    font-size: .8125rem !important;
    text-transform: uppercase; letter-spacing: .09em;
    font-weight: 700 !important; color: var(--sf-blue);
    margin: 0; padding: 0; line-height: 1.4;
}
.sf-section-count {
    font-family: var(--sf-mono); font-size: .75rem; font-weight: 600;
    color: var(--sf-muted);
}
.sf-section-spacer { flex: 1; }

/* Title and Export button share one row, vertically centred. Scoped so the
   main 38/62 workspace columns keep their default top alignment. */
.st-key-sf_histhead { margin: .9rem 0 .5rem; }
.st-key-sf_histhead [data-testid="stDownloadButton"] button { min-height: 40px !important; }

/* ── Tables: NOTHING TRUNCATES, EVER ────────────────────────────────────── */
.sf-table-scroll {
    overflow-y: auto; overflow-x: hidden;
    border: 1px solid var(--sf-hairline);
    border-radius: 10px;
    background: var(--sf-surface);
}
/* Full record sits directly under the hero — cap it so it can't push the
   rest of the stage (history, etc.) off screen. */
.sf-table-scroll:not(.is-history) { max-height: 40vh; }

/* ── The right panel owns the viewport ──────────────────────────────────────
   The stage is exactly one screen tall, the hero sits at the top, and Session
   History absorbs whatever height is left over and scrolls inside itself. That
   is what keeps the scan lane and the hero both visible at 1366x768 while
   still leaving no dead canvas at 1080p.

   !important is load-bearing: Streamlit's emotion classes set their own height
   and outrank a plain rule. Every keyed container is also wrapped in a
   stLayoutWrapper, so it is the *wrapper* — not our container — that ends up
   being the flex child of the stage.

   And Streamlit makes the stage itself a flex item with `flex-basis: 0%`, which
   makes the browser ignore `height` on the main axis entirely — hence
   `flex: 0 0 auto`, without which the calc below silently does nothing. */
.st-key-sf_stage {
    display: flex !important;
    flex-direction: column !important;
    flex: 0 0 auto !important;
    height: calc(100vh - var(--sf-header-h) - 2rem) !important;
    min-height: 0 !important;
}
.st-key-sf_stage > [data-testid="stLayoutWrapper"]:last-child {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
}
.st-key-sf_hist,
.st-key-sf_hist [data-testid="stElementContainer"],
.st-key-sf_hist [data-testid="stMarkdown"],
.st-key-sf_hist [data-testid="stMarkdown"] > div,
.st-key-sf_hist [data-testid="stMarkdownContainer"] {
    display: flex !important;
    flex-direction: column !important;
    flex: 1 1 auto !important;
    min-height: 0 !important;   /* without this a flex child refuses to shrink */
    margin: 0 !important;
    padding: 0 !important;
    width: 100%;
}

.sf-table-scroll.is-history {
    flex: 1 1 auto;
    min-height: 0;
    max-height: none;
    height: auto;
}
.sf-table {
    width: 100%;
    table-layout: fixed;      /* fixed cols + a fluid Description column */
    border-collapse: collapse;
    font-size: .9375rem;
}
.sf-table th {
    position: sticky; top: 0; z-index: 2;
    background: var(--sf-blue);
    color: var(--sf-surface);
    text-align: left;
    font-size: .625rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 700;
    padding: .6rem .7rem;
    white-space: nowrap;
}
.sf-table td {
    padding: .6rem .7rem;
    vertical-align: top;
    border-bottom: 1px solid var(--sf-hairline);
    color: var(--sf-ink);
    line-height: 1.4;
}
.sf-table tbody tr:nth-child(even) { background: var(--sf-zebra); }
.sf-table tbody tr:hover { background: var(--sf-hover); }
.sf-table tbody tr:last-child td { border-bottom: none; }
.sf-table tbody tr.sf-new { animation: sfRowIn 220ms ease-out; }
@keyframes sfRowIn {
    from { opacity: 0; transform: translateY(-8px); }
    to   { opacity: 1; transform: none; }
}

/* Long text wraps onto as many lines as it needs. No ellipsis. Ever. */
.sf-wrap {
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
}
.sf-mono { font-family: var(--sf-mono); font-variant-numeric: tabular-nums; }
.sf-dim { color: var(--sf-muted); }

/* Fixed columns are sized to their known content so they can never steal space
   from Description, which takes everything that is left over. Time and GTIN are
   `nowrap` and sized to fit a full 8-char clock / 14-digit GTIN: a number that
   breaks across two lines is a misread waiting to happen. */
.sf-table .sf-nowrap { white-space: nowrap; }
.sf-table .sf-mono { font-size: .8125rem; letter-spacing: .01em; }

.sf-c-time   { width: 96px; }
.sf-c-status { width: 118px; }
.sf-c-scan   { width: 140px; }
.sf-c-gtin   { width: 150px; }
.sf-c-item   { width: 110px; }
.sf-c-desc   { width: 100%; }
.sf-c-key    { width: 130px; }
.sf-c-val    { width: 100%; }

/* On a 1366-wide monitor the right panel is narrow, so the fixed columns give
   ground back to Description rather than squeezing it out. */
@media (max-width: 1500px) {
    .sf-c-time   { width: 88px; }
    .sf-c-status { width: 106px; }
    .sf-c-scan   { width: 118px; }
    .sf-c-gtin   { width: 140px; }
    .sf-c-item   { width: 96px; }
    .sf-c-key    { width: 110px; }
    .sf-table td, .sf-table th { padding: .5rem .5rem; }
}

/* Click-to-copy affordance */
[data-sf-copy] { cursor: pointer; border-radius: 4px; transition: background 160ms ease-out; }
[data-sf-copy]:hover { text-decoration: underline dotted; text-underline-offset: 3px; }
[data-sf-copy].sf-copied {
    background: var(--sf-success-tint);
    text-decoration: none;
}

/* Full record: a key/value table, so a long value can never be clipped. */
.sf-kv th {
    position: static;
    background: var(--sf-canvas);
    color: var(--sf-muted);
    border-bottom: 1px solid var(--sf-hairline);
    border-right: 1px solid var(--sf-hairline);
    vertical-align: top;
    font-size: .625rem;
}
.sf-kv td { font-size: .9375rem; }

/* ── Expander — not a bright blue Streamlit bar ─────────────────────────── */
[data-testid="stExpander"] details,
[data-testid="stExpander"] > div {
    border: 1px solid var(--sf-hairline) !important;
    border-radius: 10px !important;
    background: var(--sf-surface) !important;
    box-shadow: none !important;
}
[data-testid="stExpander"] summary {
    background: var(--sf-surface) !important;
    color: var(--sf-blue) !important;
    font-weight: 600 !important;
    font-size: .8125rem !important;
    text-transform: uppercase; letter-spacing: .07em;
    border-radius: 10px !important;
}
[data-testid="stExpander"] summary:hover { background: var(--sf-hover) !important; }
[data-testid="stExpander"] svg { fill: var(--sf-blue) !important; color: var(--sf-blue) !important; }

/* ── Hidden plumbing ────────────────────────────────────────────────────── */
/* Esc bridges to session state by clicking this button. */
.st-key-sf_clear {
    position: absolute !important;
    left: -9999px !important; top: auto !important;
    width: 1px !important; height: 1px !important;
    overflow: hidden !important;
}
/* The JS runtime iframe: present and executing, but zero-height. */
.st-key-sf_runtime, .st-key-sf_runtime > div {
    height: 0 !important; min-height: 0 !important;
    margin: 0 !important; padding: 0 !important;
    overflow: hidden !important;
}
.st-key-sf_runtime iframe {
    height: 0 !important; min-height: 0 !important;
    border: 0 !important; display: block !important;
}

/* ── Motion: restrained, and optional ───────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: .001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: .001ms !important;
    }
}

/* ── 1366x768: keep the scan lane and hero on-screen together ───────────── */
@media (max-height: 800px) {
    .sf-hero { padding: 1rem 1.25rem; }
    .sf-kpi-num { font-size: 1.4rem; }
    .sf-table-scroll:not(.is-history) { max-height: 34vh; }
    .block-container { padding-bottom: .75rem !important; }
}
"""


def inject_theme() -> None:
    """Inject the one and only stylesheet. Call once, immediately after page config."""
    st.markdown(
        f"<style>{_CSS.replace('__ROOT__', _root_vars())}</style>",
        unsafe_allow_html=True,
    )


# ── Client runtime ────────────────────────────────────────────────────────────
# One component, in a same-origin iframe, driving the parent document.
#
# Streamlit destroys and rebuilds this iframe on every rerun, which tears down
# the JS realm with it. Any listener registered by a previous run is therefore
# dead — so the runtime unregisters the stale handlers and re-binds fresh ones
# from the live realm on every run. Only *state* (audio context, KPI values,
# last nonce) is parked on the parent window, where it survives.
_JS = r"""
<script>
(function () {
  var P, D;
  try { P = window.parent; D = P.document; } catch (e) { return; }
  if (!P || !D) return;

  var PAYLOAD = __PAYLOAD__;

  /* Durable state lives on the parent window; handlers do not. */
  var S = P.__sf;
  if (!S) { S = P.__sf = { lastNonce: -1, kpi: {}, ctx: null, off: [], clock: null }; }

  /* Tear down anything bound by the previous (now dead) realm. */
  for (var i = 0; i < S.off.length; i++) { try { S.off[i](); } catch (e) {} }
  S.off = [];
  if (S.clock) { try { P.clearInterval(S.clock); } catch (e) {} S.clock = null; }

  function on(target, type, fn, capture) {
    target.addEventListener(type, fn, capture);
    S.off.push(function () { target.removeEventListener(type, fn, capture); });
  }

  /* ── Audio ─────────────────────────────────────────────────────────────
     Warehouse users are looking at the item, not the screen. The context is
     built with the PARENT window's constructor, so autoplay gating follows the
     parent's user activation — the scanner's own Enter keypress supplies it. */
  function ensureCtx() {
    if (!S.ctx) {
      var AC = P.AudioContext || P.webkitAudioContext;
      if (!AC) return null;
      try { S.ctx = new AC(); } catch (e) { return null; }
    }
    if (S.ctx.state === 'suspended') { try { S.ctx.resume(); } catch (e) {} }
    return S.ctx;
  }

  function beep(freq, start, dur, gain, type) {
    var ctx = S.ctx; if (!ctx) return;
    var t = ctx.currentTime + start;
    var osc = ctx.createOscillator(), g = ctx.createGain();
    osc.type = type || 'sine';
    osc.frequency.setValueAtTime(freq, t);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    osc.connect(g); g.connect(ctx.destination);
    osc.start(t); osc.stop(t + dur + 0.02);
  }

  function playTone(kind) {
    if (!ensureCtx()) return;
    if (kind === 'hold') {
      /* Urgent and unmistakable: three hard alternating pulses. */
      beep(880, 0.00, 0.15, 0.30, 'square');
      beep(620, 0.19, 0.15, 0.30, 'square');
      beep(880, 0.38, 0.20, 0.30, 'square');
    } else if (kind === 'notfound') {
      /* Error: a descending two-tone buzz. Clearly not the hold tone. */
      beep(330, 0.00, 0.17, 0.26, 'sawtooth');
      beep(196, 0.18, 0.28, 0.26, 'sawtooth');
    } else if (kind === 'cache' || kind === 'api') {
      /* Clean: a soft, short confirmation click. */
      beep(1318, 0.00, 0.05, 0.09, 'sine');
    }
  }

  function unlock() { ensureCtx(); }
  on(D, 'keydown', unlock, true);
  on(D, 'pointerdown', unlock, true);

  /* ── Focus: the scan lane must always be armed ────────────────────────── */
  function input() {
    return D.querySelector('.st-key-sf_scan input')
        || D.querySelector('input[aria-label="GTIN"]');
  }
  function focusInput() {
    var tries = 0;
    (function attempt() {
      var el = input();
      if (el) {
        if (D.activeElement !== el) {
          try { el.focus({ preventScroll: true }); el.select(); } catch (e) {}
        }
        return;
      }
      if (tries++ < 40) P.setTimeout(attempt, 50);
    })();
  }

  /* Clicking dead space re-arms the gun. Controls and tables are left alone so
     the user can still press buttons and select text in order to read it. */
  on(D, 'click', function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    if (t.closest('button, a, input, textarea, select, summary, label, [role="switch"], .sf-table, [data-sf-copy]')) return;
    focusInput();
  }, true);
  on(P, 'focus', function () { focusInput(); }, false);

  /* ── Esc: drop the result and re-arm ──────────────────────────────────── */
  on(D, 'keydown', function (e) {
    if (e.key !== 'Escape') return;
    var el = input();
    if (el) el.value = '';
    var btn = D.querySelector('.st-key-sf_clear button');
    if (btn) btn.click(); else focusInput();
  }, true);

  /* ── Click to copy (GTIN + Description cells) ─────────────────────────── */
  on(D, 'click', function (e) {
    var el = (e.target && e.target.closest) ? e.target.closest('[data-sf-copy]') : null;
    if (!el) return;
    var text = el.getAttribute('data-sf-copy') || '';
    if (!text) return;
    var done = function () {
      el.classList.add('sf-copied');
      P.setTimeout(function () { el.classList.remove('sf-copied'); }, 900);
    };
    try {
      if (P.navigator.clipboard && P.navigator.clipboard.writeText) {
        P.navigator.clipboard.writeText(text).then(done, function () {});
        return;
      }
    } catch (err) {}
    try {
      var ta = D.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed'; ta.style.opacity = '0';
      D.body.appendChild(ta); ta.select();
      D.execCommand('copy');
      D.body.removeChild(ta);
      done();
    } catch (err2) {}
  }, true);

  /* ── Live session clock ───────────────────────────────────────────────── */
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function tick() {
    var el = D.getElementById('sf-clock');
    if (!el) return;
    var d = new Date();
    el.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }
  tick();
  S.clock = P.setInterval(tick, 1000);

  /* ── KPI count-up ─────────────────────────────────────────────────────────
     The previous value survives the rerun because it is parked on the parent
     window, not read back out of the (re-rendered) DOM. */
  function countUp() {
    var reduce = false;
    try { reduce = P.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) {}
    var nodes = D.querySelectorAll('.sf-kpi-num[data-sf-key]');
    Array.prototype.forEach.call(nodes, function (node) {
      var key = node.getAttribute('data-sf-key');
      var to = parseInt(node.getAttribute('data-sf-val') || '0', 10);
      var from = (S.kpi[key] === undefined) ? to : S.kpi[key];
      S.kpi[key] = to;
      if (reduce || from === to) { node.textContent = String(to); return; }
      var dur = 240, t0 = null;
      P.requestAnimationFrame(function step(ts) {
        if (t0 === null) t0 = ts;
        var k = Math.min(1, (ts - t0) / dur);
        var eased = 1 - Math.pow(1 - k, 3);
        node.textContent = String(Math.round(from + (to - from) * eased));
        if (k < 1) P.requestAnimationFrame(step);
      });
    });
  }

  /* Fire the alert tone exactly once per scan, not on every rerun. */
  if (PAYLOAD.nonce !== S.lastNonce) {
    S.lastNonce = PAYLOAD.nonce;
    if (PAYLOAD.sound && PAYLOAD.kind) {
      P.setTimeout(function () { playTone(PAYLOAD.kind); }, 0);
    }
  }

  countUp();
  focusInput();
})();
</script>
"""


def scanner_runtime(nonce: int, kind: str | None, sound_on: bool) -> None:
    """Mount the client runtime: autofocus, alert tones, Esc, clock, copy, count-up.

    Args:
        nonce: Increments once per scan. Guarantees one tone per scan.
        kind:  Canonical status key of the latest scan, or None.
        sound_on: The user's persisted sound preference.
    """
    payload = json.dumps({"nonce": nonce, "kind": kind, "sound": bool(sound_on)})
    with st.container(key="sf_runtime"):
        components.html(_JS.replace("__PAYLOAD__", payload), height=0)
