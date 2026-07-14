"""
data/loader.py
~~~~~~~~~~~~~~
Responsible for loading and caching the supply chain contract line dataset.

Contains two distinct blocks:
  1. PRODUCTION REDSHIFT BLOCK  — commented out, ready to activate with VPN.
  2. LOCAL DEV MOCK BLOCK       — active by default for local development.

The public entry point `load_contract_data()` dispatches to the correct block
based on the DATA_SOURCE environment variable ("mock" | "redshift").
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "cache" / "contract_lines.parquet"

# ── SQL Reference (kept here for parity with the production query) ────────────
_SQL_QUERY = """
SELECT
    item_number,
    vendor_item,
    implantable,
    base_cost,
    uom_unit_of_measure,
    global_trade_item_number,
    item_description,
    item_description2,
    item_description3,
    item_type_state,
    low_uom_code_unit_of_measure,
    low_uom_code_gtin,
    manufacturer_code,
    manufacturer_number,
    san_multi_use_qty,
    contract,
    contract_line,
    on_hold
FROM gold.fsm_contractline
WHERE contract_line_state = 2;
"""


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTION REDSHIFT BLOCK
# Active. Requires REDSHIFT_HOST/PORT/DB/USER/PASSWORD in .env and
# DATA_SOURCE=redshift.
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def _load_from_redshift() -> pd.DataFrame:
    """Pull active contract lines from the Redshift gold layer.

    Connects using credentials from environment variables, executes the
    contract line query, and returns the result as a typed DataFrame.

    Returns:
        pd.DataFrame: Contract line records with correct column types.

    Raises:
        redshift_connector.Error: On connection or query failure.
    """
    import redshift_connector  # noqa: PLC0415

    logger.info("Connecting to Redshift at %s", os.getenv("REDSHIFT_HOST"))
    conn = redshift_connector.connect(
        host=os.environ["REDSHIFT_HOST"],
        port=int(os.getenv("REDSHIFT_PORT", "5439")),
        database=os.environ["REDSHIFT_DB"],
        user=os.environ["REDSHIFT_USER"],
        password=os.environ["REDSHIFT_PASSWORD"],
    )
    try:
        cursor = conn.cursor()
        cursor.execute(_SQL_QUERY)
        df: pd.DataFrame = cursor.fetch_dataframe()
    finally:
        conn.close()

    # CRITICAL: Redshift may return GTIN as numeric, silently dropping leading
    # zeros. Force to string immediately after fetch.
    df["global_trade_item_number"] = df["global_trade_item_number"].astype(str)

    # Ensure on_hold is a proper boolean regardless of Redshift driver casting.
    df["on_hold"] = df["on_hold"].astype(bool)

    logger.info("Loaded %d contract lines from Redshift.", len(df))
    return df


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL DEV MOCK BLOCK (active)
# Data sourced directly from contract_line.xlsx (Sheet1).
# Includes 5 on_hold=true items for UI warning testing and 15 active items
# across manufacturers: BARD, MOLN, CARD, CONV, WECL, HOLL.
# ─────────────────────────────────────────────────────────────────────────────
def _load_mock_data_fallback() -> pd.DataFrame:
    """Load a representative sample from the real contract_line.xlsx dataset.

    Mirrors the exact column set returned by the Redshift production query.
    GTINs are stored as strings to preserve leading zeros.
    NaN values from the Excel source are represented as None.

    Returns:
        pd.DataFrame: 20-row dataset sourced from real contract line data.
    """
    rows = [
        # ── ON HOLD items (5) — sourced from contract_line.xlsx ───────────────
        {
            "item_number": "6112182",
            "vendor_item": "0620064012",
            "implantable": "false",
            "base_cost": 185.99,
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "10801741030021",
            "item_description": "DRN PEZZER PROPORTIONATE 12FR",
            "item_description2": "BX6/EA1",
            "item_description3": "CATHETER NEPHROSTOMY DRAINAGE 12FR LATEX 2 EYE PROPORTIONATE HEAD DISPOSABLE PEZZERS",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741030024",
            "manufacturer_code": "BARD",
            "manufacturer_number": "064012",
            "san_multi_use_qty": 0,
            "contract": "1020285",
            "contract_line": 8,
            "on_hold": True,
        },
        {
            "item_number": "6112213",
            "vendor_item": "0620064010",
            "implantable": "false",
            "base_cost": 185.99,
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "10801741030014",
            "item_description": "DRN PEZZER PROPORTIONATE 10FR",
            "item_description2": "CA6/EA1",
            "item_description3": "CATHETER NEPHROSTOMY DRAINAGE 10FR 2 EYES PROPORTIONATE HEAD TIP WITHOUT BALLOON PEZZER",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741030017",
            "manufacturer_code": "BARD",
            "manufacturer_number": "064010",
            "san_multi_use_qty": 0,
            "contract": "1020285",
            "contract_line": 26,
            "on_hold": True,
        },
        {
            "item_number": "6114704",
            "vendor_item": "420127",
            "implantable": "false",
            "base_cost": 17.49,
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "10768455118219",
            "item_description": "DRSG HYDROFBR ROPE 1X45CM",
            "item_description2": "BX5/EA1",
            "item_description3": "DRESSING HYDROCOLLOID W1XL45CM ABSORBENT WITH STRENGTHENING FIBER HYDROFIBER AQUACEL",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00768455118212",
            "manufacturer_code": "CONV",
            "manufacturer_number": "420127",
            "san_multi_use_qty": 0,
            "contract": "1020670",
            "contract_line": 3,
            "on_hold": True,
        },
        {
            "item_number": "6114753",
            "vendor_item": "1638187955",
            "implantable": "false",
            "base_cost": 9.65,
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "00768455106912",
            "item_description": "DRSG DUODERM XTHN 4X4",
            "item_description2": "BX10/EA1",
            "item_description3": "DRESSING HYDROCOLLOID W4XL4IN BEIGE SQUARE VAPOR PERMEABLE OUTER FILM TRANSLUCENT BACKING FLEXIBLE CONFORMABLE DUODERM EXTRA THIN CGF",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00768455150922",
            "manufacturer_code": "CONV",
            "manufacturer_number": "187955",
            "san_multi_use_qty": 0,
            "contract": "1020669",
            "contract_line": 3,
            "on_hold": True,
        },
        {
            "item_number": "6114795",
            "vendor_item": "187660",
            "implantable": "false",
            "base_cost": 1.272,
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00768455174843",
            "item_description": "DRSG DUODERM CGF 4X4",
            "item_description2": "BX5/EA1",
            "item_description3": "DRESSING HYDROCOLLOID W4XL4IN BEIGE SQUARE MOISTURE RETENTIVE DUODERM CGF",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "CONV",
            "manufacturer_number": "187660",
            "san_multi_use_qty": 0,
            "contract": "1020670",
            "contract_line": 8,
            "on_hold": True,
        },
        # ── Active items (15) — sourced from contract_line.xlsx ───────────────
        {
            "item_number": "6112009",
            "vendor_item": "6112009",
            "implantable": "false",
            "base_cost": 0.93,
            "uom_unit_of_measure": "PR",
            "global_trade_item_number": "05060097930852",
            "item_description": "GLOVE SURG BIOGEL PF 6.0",
            "item_description2": "CA200/BX50/PR1",
            "item_description3": "GLOVE SURGICAL 6 BIOGEL SURGEONS LATEX STRAW POWDER FREE",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "MOLN",
            "manufacturer_number": "30460",
            "san_multi_use_qty": 0,
            "contract": "1021882",
            "contract_line": 3,
            "on_hold": False,
        },
        {
            "item_number": "6112010",
            "vendor_item": "30465",
            "implantable": "false",
            "base_cost": 52.00,
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "05060097930944",
            "item_description": "GLOVE SURG BIOGEL PF 6.5",
            "item_description2": "CA200/BX50/PR1",
            "item_description3": "GLOVE SURGICAL LATEX SIZE 6.5 STERILE POWDER FREE BIOGEL SURGEONS",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "05060097930869",
            "manufacturer_code": "MOLN",
            "manufacturer_number": "30465",
            "san_multi_use_qty": 0,
            "contract": "1021525",
            "contract_line": 41,
            "on_hold": False,
        },
        {
            "item_number": "6112011",
            "vendor_item": "30470",
            "implantable": "false",
            "base_cost": 208.00,
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "05060097931118",
            "item_description": "GLOVE SURG BIOGEL PF 7.0",
            "item_description2": "CA200/BX50/PR1",
            "item_description3": "GLOVE SURGICAL LATEX SIZE 7 STERILE POWDER FREE BIOGEL SURGEONS",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "05060097930876",
            "manufacturer_code": "MOLN",
            "manufacturer_number": "30470",
            "san_multi_use_qty": 0,
            "contract": "1021503",
            "contract_line": 3,
            "on_hold": False,
        },
        {
            "item_number": "6112107",
            "vendor_item": "6112107",
            "implantable": "false",
            "base_cost": 71.40,
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "00732094178258",
            "item_description": "BULB OTO HALOGEN 3.5V",
            "item_description2": "BX6/EA1",
            "item_description3": "LAMP HALOGEN 3.5V W0.25XH0.75IN D0.25IN",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00732094025163",
            "manufacturer_code": "WECL",
            "manufacturer_number": "03100-U6",
            "san_multi_use_qty": 0,
            "contract": "1021882",
            "contract_line": 17,
            "on_hold": False,
        },
        {
            "item_number": "6112160",
            "vendor_item": "8888570556",
            "implantable": "false",
            "base_cost": 104.38,
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "20884521050850",
            "item_description": "CATH THORACIC ARGYLE ST 32FR",
            "item_description2": "CA10/EA1",
            "item_description3": "CATHETER THORACIC 32FR L20IN STRAIGHT PVC THERMOSENSITIVE DISPOSABLE ARGYLE",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "10884521050853",
            "manufacturer_code": "CARD",
            "manufacturer_number": "8888570556",
            "san_multi_use_qty": 0,
            "contract": "1022692",
            "contract_line": 1141,
            "on_hold": False,
        },
        {
            "item_number": "6112164",
            "vendor_item": "0070430",
            "implantable": "false",
            "base_cost": 4.50,
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00801741090752",
            "item_description": "DRN SIL HBLS FLAT FULLPERF21FR",
            "item_description2": "BX10/EA1",
            "item_description3": "DRAIN SURGICAL W7MMXL20CM SILICONE HUBLESS FLAT FULL PERFORATION RADIOPAQUE STRIPE FOR XRAY DETECTION",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "BARD",
            "manufacturer_number": "0070430",
            "san_multi_use_qty": 0,
            "contract": "1021202",
            "contract_line": 12,
            "on_hold": False,
        },
        {
            "item_number": "6112165",
            "vendor_item": "0034760",
            "implantable": "false",
            "base_cost": 34.40,
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "10801741049184",
            "item_description": "DRN WND TROC SS MD 1/8IN",
            "item_description2": "CA10/EA1",
            "item_description3": "TROCAR SURGICAL DIA1/8IN FOR WOUND DRAINAGE PROCEDURE",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741049187",
            "manufacturer_code": "BARD",
            "manufacturer_number": "0034760",
            "san_multi_use_qty": 0,
            "contract": "1021202",
            "contract_line": 13,
            "on_hold": False,
        },
        {
            "item_number": "6112170",
            "vendor_item": "072186",
            "implantable": "false",
            "base_cost": 120.80,
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "10801741049689",
            "item_description": "DRN CH RD FULL FLUTE 10FR",
            "item_description2": "CA10/EA1",
            "item_description3": "DRAIN SURGICAL 10FR X 1/8IN SILICONE ROUND CLOSED WOUND SUCTION CHANNEL FULL FLUTED RADIOPAQUE",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741049682",
            "manufacturer_code": "BARD",
            "manufacturer_number": "072186",
            "san_multi_use_qty": 0,
            "contract": "1021202",
            "contract_line": 17,
            "on_hold": False,
        },
        {
            "item_number": "6112174",
            "vendor_item": "6112174",
            "implantable": "false",
            "base_cost": 45.00,
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "10801741090766",
            "item_description": "DRN SIL HBLS FLAT FULLPERF30FR",
            "item_description2": "BX10/EA1",
            "item_description3": "DRAIN SURGICAL W10MMXL20CM SILICONE FULL PERFORATION HUBLESS FLAT",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741090769",
            "manufacturer_code": "BARD",
            "manufacturer_number": "0070440",
            "san_multi_use_qty": 0,
            "contract": "1021882",
            "contract_line": 21,
            "on_hold": False,
        },
        {
            "item_number": "6112181",
            "vendor_item": "SU130-1334",
            "implantable": "false",
            "base_cost": 9.75,
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00630140034537",
            "item_description": "DRN T TB JP SIL 19FR",
            "item_description2": "CA80/BX10/EA1",
            "item_description3": "DRAIN SURGICAL 19FR X 81CM T 8CM SILICONE PERFORATED FOR HYSTERECTOMY CHOLECYSTECTOMY JACKSON-PRATT",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "CARD",
            "manufacturer_number": "SU130-1334",
            "san_multi_use_qty": 0,
            "contract": "1021114",
            "contract_line": 3,
            "on_hold": False,
        },
        {
            "item_number": "6112186",
            "vendor_item": "8888561027",
            "implantable": "false",
            "base_cost": 356.96,
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "20884521050751",
            "item_description": "DRN TROC CATH CHEST TB 12FR",
            "item_description2": "CA10/EA1",
            "item_description3": "CATHETER THORACIC 12FR L9IN DIA4MM ALUMINUM ARGYLE",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "10884521050754",
            "manufacturer_code": "CARD",
            "manufacturer_number": "8888561027",
            "san_multi_use_qty": 0,
            "contract": "1022692",
            "contract_line": 1145,
            "on_hold": False,
        },
        {
            "item_number": "6112236",
            "vendor_item": "6112236",
            "implantable": "false",
            "base_cost": 11.08,
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "00610075073009",
            "item_description": "BELT OSTOMY ADJ MD 23-43IN",
            "item_description2": "BX10/EA1",
            "item_description3": "BELT OSTOMY MD 23-43IN BEIGE REUSABLE ADAPT",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00610075114795",
            "manufacturer_code": "HOLL",
            "manufacturer_number": "7300",
            "san_multi_use_qty": 0,
            "contract": "1021882",
            "contract_line": 30,
            "on_hold": False,
        },
        {
            "item_number": "6112238",
            "vendor_item": "239618",
            "implantable": "false",
            "base_cost": 6.32,
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00610075122738",
            "item_description": "PDR ADAPT STOMA 1OZ",
            "item_description2": "EA1",
            "item_description3": "POWDER STOMA 10Z CONVENIENT PUFF BOTTLE WITH VIEWING WINDOW ADAPT",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "HOLL",
            "manufacturer_number": "7906",
            "san_multi_use_qty": 0,
            "contract": "1020342",
            "contract_line": 12,
            "on_hold": False,
        },
        {
            "item_number": "6112242",
            "vendor_item": "79300",
            "implantable": "false",
            "base_cost": 1.58,
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00610075205479",
            "item_description": "PASTE ADAPT LOW ALC 2OZ",
            "item_description2": "EA1",
            "item_description3": "PASTE SKIN BARRIER 2.1OZ RED CAP ALCOHOL ADAPT",
            "item_type_state": "Itemmast",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "HOLL",
            "manufacturer_number": "79300",
            "san_multi_use_qty": 0,
            "contract": "1020342",
            "contract_line": 96,
            "on_hold": False,
        },
    ]

    df = pd.DataFrame(rows)

    # Ensure GTIN is strictly string — preserves all leading zeros
    df["global_trade_item_number"] = df["global_trade_item_number"].astype(str)
    df["on_hold"] = df["on_hold"].astype(bool)
    df["base_cost"] = df["base_cost"].astype(float)
    df["san_multi_use_qty"] = df["san_multi_use_qty"].astype(int)
    df["contract_line"] = df["contract_line"].astype(int)

    logger.info("Loaded %d mock contract lines.", len(df))
    return df


def _fetch_fresh_data(source: str) -> pd.DataFrame:
    """Fetch fresh data directly from the active source."""
    if source == "redshift":
        return _load_from_redshift()
    elif source == "mock":
        return _load_mock_from_excel()
    else:
        raise ValueError(f"Unknown DATA_SOURCE={source!r}. Expected 'mock' or 'redshift'.")

def _load_mock_from_excel() -> pd.DataFrame:
    """Load the full 130K row mock dataset from the user's local Excel file.
    Falls back to the 20-row sample if the Excel file is missing.
    """
    excel_path = "/Users/anushkasirpurkar/Downloads/contract_line.xlsx"
    if not os.path.exists(excel_path):
        logger.warning("Excel file %s not found. Falling back to 20-row mock data.", excel_path)
        return _load_mock_data_fallback()

    logger.info("Loading full mock data from %s (this takes a moment...)", excel_path)
    df = pd.read_excel(excel_path, sheet_name='Sheet1', dtype=str)
    df = df.drop(columns=['key'], errors='ignore')

    df["global_trade_item_number"] = df["global_trade_item_number"].astype(str)
    if df["on_hold"].dtype == object:
        df["on_hold"] = df["on_hold"].astype(str).str.lower() == 'true'
    else:
        df["on_hold"] = df["on_hold"].astype(bool)
        
    df["base_cost"] = df["base_cost"].astype(float)
    df["san_multi_use_qty"] = pd.to_numeric(df["san_multi_use_qty"], errors='coerce').fillna(0).astype(int)
    df["contract_line"] = pd.to_numeric(df["contract_line"], errors='coerce').fillna(0).astype(int)

    logger.info("Loaded %d contract lines from Excel.", len(df))
    return df

# ─── Public Router ────────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner="Fetching contract data from Redshift…")
def load_contract_data() -> pd.DataFrame:
    """Load contract line data, preferring a local Parquet cache over live query.
    
    Checks if `data/cache/contract_lines.parquet` exists and is <24h old.
    If so, returns it instantly.
    Otherwise, queries Redshift (or the mock source), saves to Parquet, and returns.
    If the query fails but a stale Parquet file exists, it uses the stale file as a fallback.

    Returns:
        pd.DataFrame: Contract line records.
    """
    source = os.getenv("DATA_SOURCE", "mock").lower().strip()
    
    # 1. Check local Parquet cache
    if CACHE_PATH.exists():
        file_age_seconds = time.time() - CACHE_PATH.stat().st_mtime
        if file_age_seconds < 86400:
            logger.info("Reading contract data from local Parquet cache (age: %.1fh).", file_age_seconds / 3600)
            return pd.read_parquet(CACHE_PATH)
        else:
            logger.info("Local Parquet cache is stale (>24h). Will try to refresh from %s.", source)
    else:
        logger.info("No local Parquet cache found. Will fetch fresh data from %s.", source)
        
    # 2. Try fetching fresh data from source
    try:
        df = _fetch_fresh_data(source)
        
        # 3. Save successfully fetched data to Parquet
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(CACHE_PATH)
        logger.info("Saved fresh data to local Parquet cache.")
        return df
        
    except Exception as e:
        logger.exception("Failed to fetch fresh data from %s", source)
        if CACHE_PATH.exists():
            logger.warning("Falling back to stale local Parquet cache due to fetch failure.")
            return pd.read_parquet(CACHE_PATH)
        
        # No local cache and fetch failed -> raise
        raise RuntimeError(f"Failed to fetch data from {source} and no local cache exists.") from e
