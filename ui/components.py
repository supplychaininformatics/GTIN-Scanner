"""
ui/components.py
~~~~~~~~~~~~~~~~
Presentation components. Every function is pure: it takes data and returns an
HTML string. No colour is spelled out here — components only reference the
semantic classes and custom properties defined in ui/theme.py.

The tables are hand-rolled HTML rather than st.dataframe on purpose.
st.dataframe clips long text no matter how wide the page is, and a picker
cannot verify an item against a package label they cannot fully read.
"""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

import streamlit as st

from .theme import SESSION_STATUS, STATUS

APP_TITLE = "Warehouse GTIN Scanner"

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
# The approved asset. Supplied by the user; referenced, never redrawn.
_LOGO_CANDIDATES = ("sanford-logo.png", "sanford_logo.png")

_EM_DASH = "—"


# ── Logo ──────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _logo_data_uri() -> str | None:
    """Base64-inline the official Sanford Health mark, trimmed of dead margin.

    The mark is two-tone (navy wordmark, light-blue "HEALTH") on an opaque white
    background, so it is never recoloured or inverted — it sits on a white plate
    inside the blue bar instead. The only processing is cropping the uniform
    white border, so the logo reads correctly whether the supplied file is a
    tight crop or a large padded square.

    Returns None if no asset is present, in which case the header falls back to
    a neutral placeholder box.
    """
    path = next((_ASSETS / n for n in _LOGO_CANDIDATES if (_ASSETS / n).exists()), None)
    if path is None:
        return None

    try:
        from PIL import Image, ImageChops

        img = Image.open(path).convert("RGBA")
        # Flatten onto white — the plate behind it is white anyway.
        flat = Image.alpha_composite(
            Image.new("RGBA", img.size, (255, 255, 255, 255)), img
        ).convert("RGB")

        bbox = ImageChops.difference(
            flat, Image.new("RGB", flat.size, (255, 255, 255))
        ).getbbox()
        if bbox:
            flat = flat.crop(bbox)

        buf = io.BytesIO()
        flat.save(buf, format="PNG")
        raw = buf.getvalue()
    except Exception:
        # Pillow missing or the file is unreadable — inline the bytes as-is.
        try:
            raw = path.read_bytes()
        except OSError:
            return None

    return f"data:image/png;base64,{base64.b64encode(raw).decode()}"


# ── Header ────────────────────────────────────────────────────────────────────
def _identity_block_html(page_name: str | None = None) -> str:
    """Logo, wordmark, app title and (optionally) the current page name —
    the identity every page's header shares.

    The handheld is a special case: no logo (screen is too narrow to spare
    the space) and the app title splits across two lines instead of the
    page-name suffix the other pages use."""
    if page_name == "Handheld":
        return (
            '<div class="sf-wordmark">Supply Chain<br>'
            '<span class="sf-wordmark-line2">Informatics</span></div>'
            '<div class="sf-rule"></div>'
            '<div class="sf-apptitle sf-apptitle-stacked">Warehouse<br>GTIN Scanner</div>'
        )
    uri = _logo_data_uri()
    logo = (
        f'<div class="sf-logo-plate"><img src="{uri}" alt="Sanford Health"></div>'
        if uri
        else '<div class="sf-logo-fallback">Logo asset missing</div>'
    )
    page_html = (
        '<div class="sf-rule"></div>'
        f'<div class="sf-pagename">{html.escape(page_name)}</div>'
        if page_name
        else ""
    )
    return (
        f"{logo}"
        '<div class="sf-rule"></div>'
        '<div class="sf-wordmark">Supply Chain<br>'
        '<span class="sf-wordmark-line2">Informatics</span></div>'
        '<div class="sf-rule"></div>'
        f'<div class="sf-apptitle">{html.escape(APP_TITLE)}</div>'
        f"{page_html}"
    )


def identity_header_html(page_name: str | None = None) -> str:
    """The bare top bar — logo, wordmark, app title, no session chips.

    Used by pages that render before or without an active scan session (the
    pre-scan gate, the admin page), so every page shows the identical banner.
    """
    return (
        '<div class="sf-header"><div class="sf-header-left">'
        f"{_identity_block_html(page_name)}</div></div>"
    )


_KPI_CHIP_FIELDS = (
    ("total", "Total"),
    ("cache", "DW Hits"),
    ("api", "API Hits"),
    ("not_found", "Not Found"),
)


def _kpi_chip_html(stats: dict[str, int]) -> str:
    """Compact KPI chips for the handheld header, laid out as a 2x2 grid
    (see .sf-kpi-grid) instead of inline with the session chips. Not used
    by the monitor board or admin page, which never pass `kpi_stats` to
    header_html()."""
    out = []
    for key, label in _KPI_CHIP_FIELDS:
        value = stats.get(key, 0)
        out.append(
            f'<div class="sf-chip"><span class="sf-chip-k">{label}</span>'
            f'<span class="sf-chip-v" data-sf-key="{key}" data-sf-val="{value}">{value}</span></div>'
        )
    return f'<div class="sf-kpi-grid">{"".join(out)}</div>'


def header_html(
    location: str | None = None,
    sanford_id: str | None = None,
    page_name: str | None = None,
    kpi_stats: dict[str, int] | None = None,
) -> str:
    """The fixed top bar: identity block plus live session chips.

    `kpi_stats` is handheld-only (see _kpi_chip_html) — omitted by the
    monitor board and admin page.
    """
    chips = []
    if sanford_id:
        chips.append(("Sanford Id/ Name", html.escape(sanford_id)))
    if location:
        chips.append(("Warehouse Location", html.escape(location)))
    chip_html = "".join(
        f'<div class="sf-chip"><span class="sf-chip-k">{k}</span>'
        f'<span class="sf-chip-v">{v}</span></div>'
        for k, v in chips
    )
    kpi_html = _kpi_chip_html(kpi_stats) if kpi_stats is not None else ""

    return f"""
<div class="sf-header">
  <div class="sf-header-left">{_identity_block_html(page_name)}</div>
  <div class="sf-header-right">{chip_html}{kpi_html}</div>
</div>
"""


# ── Status ────────────────────────────────────────────────────────────────────
def status_pill_html(status_key: str) -> str:
    """The one status pill used by the hero card and every history row."""
    meta = STATUS.get(status_key)
    if meta is None:
        return ""
    return (
        f'<span class="sf-pill {meta["cls"]}">'
        f'<span class="sf-pill-glyph">{meta["icon"]}</span>{meta["label"]}</span>'
    )


def session_status_pill_html(status_key: str) -> str:
    """Session lifecycle pill (active/stale/ended) — the monitor board's
    equivalent of status_pill_html, using SESSION_STATUS instead of STATUS."""
    meta = SESSION_STATUS.get(status_key)
    if meta is None:
        return ""
    return (
        f'<span class="sf-pill {meta["cls"]}">'
        f'<span class="sf-pill-glyph">{meta["icon"]}</span>{meta["label"]}</span>'
    )


def progress_bar_html() -> str:
    """Indeterminate bar shown only while an API lookup is in flight."""
    return '<div class="sf-progress"></div>'


# ── Hero result card ──────────────────────────────────────────────────────────
def _val(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return html.escape(text) if text else _EM_DASH


def scan_result_card_html(result: dict, full_record: dict) -> str:
    """Handheld-only: the scan header (status, GTIN, time) and the full
    record key/value table merged into one card — one border/shadow instead
    of two stacked cards. Not used by the monitor board.

    A rescan of a GTIN already in this session's history is flagged
    `duplicate` by core.session.record_duplicate_scan(). It still shows the
    item's known status/data, but gets an extra banner up top since it was
    deliberately excluded from history, the KPIs and the Excel export.
    """
    key: str = result["status_key"]
    meta = STATUS[key]
    gtin = _val(result.get("gtin"))
    is_duplicate = bool(result.get("duplicate"))
    cls = f'{meta["cls"]} is-duplicate' if is_duplicate else meta["cls"]
    banner = '<div class="sf-hero-dup">Item already scanned</div>' if is_duplicate else ""

    rows = []
    for label, mono in _FULL_RECORD_FIELDS:
        raw = str(full_record.get(label) or "").strip()
        rcls = "sf-mono" if mono else "sf-wrap"
        if raw and label in ("Description", "GTIN"):
            cell = (
                f'<td class="{rcls} sf-wrap" title="{html.escape(raw)}" '
                f'data-sf-copy="{html.escape(raw)}">{html.escape(raw)}</td>'
            )
        else:
            cell = f'<td class="{rcls} sf-wrap">{_val(raw)}</td>'
        rows.append(f'<tr><th scope="row">{html.escape(label)}</th>{cell}</tr>')

    return f"""
<div class="sf-hero sf-hero-merged {cls}">
  {banner}
  <div class="sf-hero-top">
    {status_pill_html(key)}
    <span class="sf-hero-gtin-wrap">
      <span class="sf-hero-gtin-label">GTIN</span>
      <span class="sf-hero-gtin" data-sf-copy="{gtin}" title="Click to copy">{gtin}</span>
    </span>
  </div>
  <div class="sf-table-scroll sf-hero-record">
    <table class="sf-table sf-kv">
      <colgroup><col class="sf-c-key"><col class="sf-c-val"></colgroup>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</div>
"""


def empty_hero_html() -> str:
    """Shown before the first scan of the session."""
    return (
        '<div class="sf-empty">'
        '<div class="sf-empty-h">Ready to scan</div>'
        '<div class="sf-empty-p">Pull the trigger on a barcode, or type a GTIN '
        "into the scan lane and press Enter.</div>"
        "</div>"
    )


# ── Full record ───────────────────────────────────────────────────────────────
_FULL_RECORD_FIELDS = [
    ("Scan", True), ("GTIN", True), ("Item", True), ("Description", False),
]


# ── Session history ───────────────────────────────────────────────────────────
def history_table_html(history: list[dict]) -> str:
    """Newest-first scrollable history. Description wraps; nothing is ever clipped."""
    rows = []
    for i, entry in enumerate(reversed(history)):
        key = entry.get("status_key", "notfound")
        desc = str(entry.get("Description") or "").strip()
        gtin = str(entry.get("GTIN") or entry.get("gtin") or "").strip()
        scan = str(entry.get("Scan") or "").strip()

        if desc:
            desc_cell = (
                f'<td class="sf-wrap" title="{html.escape(desc)}" '
                f'data-sf-copy="{html.escape(desc)}">{html.escape(desc)}</td>'
            )
        else:
            desc_cell = f'<td class="sf-wrap sf-dim">{_EM_DASH}</td>'

        # A GTIN that breaks across two lines is a misread waiting to happen.
        gtin_cell = (
            f'<td class="sf-mono sf-nowrap" data-sf-copy="{html.escape(gtin)}" '
            f'title="Click to copy">{html.escape(gtin)}</td>'
            if gtin
            else f'<td class="sf-mono sf-dim">{_EM_DASH}</td>'
        )
        # The raw scan (unlike GTIN) can run longer than 14 digits on a composite
        # GS1 barcode, so it wraps rather than forcing a fixed nowrap width.
        scan_cell = (
            f'<td class="sf-mono sf-wrap" data-sf-copy="{html.escape(scan)}" '
            f'title="Click to copy">{html.escape(scan)}</td>'
            if scan
            else f'<td class="sf-mono sf-dim">{_EM_DASH}</td>'
        )

        # A rescan bumps this in place (see core/store.increment_scan) rather
        # than adding a new row, so >1 is the only signal on the board that a
        # picker scanned the same item twice — flag it instead of blending in.
        count = entry.get("Scan Count") or 1
        count_cls = "sf-mono sf-nowrap" + (" is-rescanned" if count > 1 else " sf-dim")
        count_cell = f'<td class="{count_cls}">{count}</td>'

        # Only the newest row animates in.
        cls = ' class="sf-new"' if i == 0 else ""
        rows.append(
            f"<tr{cls}>"
            f'<td class="sf-mono sf-dim sf-nowrap">{_val(entry.get("time"))}</td>'
            f"<td>{status_pill_html(key)}</td>"
            f"{scan_cell}"
            f"{gtin_cell}"
            f'<td class="sf-mono sf-wrap">{_val(entry.get("Item"))}</td>'
            f"{desc_cell}"
            f"{count_cell}"
            f"</tr>"
        )

    return f"""
<div class="sf-table-scroll is-history">
  <table class="sf-table">
    <colgroup>
      <col class="sf-c-time"><col class="sf-c-status"><col class="sf-c-scan">
      <col class="sf-c-gtin"><col class="sf-c-item"><col class="sf-c-desc">
      <col class="sf-c-count">
    </colgroup>
    <thead>
      <tr>
        <th>Time</th><th>Status</th><th>Scan</th>
        <th>GTIN</th><th>Item</th><th>Description</th><th>Scan Count</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
"""


def handheld_history_table_html(history: list[dict]) -> str:
    """Handheld-only condensed history: time (hh:mm), status, scan, item.
    GTIN/Description/Scan Count still live in the full history_table_html()
    used by the monitor board, and in the Excel export."""
    rows = []
    for i, entry in enumerate(reversed(history)):
        key = entry.get("status_key", "notfound")
        scan = str(entry.get("Scan") or "").strip()
        # Stored as %H:%M:%S (matches export); trim to hh:mm for this table.
        time_str = str(entry.get("time") or "")[:5]

        # The raw scan (unlike GTIN) can run longer than 14 digits on a composite
        # GS1 barcode, so it wraps rather than forcing a fixed nowrap width.
        scan_cell = (
            f'<td class="sf-mono sf-wrap" data-sf-copy="{html.escape(scan)}" '
            f'title="Click to copy">{html.escape(scan)}</td>'
            if scan
            else f'<td class="sf-mono sf-dim">{_EM_DASH}</td>'
        )

        # Only the newest row animates in.
        cls = ' class="sf-new"' if i == 0 else ""
        rows.append(
            f"<tr{cls}>"
            f'<td class="sf-mono sf-dim sf-nowrap">{_val(time_str)}</td>'
            f"<td>{status_pill_html(key)}</td>"
            f"{scan_cell}"
            f'<td class="sf-mono sf-wrap">{_val(entry.get("Item"))}</td>'
            f"</tr>"
        )

    return f"""
<div class="sf-table-scroll is-history">
  <table class="sf-table">
    <colgroup>
      <col class="sf-c-time"><col class="sf-c-status"><col class="sf-c-scan">
      <col class="sf-c-item">
    </colgroup>
    <thead>
      <tr>
        <th>Time</th><th>Status</th><th>Scan</th><th>Item</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
"""


def session_row_status_key(session: dict) -> str:
    """The SESSION_STATUS key a session row should render as: 'active',
    'stale', or 'ended'. Stale is derived (core.store.session_is_stale) —
    the row's own `status` column is either 'active' or 'ended' in the DB."""
    if session["status"] == "ended":
        return "ended"
    return "stale" if session.get("is_stale") else "active"


def session_list_table_html(sessions: list[dict]) -> str:
    """The monitor board's session list: Sanford Id/ Name, location, status, scan
    count, last-scan time. Newest first (caller sorts; this only renders).

    Deliberately presentational only — clicking a row to drill in is a
    Streamlit interaction (a button, not a link), so pages/board.py pairs
    this table with its own native per-row "View" controls rather than this
    module reaching for click handling it isn't built to own (see the
    module docstring: every function here is pure).
    """
    rows = []
    for s in sessions:
        key = session_row_status_key(s)
        last_scanned = s.get("last_scanned")
        last_cell = (
            f'<td class="sf-mono sf-nowrap">{_val(_wall_clock(last_scanned))}</td>'
            if last_scanned
            else f'<td class="sf-mono sf-dim">{_EM_DASH}</td>'
        )
        rows.append(
            "<tr>"
            f'<td class="sf-wrap">{_val(s.get("sanford_id"))}</td>'
            f'<td class="sf-wrap">{_val(s.get("location"))}</td>'
            f"<td>{session_status_pill_html(key)}</td>"
            f'<td class="sf-mono sf-nowrap">{_val(s.get("scan_count", 0))}</td>'
            f"{last_cell}"
            "</tr>"
        )

    return f"""
<div class="sf-table-scroll is-history">
  <table class="sf-table">
    <colgroup>
      <col class="sf-c-item"><col class="sf-c-item">
      <col class="sf-c-status"><col class="sf-c-time"><col class="sf-c-time">
    </colgroup>
    <thead>
      <tr>
        <th>Sanford Id/ Name</th><th>Location</th><th>Status</th>
        <th>Scans</th><th>Last Scan</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
"""


def _wall_clock(iso_ts: str | None) -> str:
    """Format a stored UTC ISO datetime for display. Mirrors
    core.session._wall_clock — duplicated here rather than imported so
    ui/components.py stays free of a core/ dependency (see ui/theme.py's
    "no other module may hardcode..." boundary: presentation doesn't reach
    into orchestration)."""
    if not iso_ts:
        return ""
    try:
        from datetime import datetime  # noqa: PLC0415

        return datetime.fromisoformat(iso_ts).strftime("%b %d, %H:%M:%S")
    except (TypeError, ValueError):
        return iso_ts


def section_html(title: str, count: str | None = None) -> str:
    """A section header rule. The export button is placed alongside by app.py.

    Deliberately a <div>, not an <h2> — Streamlit's own heading styles outrank
    ours and would blow this up to display size.
    """
    count_html = f'<span class="sf-section-count">{html.escape(count)}</span>' if count else ""
    return (
        f'<div class="sf-section"><span class="sf-section-h">{html.escape(title)}</span>'
        f'{count_html}<span class="sf-section-spacer"></span></div>'
    )
