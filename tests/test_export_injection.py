"""Tests that core.export.build_workbook neutralizes CSV/formula injection
payloads before they reach the .xlsx file (ASVS-AUDIT.md finding #4).

openpyxl converts a string cell value starting with "=" into a real <f>
formula element at write time (confirmed by inspecting the raw sheet XML) —
this isn't just a "CSV re-import" heuristic, so these tests assert directly
on the written XML rather than trusting a higher-level API that might mask
the behavior."""

from __future__ import annotations

import io
import zipfile

from core.export import _neutralize_formula, build_workbook

_HISTORY_ROW = {
    "time": "10:00:00",
    "source": "cache",
    "status": "Found",
    "Scan": "plain-scan",
    "Item": "x",
    "Company": "y",
    "Brand": "z",
    "Description": "d",
    "GTIN": "00000000000000",
    "GTIN UOM": "EA",
    "UOU": "-",
    "HIBCC": "-",
    "LAWSON ID": "-",
    "Lawson UOM": "-",
    "Scan Count": 1,
    "Miss Reason": "",
    "Miss Detail": "",
}


def _sheet_xml(data: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    return z.read("xl/worksheets/sheet1.xml").decode()


def test_neutralize_formula_prefixes_trigger_chars():
    for trigger in ("=1+1", "+CMD", "-1", "@SUM(1,1)", "\tping", "\rping"):
        neutralized = _neutralize_formula(trigger)
        assert neutralized.startswith("'"), trigger
        assert neutralized[1:] == trigger


def test_neutralize_formula_leaves_plain_text_alone():
    assert _neutralize_formula("normal text") == "normal text"
    assert _neutralize_formula("00801741030024") == "00801741030024"


def test_neutralize_formula_passes_through_non_strings():
    assert _neutralize_formula(42) == 42
    assert _neutralize_formula(None) is None


def test_malicious_scan_field_does_not_become_a_formula_cell():
    row = {**_HISTORY_ROW, "Scan": "=1+1", "Description": "@SUM(A1:A9)"}
    xml = _sheet_xml(build_workbook([row]))
    assert "<f>" not in xml


def test_malicious_sanford_id_and_location_do_not_become_formula_cells():
    xml = _sheet_xml(
        build_workbook(
            [_HISTORY_ROW],
            location="+CMD|' /C calc'!A0",
            sanford_id="=cmd|'/C calc'!A0",
            session_id="abc123",
        )
    )
    assert "<f>" not in xml
    assert "'=cmd" in xml  # neutralized, not stripped — still visible as text


def test_benign_export_is_unaffected():
    xml = _sheet_xml(
        build_workbook(
            [_HISTORY_ROW], location="Sioux Falls GS1", sanford_id="jdoe", session_id="abc123"
        )
    )
    assert "<f>" not in xml
    assert "Sioux Falls GS1" in xml
    assert "jdoe" in xml
