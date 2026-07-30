"""
data/loader.py
~~~~~~~~~~~~~~
Responsible for loading and caching the supply chain contract line dataset.

Contains two distinct blocks:
  1. PRODUCTION FABRIC BLOCK — queries the Microsoft Fabric Lakehouse SQL
     analytics endpoint over ODBC, authenticating as the signed-in Azure AD
     user (no stored credentials).
  2. LOCAL DEV MOCK BLOCK    — active by default for local development.

The public entry point `load_contract_data()` dispatches to the correct block
based on the DATA_SOURCE environment variable ("mock" | "fabric").
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).parent / "cache" / "contract_lines.parquet"

# Candidate locations for the full mock dataset, tried in order by
# _resolve_mock_dataset(). The repo-relative paths come first so a deployed
# container (Streamlit Cloud, a container image — anywhere without the
# developer's home directory) can find a committed dataset; ~/Downloads stays
# last so existing local setups keep working with no change. Set
# MOCK_DATA_PATH in .env to point somewhere else entirely.
_MOCK_DATA_DIR = Path(__file__).parent / "mock"
_MOCK_DATASET_CANDIDATES = (
    _MOCK_DATA_DIR / "contract_line.parquet",
    _MOCK_DATA_DIR / "contract_line.xlsx",
    Path.home() / "Downloads" / "contract_line.xlsx",
)

DEFAULT_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"
DEFAULT_CONTRACT_LINE_TABLE = "[Silver_Lake].[infor].[contract_line]"

# The table name is interpolated into the query rather than bound as a
# parameter — SQL does not allow object names to be parameterised. It comes
# from .env (same trust level as the connection string, not user input), but is
# pattern-checked below so a typo fails loudly instead of reaching the server.
# T-SQL allows each dotted part to be bracket-quoted (e.g. [Silver_Lake].[infor]
# .[contract_line]), which is how Fabric's own connection-string UI writes it.
_IDENT_PART = r"(?:\[[A-Za-z_][A-Za-z0-9_ ]*\]|[A-Za-z_][A-Za-z0-9_]*)"
_IDENTIFIER_RE = re.compile(rf"^{_IDENT_PART}(?:\.{_IDENT_PART}){{0,2}}$")

# Fabric lakehouse column name -> canonical name used everywhere else in the
# app (engine.LookupEngine, core.lookup, ui.components). Renaming right after
# fetch means nothing downstream needs to know the source ever changed.
#
# NOTE — "manuf_name" -> "manufacturer_number" is a positional guess, not a
# confirmed mapping: it fills the same slot the old Redshift column
# `manufacturer_number` did (which core.lookup.py labels "Brand" in the UI),
# but the lakehouse name suggests it might actually be a readable manufacturer
# name rather than a number. Confirm against real rows before trusting the
# "Brand" column in the UI.
#
# NOTE — there is no lakehouse counterpart to the old `low_uom_code_gtin`
# column. That column fed engine.LookupEngine's inner-pack/each-level barcode
# alias (see engine/lookup.py) — a worker could scan either the case barcode
# or the individual-unit barcode inside it and both resolved to the same
# contract line. Without it, only the case-level `gtin` barcode will resolve;
# an inner-pack scan will silently fall through to "Not Found". This is a
# real feature gap, not just a rename, until a source column is identified.
_LAKEHOUSE_COLUMN_MAP = {
    "item": "item_number",
    "contract_uom": "uom_unit_of_measure",
    "gtin": "global_trade_item_number",
    "description": "item_description",
    "description2": "item_description2",
    "description_long": "item_description3",
    "item_type": "item_type_state",
    "base_uom": "low_uom_code_unit_of_measure",
    "manuf_code": "manufacturer_code",
    "manuf_name": "manufacturer_number",
    "multi_use_qty": "san_multi_use_qty",
    "line": "contract_line",
    "hold": "on_hold",
}

# NOTE — the old Redshift query filtered `WHERE contract_line_state = 2`
# (active lines only). This table has no equivalent column, so this query is
# currently unfiltered — it will return every contract line, including any
# inactive/historical/discontinued ones the old filter excluded. Confirm
# whether that's intended, or whether an active-only filter needs to be added
# once the right column is known.
_SQL_TEMPLATE = """
SELECT
    item,
    vendor_item,
    implantable,
    base_cost,
    contract_uom,
    gtin,
    description,
    description2,
    description_long,
    item_type,
    base_uom,
    manuf_code,
    manuf_name,
    multi_use_qty,
    contract,
    line,
    hold
FROM {table}
"""


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTION FABRIC LAKEHOUSE BLOCK
# Requires FABRIC_SQL_ENDPOINT + FABRIC_DATABASE in .env, DATA_SOURCE=fabric,
# the `fabric` extra installed (pyodbc), and the Microsoft ODBC driver
# installed at system level. See README → "Switching to the Fabric Lakehouse".
# ─────────────────────────────────────────────────────────────────────────────
def _contract_line_query() -> str:
    """Build the contract line query against the configured lakehouse table."""
    table = os.getenv("FABRIC_TABLE", DEFAULT_CONTRACT_LINE_TABLE).strip()
    if not _IDENTIFIER_RE.match(table):
        raise ValueError(
            f"FABRIC_TABLE={table!r} is not a valid SQL object name. "
            "Expected something like 'schema.table' or 'db.schema.table'."
        )
    return _SQL_TEMPLATE.format(table=table)


def _fabric_connection_string() -> str:
    """Assemble the ODBC connection string for the Fabric SQL analytics endpoint.

    Auth is Azure AD, driven by FABRIC_AUTH:
      * ActiveDirectoryInteractive (default) — opens a browser sign-in prompt on
        the machine running this process. Fine for a locally-run Streamlit app;
        it cannot work on a headless server, since nobody is there to click.
      * ActiveDirectoryDeviceCode — prints a code to sign in with on any device.
        Use this if the browser popup can't open (headless, SSH, some Macs).
      * ActiveDirectoryDefault — reuses an existing Azure CLI / VS Code login,
        or a managed identity when deployed. No prompt at all.

    No password is ever read or stored, in any of these modes.
    """
    server = os.environ["FABRIC_SQL_ENDPOINT"]
    database = os.environ["FABRIC_DATABASE"]
    driver = os.getenv("FABRIC_ODBC_DRIVER", DEFAULT_ODBC_DRIVER)
    authentication = os.getenv("FABRIC_AUTH", "ActiveDirectoryInteractive")

    return (
        f"Driver={{{driver}}};"
        f"Server={server},1433;"
        f"Database={database};"
        f"Authentication={authentication};"
        "Encrypt=Yes;"
        "TrustServerCertificate=No;"
        "Connection Timeout=60;"
    )


@st.cache_data(ttl=86400)
def _load_from_lakehouse() -> pd.DataFrame:
    """Pull active contract lines from the Fabric Lakehouse gold layer.

    Connects to the SQL analytics endpoint as the signed-in Azure AD user,
    executes the contract line query, and returns a typed DataFrame.

    Returns:
        pd.DataFrame: Contract line records with correct column types.

    Raises:
        RuntimeError: If pyodbc or the system ODBC driver is not installed.
        pyodbc.Error: On connection or query failure.
    """
    try:
        import pyodbc  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError(
            "pyodbc is not installed. Run: pip install -e '.[fabric]'"
        ) from e

    endpoint = os.environ["FABRIC_SQL_ENDPOINT"]
    logger.info("Connecting to Fabric SQL analytics endpoint at %s", endpoint)

    try:
        conn = pyodbc.connect(_fabric_connection_string())
    except pyodbc.InterfaceError as e:
        # IM002 means the ODBC *driver* is missing — a system-level install that
        # pip cannot do for you. It is by far the most common first-run failure,
        # and the raw driver message does not say how to fix it.
        if "IM002" in str(e):
            raise RuntimeError(
                f"ODBC driver {os.getenv('FABRIC_ODBC_DRIVER', DEFAULT_ODBC_DRIVER)!r} "
                "is not installed. Install the Microsoft ODBC Driver 18 for SQL Server "
                "(see README → 'Switching to the Fabric Lakehouse'), then retry."
            ) from e
        raise

    try:
        cursor = conn.cursor()
        cursor.execute(_contract_line_query())
        columns = [col[0] for col in cursor.description]
        rows = [tuple(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    df = pd.DataFrame.from_records(rows, columns=columns)
    df = df.rename(columns=_LAKEHOUSE_COLUMN_MAP)

    # CRITICAL: GTINs are identifiers, not numbers. If the endpoint hands one
    # back as numeric, the leading zeros are already gone ("00801741030024"
    # becomes 801741030024) and every lookup for that item misses. Force to
    # string immediately after fetch.
    df["global_trade_item_number"] = df["global_trade_item_number"].astype(str)

    # on_hold may arrive as a BIT, an int, or a string depending on the column's
    # lakehouse type. Note a plain .astype(bool) would turn NULL into True.
    df["on_hold"] = _coerce_bool(df["on_hold"])

    logger.info("Loaded %d contract lines from Fabric Lakehouse.", len(df))
    return df


_TRUTHY = frozenset({"true", "1", "t", "yes", "y"})


def _coerce_bool(series: pd.Series) -> pd.Series:
    """Coerce a boolean-ish column to real bools, treating NULL/blank as False.

    on_hold reaches us as a bool, an int/BIT, or a string depending on the
    source (Excel hands back "true"/"false" text; a lakehouse BIT arrives
    numeric). Two traps this exists to avoid:

      * `.astype(bool)` on strings is always True — bool("false") is True,
        because it is a non-empty string. That silently flags every item as
        on-hold.
      * Branching on `dtype == object` to detect strings is a pandas-2 idiom.
        Under pandas 3, string columns have dtype `str`, so the check is False
        and execution falls into exactly the `.astype(bool)` trap above.

    So: dispatch on pandas' type API, never on `== object`, and compare strings
    by value.
    """
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0) != 0
    return series.astype("string").str.strip().str.lower().isin(_TRUTHY)


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL DEV MOCK BLOCK (active)
# Data sourced directly from contract_line.xlsx (Sheet1).
# Includes 5 on_hold=true items for UI warning testing and 15 active items
# across manufacturers: BARD, MOLN, CARD, CONV, WECL, HOLL.
# ─────────────────────────────────────────────────────────────────────────────
def _load_mock_data_fallback() -> pd.DataFrame:
    """Load a representative sample from the real contract_line.xlsx dataset.

    Mirrors the exact column set returned by the Fabric production query.
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
    if source == "fabric":
        return _load_from_lakehouse()
    elif source == "mock":
        return _load_mock_from_excel()
    else:
        raise ValueError(f"Unknown DATA_SOURCE={source!r}. Expected 'mock' or 'fabric'.")

def _resolve_mock_dataset() -> Path | None:
    """First existing mock dataset among the configured locations, or None.

    MOCK_DATA_PATH wins outright if set — a missing file there is a
    misconfiguration worth a loud warning, not something to silently paper
    over with a different candidate.
    """
    override = os.getenv("MOCK_DATA_PATH", "").strip()
    if override:
        override_path = Path(override).expanduser()
        if override_path.exists():
            return override_path
        logger.warning("MOCK_DATA_PATH=%s does not exist. Ignoring it.", override_path)

    return next((path for path in _MOCK_DATASET_CANDIDATES if path.exists()), None)


def _load_mock_from_excel() -> pd.DataFrame:
    """Load the full 130K row mock dataset from the first location that has it.

    Reads Parquet or Excel (dispatched on suffix) so the dataset can be
    committed as Parquet — far smaller and faster to load than the .xlsx, and
    the only practical way to ship it to a deployed container. Falls back to
    the 20-row sample when no dataset is present anywhere.
    """
    dataset_path = _resolve_mock_dataset()
    if dataset_path is None:
        logger.warning(
            "No mock dataset found in any of %s. Falling back to 20-row mock data.",
            [str(p) for p in _MOCK_DATASET_CANDIDATES],
        )
        return _load_mock_data_fallback()

    logger.info("Loading full mock data from %s (this takes a moment...)", dataset_path)
    if dataset_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(dataset_path)
    else:
        df = pd.read_excel(dataset_path, sheet_name="Sheet1", dtype=str)
    df = df.drop(columns=["key"], errors="ignore")

    df["global_trade_item_number"] = df["global_trade_item_number"].astype(str)
    df["on_hold"] = _coerce_bool(df["on_hold"])
    df["base_cost"] = df["base_cost"].astype(float)
    df["san_multi_use_qty"] = (
        pd.to_numeric(df["san_multi_use_qty"], errors="coerce").fillna(0).astype(int)
    )
    df["contract_line"] = (
        pd.to_numeric(df["contract_line"], errors="coerce").fillna(0).astype(int)
    )

    logger.info("Loaded %d contract lines from %s.", len(df), dataset_path.name)
    return df

# ─── Public Router ────────────────────────────────────────────────────────────

@st.cache_data(ttl=86400, show_spinner="Fetching contract data…")
def load_contract_data() -> pd.DataFrame:
    """Load contract line data, preferring a local Parquet cache over live query.

    Checks if `data/cache/contract_lines.parquet` exists and is <24h old.
    If so, returns it instantly.
    Otherwise, queries the Fabric Lakehouse (or the mock source), saves to Parquet,
    and returns. If the query fails but a stale Parquet file exists, it uses the
    stale file as a fallback.

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


def invalidate_data_cache() -> None:
    """Drop every layer of the data cache so the next load fetches fresh.

    Three layers stand between a scan and the real data, and all three must be
    cleared together or a "refresh" silently keeps serving old rows:

      1. The on-disk Parquet file (CACHE_PATH) — load_contract_data() treats it
         as fresh for 24h based purely on its mtime, so it's deleted rather than
         just left for the age check to reject.
      2. load_contract_data()'s own @st.cache_data memoization — cleared so the
         function body actually runs again instead of returning its last result.
      3. _load_from_lakehouse()'s @st.cache_data memoization — a second, inner
         cache on the Fabric path specifically. Clearing only #2 would re-run
         the router but still hit this cache and get the old lakehouse rows.

    Callers on the mock path only need #1/#2 (the mock loader isn't cached),
    but clearing all three unconditionally keeps this safe regardless of
    DATA_SOURCE, including after a future switch from mock to fabric.

    Note: this does NOT clear engine.get_lookup_engine()'s @st.cache_resource —
    that is a 4th, separate cache the caller (core.admin.refresh_now) must also
    clear, since data/ has no dependency on core/.
    """
    CACHE_PATH.unlink(missing_ok=True)
    load_contract_data.clear()
    _load_from_lakehouse.clear()
