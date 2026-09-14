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
import struct
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
# NOTE — "manuf_item", not "manuf_name", is the counterpart of the old Redshift
# `manufacturer_number` (which core.lookup.py labels "Brand"). Verified against
# the retained mock dataset: manuf_item matches the old value on 100% of the
# ~400k comparable rows. `manuf_name` is a readable *company* name
# ("INTUITIVE SURGICAL INC") and is 1:1 with manuf_code ("INTU") — 2,103
# distinct values each — so it feeds "Company" under its own name. The mock
# datasets predate it and have no such column; core.lookup falls back to
# manufacturer_code there, which is why nothing downstream requires it.
#
# NOTE — "base_uom_gtin" is the lakehouse name for the old `low_uom_code_gtin`.
# It feeds engine.LookupEngine's inner-pack/each-level barcode alias (see
# engine/lookup.py) so a worker can scan either the case barcode or the
# individual-unit barcode inside it. Also verified at 100% against the mock
# dataset. Present on 14.7% of rows; where present it differs from the
# case-level `gtin` essentially always.
_LAKEHOUSE_COLUMN_MAP = {
    "item": "item_number",
    "contract_uom": "uom_unit_of_measure",
    "gtin": "global_trade_item_number",
    "base_uom_gtin": "low_uom_code_gtin",
    "description": "item_description",
    "description2": "item_description2",
    "description_long": "item_description3",
    "base_uom": "low_uom_code_unit_of_measure",
    "manuf_code": "manufacturer_code",
    "manuf_name": "manufacturer_name",
    "manuf_item": "manufacturer_number",
    "line": "contract_line",
    "hold": "on_hold",
}

# The `active` bit is the lakehouse equivalent of the old Redshift filter
# `WHERE contract_line_state = 2`. Filtering here rather than downstream keeps
# the behaviour identical to the pre-migration app: an inactive line does not
# resolve at all, so a scan of a discontinued item reports "Not Found".
# Excludes ~18.6k of 176.3k lines (10.6%).
_SQL_TEMPLATE = """
SELECT
    item,
    vendor_item,
    implantable,
    contract_uom,
    gtin,
    base_uom_gtin,
    description,
    description2,
    description_long,
    base_uom,
    manuf_code,
    manuf_name,
    manuf_item,
    contract,
    line,
    hold
FROM {table}
WHERE active = 1
"""

# Columns the lakehouse has that this app deliberately does NOT select, and
# strips if an older local dataset still carries them (see _RETIRED_COLUMNS use
# in _load_mock_from_excel):
#
#   base_cost         — unit pricing. Never displayed (core.lookup builds
#                       full_record from a fixed field list), never exported
#                       (core.export._COLUMNS), never persisted. Not selecting
#                       it is what keeps contract pricing out of process memory,
#                       out of the on-disk Parquet cache, and out of any future
#                       Neon copy of this table.
#   san_multi_use_qty — unused, and 82 distinct values across the whole table.
#   item_type_state   — unused, and effectively constant ("Itemmast").
#
# base_cost and san_multi_use_qty arrive from ODBC as Decimal objects, so
# together they were ~40MB of an 88.8MB DataFrame — about half of it, for data
# nothing reads. Dropping all three halves resident memory.
_RETIRED_COLUMNS = ("base_cost", "san_multi_use_qty", "item_type_state")


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTION FABRIC LAKEHOUSE BLOCK
# Requires FABRIC_SQL_ENDPOINT + FABRIC_DATABASE in .env, DATA_SOURCE=fabric,
# the `fabric` extra installed (pyodbc + azure-identity), and the Microsoft ODBC
# driver installed at system level. See README → "Switching to the Fabric
# Lakehouse".
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

    Deliberately carries NO `Authentication=`, `UID`, or `PWD`. Azure AD sign-in
    happens in Python (see _fabric_access_token) and the resulting token is
    attached as a connection *attribute* — supplying both is an error.
    """
    server = os.environ["FABRIC_SQL_ENDPOINT"]
    database = os.environ["FABRIC_DATABASE"]
    driver = os.getenv("FABRIC_ODBC_DRIVER", DEFAULT_ODBC_DRIVER)

    # Egress allowlist chokepoint (see core.egress): FABRIC_SQL_ENDPOINT is
    # itself one of the allowed hosts by construction, so this can't reject a
    # correctly configured endpoint — its value is catching a malformed one
    # (empty, or accidentally carrying a scheme/path/port) before it reaches
    # the driver, and keeping this connection's destination in the same
    # single audited allowlist as GUDID/Neon rather than trusted implicitly.
    from core.egress import assert_allowed_host  # noqa: PLC0415

    assert_allowed_host(server)

    return (
        f"Driver={{{driver}}};"
        f"Server={server},1433;"
        f"Database={database};"
        "Encrypt=Yes;"
        "TrustServerCertificate=No;"
        "Connection Timeout=60;"
    )


# Azure AD scope for the SQL/TDS surface of Fabric — the same scope Azure SQL
# uses, not a Fabric-specific one.
_TOKEN_SCOPE = "https://database.windows.net/.default"

# ODBC connection attribute carrying a pre-acquired AAD access token.
# Defined by the Microsoft driver; pyodbc has no symbolic name for it.
_SQL_COPT_SS_ACCESS_TOKEN = 1256

# FABRIC_AUTH accepts the azure-identity names below. The ODBC driver's own
# names are kept as aliases so existing .env files keep resolving to something
# sensible rather than failing on a value that merely *looks* right.
_AUTH_ALIASES = {
    "activedirectoryinteractive": "interactivebrowser",
    "interactive": "interactivebrowser",
    "browser": "interactivebrowser",
    "activedirectorydevicecode": "devicecode",
    "activedirectorydefault": "default",
    "activedirectoryserviceprincipal": "serviceprincipal",
}


# Where the AuthenticationRecord is kept. Sits beside the Parquet cache rather
# than in the repo — it is per-machine, per-user state, not project config.
_AUTH_RECORD_PATH = CACHE_PATH.parent / "auth_record.json"


def _read_auth_record():
    """The stored AuthenticationRecord, or None if there isn't a usable one.

    A missing or corrupt record is not an error: it just means the next sign-in
    is interactive, which is exactly the first-run path anyway.
    """
    if not _AUTH_RECORD_PATH.exists():
        return None
    try:
        from azure.identity import AuthenticationRecord  # noqa: PLC0415

        return AuthenticationRecord.deserialize(_AUTH_RECORD_PATH.read_text())
    except Exception:  # noqa: BLE001 - any failure means "re-authenticate"
        logger.warning(
            "Ignoring unreadable auth record at %s; will sign in again.",
            _AUTH_RECORD_PATH,
        )
        return None


def _write_auth_record(record) -> None:
    """Persist the AuthenticationRecord so the next run can reuse the cache."""
    try:
        _AUTH_RECORD_PATH.parent.mkdir(parents=True, exist_ok=True)
        _AUTH_RECORD_PATH.write_text(record.serialize())
    except OSError as e:
        # Losing the record costs an extra sign-in, nothing more — never fail
        # a data load over it.
        logger.warning("Could not save auth record: %s", e)


def _fabric_credential():
    """Build the azure-identity credential named by FABRIC_AUTH.

    Sign-in is done here rather than by the ODBC driver because the driver's
    browser-based modes are Windows-only. On macOS the driver accepts
    `Authentication=ActiveDirectoryInteractive` and then hangs until timeout,
    and it rejects `ActiveDirectoryDefault`/`ActiveDirectoryDeviceCode` as
    invalid values outright. azure-identity implements all of these properly on
    every platform, so it owns auth and the driver just carries the token.

    Modes:
      * devicecode (default) — prints a URL and a code to enter on any device.
        Works headless and over SSH; the prompt is logged at WARNING so it is
        visible in the terminal running Streamlit.
      * interactivebrowser — opens a real browser sign-in on this machine.
      * serviceprincipal — non-interactive, for deployment. Requires
        FABRIC_TENANT_ID, FABRIC_CLIENT_ID and FABRIC_CLIENT_SECRET.
      * default — DefaultAzureCredential: managed identity, env vars, or an
        existing `az login` session, in that order. No prompt.

    Only the serviceprincipal mode involves a stored secret.
    """
    try:
        from azure.identity import (  # noqa: PLC0415
            ClientSecretCredential,
            DefaultAzureCredential,
            DeviceCodeCredential,
            InteractiveBrowserCredential,
            TokenCachePersistenceOptions,
        )
    except ImportError as e:
        raise RuntimeError(
            "azure-identity is not installed. Run: pip install -e '.[fabric]'"
        ) from e

    raw = os.getenv("FABRIC_AUTH", "devicecode").strip()
    mode = _AUTH_ALIASES.get(raw.lower(), raw.lower())

    # Persist tokens in the OS keychain so a human is prompted about once a
    # month (refresh-token lifetime) rather than on every process start.
    # Service principal and managed identity need no cache — they can
    # re-authenticate silently.
    cache = TokenCachePersistenceOptions()
    tenant = os.getenv("FABRIC_TENANT_ID", "").strip() or "organizations"

    # The keychain cache alone is NOT enough for the interactive modes: it
    # stores the token, but a fresh credential object has no idea which account
    # to look up, so it re-prompts every process start. The AuthenticationRecord
    # is that missing pointer (home account id, tenant, username, authority) —
    # identifying data, not a credential, which is why it can sit on disk.
    record = _read_auth_record()

    if mode == "devicecode":
        return DeviceCodeCredential(
            tenant_id=tenant,
            cache_persistence_options=cache,
            authentication_record=record,
            prompt_callback=lambda uri, code, expires: logger.warning(
                "AZURE AD SIGN-IN REQUIRED: open %s and enter code %s", uri, code
            ),
        )
    if mode == "interactivebrowser":
        return InteractiveBrowserCredential(
            tenant_id=tenant,
            cache_persistence_options=cache,
            authentication_record=record,
        )
    if mode == "serviceprincipal":
        missing = [
            var
            for var in ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET")
            if not os.getenv(var, "").strip()
        ]
        if missing:
            raise RuntimeError(
                f"FABRIC_AUTH=serviceprincipal requires {', '.join(missing)} in .env."
            )
        return ClientSecretCredential(
            tenant_id=os.environ["FABRIC_TENANT_ID"],
            client_id=os.environ["FABRIC_CLIENT_ID"],
            client_secret=os.environ["FABRIC_CLIENT_SECRET"],
        )
    if mode == "default":
        return DefaultAzureCredential()

    raise ValueError(
        f"FABRIC_AUTH={raw!r} is not a supported auth mode. Expected one of: "
        "devicecode, interactivebrowser, serviceprincipal, default."
    )


def _fabric_access_token() -> bytes:
    """Acquire an Azure AD token, packed in the layout the ODBC driver expects.

    The driver wants a 4-byte little-endian length followed by the token as
    UTF-16-LE — not the bare token string.
    """
    credential = _fabric_credential()

    # First interactive sign-in on this machine: authenticate() runs the flow
    # and returns the record that makes every later run silent. Only the
    # interactive credentials define it — service principal and managed
    # identity re-authenticate silently and need no record.
    #
    # A failure here is deliberately allowed to propagate. Catching it and
    # falling through to get_token() starts a SECOND device-code flow issuing a
    # DIFFERENT code, so a user who was merely slow gets a fresh code they never
    # saw and waits out two timeouts instead of one.
    if _read_auth_record() is None and hasattr(credential, "authenticate"):
        _write_auth_record(credential.authenticate(scopes=[_TOKEN_SCOPE]))

    # Silent after the above: reads the token straight from the keychain cache.
    token = credential.get_token(_TOKEN_SCOPE)
    token_bytes = token.token.encode("UTF-16-LE")
    return struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)


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
        conn = pyodbc.connect(
            _fabric_connection_string(),
            attrs_before={_SQL_COPT_SS_ACCESS_TOKEN: _fabric_access_token()},
        )
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
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "10801741030021",
            "item_description": "DRN PEZZER PROPORTIONATE 12FR",
            "item_description2": "BX6/EA1",
            "item_description3": "CATHETER NEPHROSTOMY DRAINAGE 12FR LATEX 2 EYE PROPORTIONATE HEAD DISPOSABLE PEZZERS",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741030024",
            "manufacturer_code": "BARD",
            "manufacturer_number": "064012",
            "contract": "1020285",
            "contract_line": 8,
            "on_hold": True,
        },
        {
            "item_number": "6112213",
            "vendor_item": "0620064010",
            "implantable": "false",
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "10801741030014",
            "item_description": "DRN PEZZER PROPORTIONATE 10FR",
            "item_description2": "CA6/EA1",
            "item_description3": "CATHETER NEPHROSTOMY DRAINAGE 10FR 2 EYES PROPORTIONATE HEAD TIP WITHOUT BALLOON PEZZER",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741030017",
            "manufacturer_code": "BARD",
            "manufacturer_number": "064010",
            "contract": "1020285",
            "contract_line": 26,
            "on_hold": True,
        },
        {
            "item_number": "6114704",
            "vendor_item": "420127",
            "implantable": "false",
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "10768455118219",
            "item_description": "DRSG HYDROFBR ROPE 1X45CM",
            "item_description2": "BX5/EA1",
            "item_description3": "DRESSING HYDROCOLLOID W1XL45CM ABSORBENT WITH STRENGTHENING FIBER HYDROFIBER AQUACEL",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00768455118212",
            "manufacturer_code": "CONV",
            "manufacturer_number": "420127",
            "contract": "1020670",
            "contract_line": 3,
            "on_hold": True,
        },
        {
            "item_number": "6114753",
            "vendor_item": "1638187955",
            "implantable": "false",
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "00768455106912",
            "item_description": "DRSG DUODERM XTHN 4X4",
            "item_description2": "BX10/EA1",
            "item_description3": "DRESSING HYDROCOLLOID W4XL4IN BEIGE SQUARE VAPOR PERMEABLE OUTER FILM TRANSLUCENT BACKING FLEXIBLE CONFORMABLE DUODERM EXTRA THIN CGF",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00768455150922",
            "manufacturer_code": "CONV",
            "manufacturer_number": "187955",
            "contract": "1020669",
            "contract_line": 3,
            "on_hold": True,
        },
        {
            "item_number": "6114795",
            "vendor_item": "187660",
            "implantable": "false",
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00768455174843",
            "item_description": "DRSG DUODERM CGF 4X4",
            "item_description2": "BX5/EA1",
            "item_description3": "DRESSING HYDROCOLLOID W4XL4IN BEIGE SQUARE MOISTURE RETENTIVE DUODERM CGF",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "CONV",
            "manufacturer_number": "187660",
            "contract": "1020670",
            "contract_line": 8,
            "on_hold": True,
        },
        # ── Active items (15) — sourced from contract_line.xlsx ───────────────
        {
            "item_number": "6112009",
            "vendor_item": "6112009",
            "implantable": "false",
            "uom_unit_of_measure": "PR",
            "global_trade_item_number": "05060097930852",
            "item_description": "GLOVE SURG BIOGEL PF 6.0",
            "item_description2": "CA200/BX50/PR1",
            "item_description3": "GLOVE SURGICAL 6 BIOGEL SURGEONS LATEX STRAW POWDER FREE",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "MOLN",
            "manufacturer_number": "30460",
            "contract": "1021882",
            "contract_line": 3,
            "on_hold": False,
        },
        {
            "item_number": "6112010",
            "vendor_item": "30465",
            "implantable": "false",
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "05060097930944",
            "item_description": "GLOVE SURG BIOGEL PF 6.5",
            "item_description2": "CA200/BX50/PR1",
            "item_description3": "GLOVE SURGICAL LATEX SIZE 6.5 STERILE POWDER FREE BIOGEL SURGEONS",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "05060097930869",
            "manufacturer_code": "MOLN",
            "manufacturer_number": "30465",
            "contract": "1021525",
            "contract_line": 41,
            "on_hold": False,
        },
        {
            "item_number": "6112011",
            "vendor_item": "30470",
            "implantable": "false",
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "05060097931118",
            "item_description": "GLOVE SURG BIOGEL PF 7.0",
            "item_description2": "CA200/BX50/PR1",
            "item_description3": "GLOVE SURGICAL LATEX SIZE 7 STERILE POWDER FREE BIOGEL SURGEONS",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "05060097930876",
            "manufacturer_code": "MOLN",
            "manufacturer_number": "30470",
            "contract": "1021503",
            "contract_line": 3,
            "on_hold": False,
        },
        {
            "item_number": "6112107",
            "vendor_item": "6112107",
            "implantable": "false",
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "00732094178258",
            "item_description": "BULB OTO HALOGEN 3.5V",
            "item_description2": "BX6/EA1",
            "item_description3": "LAMP HALOGEN 3.5V W0.25XH0.75IN D0.25IN",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00732094025163",
            "manufacturer_code": "WECL",
            "manufacturer_number": "03100-U6",
            "contract": "1021882",
            "contract_line": 17,
            "on_hold": False,
        },
        {
            "item_number": "6112160",
            "vendor_item": "8888570556",
            "implantable": "false",
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "20884521050850",
            "item_description": "CATH THORACIC ARGYLE ST 32FR",
            "item_description2": "CA10/EA1",
            "item_description3": "CATHETER THORACIC 32FR L20IN STRAIGHT PVC THERMOSENSITIVE DISPOSABLE ARGYLE",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "10884521050853",
            "manufacturer_code": "CARD",
            "manufacturer_number": "8888570556",
            "contract": "1022692",
            "contract_line": 1141,
            "on_hold": False,
        },
        {
            "item_number": "6112164",
            "vendor_item": "0070430",
            "implantable": "false",
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00801741090752",
            "item_description": "DRN SIL HBLS FLAT FULLPERF21FR",
            "item_description2": "BX10/EA1",
            "item_description3": "DRAIN SURGICAL W7MMXL20CM SILICONE HUBLESS FLAT FULL PERFORATION RADIOPAQUE STRIPE FOR XRAY DETECTION",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "BARD",
            "manufacturer_number": "0070430",
            "contract": "1021202",
            "contract_line": 12,
            "on_hold": False,
        },
        {
            "item_number": "6112165",
            "vendor_item": "0034760",
            "implantable": "false",
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "10801741049184",
            "item_description": "DRN WND TROC SS MD 1/8IN",
            "item_description2": "CA10/EA1",
            "item_description3": "TROCAR SURGICAL DIA1/8IN FOR WOUND DRAINAGE PROCEDURE",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741049187",
            "manufacturer_code": "BARD",
            "manufacturer_number": "0034760",
            "contract": "1021202",
            "contract_line": 13,
            "on_hold": False,
        },
        {
            "item_number": "6112170",
            "vendor_item": "072186",
            "implantable": "false",
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "10801741049689",
            "item_description": "DRN CH RD FULL FLUTE 10FR",
            "item_description2": "CA10/EA1",
            "item_description3": "DRAIN SURGICAL 10FR X 1/8IN SILICONE ROUND CLOSED WOUND SUCTION CHANNEL FULL FLUTED RADIOPAQUE",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741049682",
            "manufacturer_code": "BARD",
            "manufacturer_number": "072186",
            "contract": "1021202",
            "contract_line": 17,
            "on_hold": False,
        },
        {
            "item_number": "6112174",
            "vendor_item": "6112174",
            "implantable": "false",
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "10801741090766",
            "item_description": "DRN SIL HBLS FLAT FULLPERF30FR",
            "item_description2": "BX10/EA1",
            "item_description3": "DRAIN SURGICAL W10MMXL20CM SILICONE FULL PERFORATION HUBLESS FLAT",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00801741090769",
            "manufacturer_code": "BARD",
            "manufacturer_number": "0070440",
            "contract": "1021882",
            "contract_line": 21,
            "on_hold": False,
        },
        {
            "item_number": "6112181",
            "vendor_item": "SU130-1334",
            "implantable": "false",
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00630140034537",
            "item_description": "DRN T TB JP SIL 19FR",
            "item_description2": "CA80/BX10/EA1",
            "item_description3": "DRAIN SURGICAL 19FR X 81CM T 8CM SILICONE PERFORATED FOR HYSTERECTOMY CHOLECYSTECTOMY JACKSON-PRATT",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "CARD",
            "manufacturer_number": "SU130-1334",
            "contract": "1021114",
            "contract_line": 3,
            "on_hold": False,
        },
        {
            "item_number": "6112186",
            "vendor_item": "8888561027",
            "implantable": "false",
            "uom_unit_of_measure": "CA",
            "global_trade_item_number": "20884521050751",
            "item_description": "DRN TROC CATH CHEST TB 12FR",
            "item_description2": "CA10/EA1",
            "item_description3": "CATHETER THORACIC 12FR L9IN DIA4MM ALUMINUM ARGYLE",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "10884521050754",
            "manufacturer_code": "CARD",
            "manufacturer_number": "8888561027",
            "contract": "1022692",
            "contract_line": 1145,
            "on_hold": False,
        },
        {
            "item_number": "6112236",
            "vendor_item": "6112236",
            "implantable": "false",
            "uom_unit_of_measure": "BX",
            "global_trade_item_number": "00610075073009",
            "item_description": "BELT OSTOMY ADJ MD 23-43IN",
            "item_description2": "BX10/EA1",
            "item_description3": "BELT OSTOMY MD 23-43IN BEIGE REUSABLE ADAPT",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": "00610075114795",
            "manufacturer_code": "HOLL",
            "manufacturer_number": "7300",
            "contract": "1021882",
            "contract_line": 30,
            "on_hold": False,
        },
        {
            "item_number": "6112238",
            "vendor_item": "239618",
            "implantable": "false",
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00610075122738",
            "item_description": "PDR ADAPT STOMA 1OZ",
            "item_description2": "EA1",
            "item_description3": "POWDER STOMA 10Z CONVENIENT PUFF BOTTLE WITH VIEWING WINDOW ADAPT",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "HOLL",
            "manufacturer_number": "7906",
            "contract": "1020342",
            "contract_line": 12,
            "on_hold": False,
        },
        {
            "item_number": "6112242",
            "vendor_item": "79300",
            "implantable": "false",
            "uom_unit_of_measure": "EA",
            "global_trade_item_number": "00610075205479",
            "item_description": "PASTE ADAPT LOW ALC 2OZ",
            "item_description2": "EA1",
            "item_description3": "PASTE SKIN BARRIER 2.1OZ RED CAP ALCOHOL ADAPT",
            "low_uom_code_unit_of_measure": None,
            "low_uom_code_gtin": None,
            "manufacturer_code": "HOLL",
            "manufacturer_number": "79300",
            "contract": "1020342",
            "contract_line": 96,
            "on_hold": False,
        },
    ]

    df = pd.DataFrame(rows)

    # Ensure GTIN is strictly string — preserves all leading zeros
    df["global_trade_item_number"] = df["global_trade_item_number"].astype(str)
    df["on_hold"] = df["on_hold"].astype(bool)
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
    # _RETIRED_COLUMNS is dropped here, not just left out of the Fabric SELECT,
    # because this path reads whatever dataset it finds — including an older
    # ~/Downloads/contract_line.xlsx that still carries base_cost. Stripping on
    # read means no local file can put pricing back into memory.
    df = df.drop(columns=["key", *_RETIRED_COLUMNS], errors="ignore")

    df["global_trade_item_number"] = df["global_trade_item_number"].astype(str)
    df["on_hold"] = _coerce_bool(df["on_hold"])
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
