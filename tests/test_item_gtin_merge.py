"""Tests for data.loader._merge_item_gtin: item_gtin barcodes as a pre-API fallback."""

from __future__ import annotations

import pandas as pd

import data.loader as loader
from engine import LookupEngine


def _contract(rows: list[dict]) -> pd.DataFrame:
    base = {
        "item_number": "",
        "vendor_item": None,
        "manufacturer_number": None,
        "manufacturer_code": None,
        "manufacturer_name": None,
        "item_description": None,
        "uom_unit_of_measure": None,
        "low_uom_code_unit_of_measure": None,
        "global_trade_item_number": "",
        "low_uom_code_gtin": None,
        "on_hold": False,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def _item_gtin(rows: list[dict]) -> pd.DataFrame:
    base = {
        "item": "", "description_short": None, "manuf_code": None,
        "manuf_item": None, "uom": None, "gtin": "", "gtin_type": "Itemmaster",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def test_missing_barcode_resolves_to_lawson_item_with_contract_details():
    contract = _contract([{
        "item_number": "6294144", "vendor_item": "OTHER", "manufacturer_name": "TERUMO MEDICAL CORPORATION",
        "item_description": "GLIDESHEATH SLENDER", "uom_unit_of_measure": "EA",
        "global_trade_item_number": "00389701099999",
    }])
    ig = _item_gtin([{
        "item": "6294144", "manuf_item": "80-1050", "uom": "EA", "gtin": "00389701012049",
    }])

    engine = LookupEngine(loader._merge_item_gtin(contract, ig))
    hit = engine.search("00389701012049")

    assert hit is not None
    assert hit["item_number"] == "6294144"  # Lawson ID
    assert hit["vendor_item"] == "80-1050"  # shown as Item, same as the API path
    assert hit["manufacturer_number"] == "80-1050"
    assert hit["manufacturer_name"] == "TERUMO MEDICAL CORPORATION"  # from the contract line
    assert hit["gtin_source"] == "item_gtin"


def test_gtin_already_in_contract_is_untouched():
    contract = _contract([{
        "item_number": "1", "vendor_item": "V1", "global_trade_item_number": "00000000000017",
    }])
    ig = _item_gtin([{"item": "2", "manuf_item": "X", "gtin": "00000000000017"}])

    merged = loader._merge_item_gtin(contract, ig)

    assert len(merged) == 1
    assert LookupEngine(merged).search("00000000000017")["item_number"] == "1"


def test_inner_pack_barcode_counts_as_already_known():
    contract = _contract([{
        "item_number": "1", "global_trade_item_number": "00000000000017",
        "low_uom_code_gtin": "00000000000024",
    }])
    ig = _item_gtin([{"item": "2", "gtin": "00000000000024"}])

    assert len(loader._merge_item_gtin(contract, ig)) == 1


def test_barcode_uom_selects_the_matching_contract_line():
    contract = _contract([
        {"item_number": "5", "uom_unit_of_measure": "CA", "manufacturer_name": "ACME",
         "global_trade_item_number": "00000000000031"},
        {"item_number": "5", "uom_unit_of_measure": "EA", "manufacturer_name": "ACME",
         "global_trade_item_number": "00000000000048"},
    ])
    ig = _item_gtin([{"item": "5", "uom": "EA", "gtin": "00000000000055"}])

    hit = LookupEngine(loader._merge_item_gtin(contract, ig)).search("00000000000055")

    assert hit["uom_unit_of_measure"] == "EA"


def test_hold_flag_is_inherited_from_the_contract_line():
    contract = _contract([{
        "item_number": "7", "on_hold": True, "global_trade_item_number": "00000000000062",
    }])
    ig = _item_gtin([{"item": "7", "gtin": "00000000000079"}])

    hit = LookupEngine(loader._merge_item_gtin(contract, ig)).search("00000000000079")

    assert bool(hit["on_hold"]) is True


def test_item_without_a_contract_line_still_resolves_from_item_gtin_alone():
    contract = _contract([{"item_number": "1", "global_trade_item_number": "00000000000017"}])
    ig = _item_gtin([{
        "item": "999", "description_short": "KT SLENDER FLEX", "manuf_code": "TERM",
        "manuf_item": "80-1060", "uom": "EA", "gtin": "00389701012063",
    }])

    hit = LookupEngine(loader._merge_item_gtin(contract, ig)).search("00389701012063")

    assert hit["item_number"] == "999"
    assert hit["item_description"] == "KT SLENDER FLEX"
    assert hit["manufacturer_code"] == "TERM"
    assert bool(hit["on_hold"]) is False


def test_duplicate_item_gtin_barcode_keeps_first_row():
    contract = _contract([{"item_number": "1", "global_trade_item_number": "00000000000017"}])
    ig = _item_gtin([
        {"item": "10", "gtin": "00000000000086"},
        {"item": "11", "gtin": "00000000000086"},
    ])

    assert LookupEngine(loader._merge_item_gtin(contract, ig)).search("00000000000086")["item_number"] == "10"


def test_no_item_gtin_returns_contract_unchanged():
    contract = _contract([{"item_number": "1", "global_trade_item_number": "00000000000017"}])

    assert loader._merge_item_gtin(contract, None) is contract
    assert loader._merge_item_gtin(contract, _item_gtin([])) is contract


def test_item_gtin_query_failure_is_swallowed():
    class _Boom:
        def execute(self, *_a):
            raise RuntimeError("permission denied")

    assert loader._fetch_item_gtin(_Boom()) is None


def test_item_gtin_table_name_is_validated(monkeypatch):
    monkeypatch.setenv("FABRIC_ITEM_GTIN_TABLE", "x; DROP TABLE y")
    try:
        loader._item_gtin_query()
    except ValueError as e:
        assert "FABRIC_ITEM_GTIN_TABLE" in str(e)
    else:
        raise AssertionError("an invalid table name must be rejected")


def test_mock_item_gtin_csv_keeps_leading_zeros_and_filters_inactive(tmp_path, monkeypatch):
    f = tmp_path / "item_gtin.csv"
    f.write_text(
        "item,description_short,manuf_code,manuf_item,uom,gtin,gtin_type,active\n"
        "6294144,KT SLENDER,TERM,80-1050,EA,00389701012049,Itemmaster,1\n"
        "1,GONE,TERM,X,EA,00000000000017,Itemmaster,0\n"
    )
    monkeypatch.setenv("MOCK_ITEM_GTIN_PATH", str(f))

    ig = loader._load_mock_item_gtin()

    assert list(ig["gtin"]) == ["00389701012049"]


def test_mock_item_gtin_absent_or_malformed_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "_MOCK_ITEM_GTIN_CANDIDATES", ())
    monkeypatch.delenv("MOCK_ITEM_GTIN_PATH", raising=False)
    assert loader._load_mock_item_gtin() is None

    bad = tmp_path / "item_gtin.csv"
    bad.write_text("foo,bar\n1,2\n")
    monkeypatch.setenv("MOCK_ITEM_GTIN_PATH", str(bad))
    assert loader._load_mock_item_gtin() is None


def test_blank_base_uom_inferred_as_ea_when_item_master_has_an_ea_row():
    contract = _contract([
        {"item_number": "1", "global_trade_item_number": "00000000000017", "uom_unit_of_measure": "CA"},
        {"item_number": "2", "global_trade_item_number": "00000000000024", "uom_unit_of_measure": "CA"},
        {"item_number": "3", "global_trade_item_number": "00000000000031", "low_uom_code_unit_of_measure": "PK"},
    ])
    ig = _item_gtin([
        {"item": "1", "uom": "EA", "gtin": "00000000000048"},
        {"item": "2", "uom": "BX", "gtin": "00000000000055"},   # no EA row: leave blank
        {"item": "3", "uom": "EA", "gtin": "00000000000062"},   # source value wins
    ])
    merged = loader._merge_item_gtin(contract, ig)
    by = {r["global_trade_item_number"]: r for r in merged.to_dict("records")}
    assert by["00000000000017"]["low_uom_code_unit_of_measure"] == "EA"
    assert by["00000000000017"]["base_uom_source"] == loader.BASE_UOM_INFERRED
    assert loader._blank(by["00000000000024"]["low_uom_code_unit_of_measure"]) == ""
    assert by["00000000000031"]["low_uom_code_unit_of_measure"] == "PK"
    assert not by["00000000000031"]["base_uom_source"]


def test_inactive_item_master_rows_do_not_infer_a_base_uom():
    contract = _contract([{"item_number": "1", "global_trade_item_number": "00000000000017"}])
    ig = _item_gtin([{"item": "1", "uom": "EA", "gtin": "00000000000048", "active": "0"}])
    merged = loader._merge_item_gtin(contract, ig)
    assert loader._blank(merged.iloc[0]["low_uom_code_unit_of_measure"]) == ""


def test_item_master_catalog_number_is_searchable_even_when_its_barcode_is_known():
    contract = _contract([{
        "item_number": "1", "vendor_item": "OLD-1", "uom_unit_of_measure": "EA",
        "global_trade_item_number": "00000000000017",
    }])
    ig = _item_gtin([
        {"item": "1", "manuf_item": "0037850", "uom": "EA", "gtin": "00000000000017"},  # barcode already known
        {"item": "1", "manuf_item": "old-1", "uom": "EA", "gtin": "00000000000017"},    # already a vendor_item
    ])
    merged = loader._merge_item_gtin(contract, ig)
    engine = LookupEngine(merged)

    assert [r["item_number"] for r in engine.find_by_catalog("0037850")] == ["1"]
    assert len(merged) == 2  # one alias row only; the case-variant duplicate adds nothing
    assert engine.size == 1  # the alias has no barcode, so the GTIN index is unchanged
    assert engine.search("00000000000017")["item_number"] == "1"
