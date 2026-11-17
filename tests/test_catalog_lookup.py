"""LookupEngine.find_by_catalog: Lawson item from a goodID catalog number."""

from __future__ import annotations

import pandas as pd

from engine import LookupEngine


def _engine(rows: list[dict]) -> LookupEngine:
    base = {
        "item_number": "", "vendor_item": None, "manufacturer_number": None,
        "manufacturer_code": None, "manufacturer_name": None,
        "global_trade_item_number": "", "low_uom_code_gtin": None,
    }
    return LookupEngine(pd.DataFrame([{**base, **r} for r in rows]))


def test_exact_match_ignores_case_and_whitespace():
    e = _engine([{"item_number": "6201939", "vendor_item": "350-2400", "global_trade_item_number": "1"}])
    assert [r["item_number"] for r in e.find_by_catalog("  350-2400 ")] == ["6201939"]


def test_punctuation_insensitive_fallback():
    e = _engine([{"item_number": "5", "vendor_item": "AB-123", "global_trade_item_number": "1"}])
    assert len(e.find_by_catalog("ab 123")) == 1


def test_matches_manufacturer_number_too():
    e = _engine([{"item_number": "7", "vendor_item": "X", "manufacturer_number": "80-1050",
                  "global_trade_item_number": "1"}])
    assert len(e.find_by_catalog("80-1050")) == 1


def test_one_candidate_per_lawson_item():
    e = _engine([
        {"item_number": "9", "vendor_item": "P1", "global_trade_item_number": "1"},
        {"item_number": "9", "vendor_item": "P1", "global_trade_item_number": "2"},
    ])
    assert len(e.find_by_catalog("P1")) == 1


def test_ambiguous_number_returns_all_candidates():
    e = _engine([
        {"item_number": "1", "vendor_item": "P1", "manufacturer_name": "ACME CORP", "global_trade_item_number": "1"},
        {"item_number": "2", "vendor_item": "P1", "manufacturer_name": "ZETA INC", "global_trade_item_number": "2"},
    ])
    assert {r["item_number"] for r in e.find_by_catalog("P1")} == {"1", "2"}


def test_company_narrows_ambiguity():
    e = _engine([
        {"item_number": "1", "vendor_item": "P1", "manufacturer_name": "ACME CORP", "global_trade_item_number": "1"},
        {"item_number": "2", "vendor_item": "P1", "manufacturer_name": "ZETA INC", "global_trade_item_number": "2"},
    ])
    assert [r["item_number"] for r in e.find_by_catalog("P1", "Acme Corporation Inc")] == ["1"]


def test_company_that_matches_nobody_keeps_all_candidates():
    e = _engine([
        {"item_number": "1", "vendor_item": "P1", "manufacturer_name": "ACME CORP", "global_trade_item_number": "1"},
        {"item_number": "2", "vendor_item": "P1", "manufacturer_name": "ZETA INC", "global_trade_item_number": "2"},
    ])
    assert len(e.find_by_catalog("P1", "Unrelated")) == 2


def test_excel_mangled_catalog_numbers_are_never_indexed():
    e = _engine([{"item_number": "1", "vendor_item": "9.89803E+11", "global_trade_item_number": "1"}])
    assert e.find_by_catalog("9.89803E+11") == []


def test_blank_and_unknown():
    e = _engine([{"item_number": "1", "vendor_item": "P1", "global_trade_item_number": "1"}])
    assert e.find_by_catalog("") == []
    assert e.find_by_catalog("NOPE") == []


def test_catalog_uoms_reports_agreement_across_rows():
    e = _engine([
        {"item_number": "1", "vendor_item": "P1", "uom_unit_of_measure": "BX", "global_trade_item_number": "1"},
        {"item_number": "1", "vendor_item": "P1", "uom_unit_of_measure": "CA", "global_trade_item_number": "2"},
        {"item_number": "2", "vendor_item": "P2", "uom_unit_of_measure": "EA", "global_trade_item_number": "3"},
    ])
    assert e.find_by_catalog("P1")[0]["catalog_uoms"] == {"BX", "CA"}
    assert e.find_by_catalog("P2")[0]["catalog_uoms"] == {"EA"}
