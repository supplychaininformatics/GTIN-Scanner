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

from .theme import STATUS

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
def _identity_block_html() -> str:
    """Logo, wordmark and app title — the identity every page's header shares."""
    uri = _logo_data_uri()
    logo = (
        f'<div class="sf-logo-plate"><img src="{uri}" alt="Sanford Health"></div>'
        if uri
        else '<div class="sf-logo-fallback">Logo asset missing</div>'
    )
    return (
        f"{logo}"
        '<div class="sf-rule"></div>'
        '<div class="sf-wordmark">Supply Chain Informatics</div>'
        '<div class="sf-rule"></div>'
        f'<div class="sf-apptitle">{html.escape(APP_TITLE)}</div>'
    )


def identity_header_html() -> str:
    """The bare top bar — logo, wordmark, app title, no session chips.

    Used by pages that render before or without an active scan session (the
    pre-scan gate, the admin page), so every page shows the identical banner.
    """
    return f'<div class="sf-header"><div class="sf-header-left">{_identity_block_html()}</div></div>'


def header_html(
    data_source: str, contract_lines: int, cache_ttl: str, location: str | None = None
) -> str:
    """The fixed top bar: identity block plus live session chips."""
    chips = [
        ("Data source", html.escape(data_source.upper())),
        ("Contract lines", f"{contract_lines:,}"),
        ("Cache TTL", html.escape(cache_ttl)),
    ]
    if location:
        chips.append(("Warehouse Location", html.escape(location)))
    chip_html = "".join(
        f'<div class="sf-chip"><span class="sf-chip-k">{k}</span>'
        f'<span class="sf-chip-v">{v}</span></div>'
        for k, v in chips
    )
    # The clock is filled and ticked by the client runtime.
    chip_html += (
        '<div class="sf-chip"><span class="sf-chip-k">Session</span>'
        '<span class="sf-chip-v" id="sf-clock">--:--:--</span></div>'
    )

    return f"""
<div class="sf-header">
  <div class="sf-header-left">{_identity_block_html()}</div>
  <div class="sf-header-right">{chip_html}</div>
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


def progress_bar_html() -> str:
    """Indeterminate bar shown only while an API lookup is in flight."""
    return '<div class="sf-progress"></div>'


# ── KPI strip ─────────────────────────────────────────────────────────────────
def kpi_strip_html(stats: dict[str, int]) -> str:
    """Five tight tiles: three across, then the two alert tiles on a wider row.

    On Hold turns amber and Not Found turns red the moment they are non-zero.
    """
    tiles = [
        ("total", "Total Scans", "", False),
        ("cache", "Data Warehouse Hits", "", False),
        ("api", "API Hits", "", False),
        ("not_found", "Not Found", "is-red", True),
        ("on_hold", "On Hold", "is-amber", True),
    ]
    out = []
    for key, label, alert_cls, wide in tiles:
        value = stats.get(key, 0)
        cls = "sf-kpi-tile"
        if wide:
            cls += " is-wide"
        if alert_cls and value:
            cls += f" {alert_cls}"
        out.append(
            f'<div class="{cls}">'
            f'<span class="sf-kpi-num" data-sf-key="{key}" data-sf-val="{value}">{value}</span>'
            f'<span class="sf-kpi-lab">{label}</span>'
            f"</div>"
        )
    return f'<div class="sf-kpi">{"".join(out)}</div>'


# ── Hero result card ──────────────────────────────────────────────────────────
def _val(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return html.escape(text) if text else _EM_DASH


def hero_card_html(result: dict) -> str:
    """The scan header — status, GTIN and time. Every field lives in the full
    record table directly beneath it, so this bar never repeats one.

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

    return f"""
<div class="sf-hero {cls}">
  {banner}
  <div class="sf-hero-top">
    {status_pill_html(key)}
    <span class="sf-hero-gtin-wrap">
      <span class="sf-hero-gtin-label">GTIN</span>
      <span class="sf-hero-gtin" data-sf-copy="{gtin}" title="Click to copy">{gtin}</span>
    </span>
    <span class="sf-hero-time">{_val(result.get("time"))}</span>
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
    ("Company", False), ("Brand", False), ("GTIN UOM", True), ("UOU", True),
    ("HIBCC", True), ("LAWSON ID", True), ("Lawson UOM", True),
]


def full_record_table_html(fr: dict) -> str:
    """Full record as a key/value table, shown directly under the scan header.

    Rendered vertically rather than as one wide row so that every value has the
    full panel width to wrap into — a horizontal 11-column layout is exactly
    what was clipping the description before.
    """
    rows = []
    for label, mono in _FULL_RECORD_FIELDS:
        raw = str(fr.get(label) or "").strip()
        cls = "sf-mono" if mono else "sf-wrap"
        if raw and label in ("Description", "GTIN"):
            cell = (
                f'<td class="{cls} sf-wrap" title="{html.escape(raw)}" '
                f'data-sf-copy="{html.escape(raw)}">{html.escape(raw)}</td>'
            )
        else:
            cell = f'<td class="{cls} sf-wrap">{_val(raw)}</td>'
        rows.append(f'<tr><th scope="row">{html.escape(label)}</th>{cell}</tr>')

    return f"""
<div class="sf-table-scroll">
  <table class="sf-table sf-kv">
    <colgroup><col class="sf-c-key"><col class="sf-c-val"></colgroup>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
"""


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
            f"</tr>"
        )

    return f"""
<div class="sf-table-scroll is-history">
  <table class="sf-table">
    <colgroup>
      <col class="sf-c-time"><col class="sf-c-status"><col class="sf-c-scan">
      <col class="sf-c-gtin"><col class="sf-c-item"><col class="sf-c-desc">
    </colgroup>
    <thead>
      <tr>
        <th>Time</th><th>Status</th><th>Scan</th>
        <th>GTIN</th><th>Item</th><th>Description</th>
      </tr>
    </thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
"""


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
