"""
core/lookup.py
~~~~~~~~~~~~~~
Scan orchestration.

This module holds the resolution logic that previously lived inline in app.py
(`extract_gtin` and `_process_scan`). Behaviour is unchanged — the same GS1
parsing, the same local-cache-then-API order, the same field mappings.

The heavy lifting still belongs to the existing packages, untouched:
  * engine.LookupEngine  — O(1) in-memory GTIN index
  * api.query_goodid     — AccessGUDID HTTP fallback
  * data.load_contract_data — parquet/Redshift loader with a 24h TTL

The only structural change is that resolution no longer writes to
st.session_state directly. `resolve_scan()` returns the result and lets the
caller persist it (see core/session.record_scan), which keeps the lookup path
testable and free of UI concerns.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime

import streamlit as st

from api import GoodIDResult, query_goodid
from data import load_contract_data
from engine import LookupEngine

logger = logging.getLogger(__name__)

# Canonical status keys. The UI maps these to colour/pill/icon; the Excel export
# continues to use the legacy emoji `status` string so its output is unchanged.
STATUS_CACHE = "cache"
STATUS_API = "api"
STATUS_NOT_FOUND = "notfound"
STATUS_HOLD = "hold"

# Legacy status labels — preserved verbatim because core/export.py writes them.
_LABEL_CACHE = "✅ Found"
_LABEL_API = "🌐 API Found"
_LABEL_NOT_FOUND = "❌ Not Found"


@st.cache_resource(show_spinner="Building GTIN lookup index…")
def get_lookup_engine() -> LookupEngine:
    """Build the GTIN lookup engine once and cache for the app lifetime.

    Wraps load_contract_data() (which is itself @st.cache_data(ttl=86400))
    so the index rebuild also only happens when the underlying data refreshes.
    """
    df = load_contract_data()
    engine = LookupEngine(df)
    logger.info("LookupEngine ready with %d entries.", engine.size)
    return engine


def extract_gtin(scanned_code: str) -> str:
    """Extract a 14-digit GTIN from a composite GS1 barcode."""
    code = scanned_code.strip()
    match = re.search(r'^(?:\][A-Za-z0-9]{2})?01(\d{14})', code)
    if match:
        return match.group(1)
    return code


def resolve_scan(
    raw_gtin: str,
    engine: LookupEngine,
    before_api: Callable[[], None] | None = None,
    after_api: Callable[[], None] | None = None,
) -> dict:
    """Resolve a single scanned GTIN: local cache first, goodID API as fallback.

    Args:
        raw_gtin: Raw string from the scanner input (may contain GS1 AI headers).
        engine: The in-memory contract-line index.
        before_api: Optional hook fired immediately before the (slow) network
            call. Used by the UI to raise an in-flight progress bar. Never fires
            on a cache hit, which is why cache hits show no loading state.
        after_api: Optional hook fired once the network call returns.

    Returns:
        A result dict carrying both the display record and a canonical status.
    """
    gtin = extract_gtin(raw_gtin)
    ts = datetime.now().strftime("%H:%M:%S")

    # ── Local cache lookup ────────────────────────────────────────────────────
    record = engine.search(gtin)

    if record is not None:
        logger.info("Cache HIT for GTIN %s", gtin)
        full_record = {
            "Scan": raw_gtin,
            "Item": record.get("vendor_item", ""),
            "Company": record.get("manufacturer_code", ""),
            "Brand": record.get("manufacturer_number", ""),
            "Description": " ".join(
                str(x)
                for x in filter(
                    None,
                    [
                        record.get("item_description"),
                        record.get("item_description2"),
                        record.get("item_description3"),
                    ],
                )
            ),
            "GTIN": gtin,
            "GTIN UOM": record.get("uom_unit_of_measure", ""),
            "UOU": record.get("low_uom_code_unit_of_measure", ""),
            "HIBCC": "-",
            "LAWSON ID": record.get("item_number", ""),
            "Lawson UOM": record.get("low_uom_code_unit_of_measure", ""),
        }
        on_hold = bool(record.get("on_hold"))
        return {
            "source": "cache",
            "gtin": gtin,
            "time": ts,
            "record": record,
            "full_record": full_record,
            "on_hold": on_hold,
            # On Hold overrides Cache Hit visually, but the legacy export label
            # stays "✅ Found" exactly as before.
            "status_key": STATUS_HOLD if on_hold else STATUS_CACHE,
            "status_label": _LABEL_CACHE,
            "source_label": "Contract Line",
        }

    # ── goodID API fallback ───────────────────────────────────────────────────
    logger.info("Cache MISS for GTIN %s — querying goodID API.", gtin)
    if before_api is not None:
        before_api()
    try:
        api_result: GoodIDResult = query_goodid(gtin)
    finally:
        if after_api is not None:
            after_api()

    if api_result.success:
        status_label = _LABEL_API
        status_key = STATUS_API
        device = api_result.payload.get("gudid", {}).get("device", {})

        # AccessGUDID/GUDID carries no Lawson-style UOM code (BX/CA/EA). The
        # value it exposes per packaging level is "pkgQuantity" — a *count* of
        # base units per package, not a unit of measure — so surfacing it as
        # "GTIN UOM" is misleading (it showed up as bare numbers like "20").
        # Mark the UOM unavailable for API results, consistent with the other
        # Lawson-only fields (LAWSON ID / HIBCC). The full packaging breakdown
        # remains visible in the raw AccessGUDID response expander.
        #
        # UOU (Unit of Use): GUDID lists it as its own identifier entry with
        # deviceIdType "Unit of Use", separate from the Primary and Package
        # DIs. Pull that deviceId — it's the value the legacy tool displayed.
        identifiers = device.get("identifiers", {}).get("identifier", [])
        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        uou = ""
        for ident in identifiers:
            if isinstance(ident, dict) and ident.get("deviceIdType") == "Unit of Use":
                uou = str(ident.get("deviceId") or "")
                break

        full_record = {
            "Scan": raw_gtin,
            "Item": device.get("versionModelNumber") or "",
            "Company": device.get("companyName") or "",
            "Brand": device.get("brandName") or "",
            "Description": device.get("deviceDescription") or "",
            "GTIN": gtin,
            "GTIN UOM": "-",
            "UOU": uou or "-",
            "HIBCC": "-",
            "LAWSON ID": "-",
            "Lawson UOM": "-",
        }
    else:
        status_label = _LABEL_NOT_FOUND
        status_key = STATUS_NOT_FOUND
        full_record = {
            "Scan": raw_gtin,
            "Item": "", "Company": "", "Brand": "", "Description": "",
            "GTIN": gtin, "GTIN UOM": "", "UOU": "-", "HIBCC": "-",
            "LAWSON ID": "-", "Lawson UOM": "-"
        }

    return {
        "source": "api",
        "gtin": gtin,
        "time": ts,
        "api_result": api_result,
        "full_record": full_record,
        "on_hold": False,
        "status_key": status_key,
        "status_label": status_label,
        "source_label": "goodID API",
    }
