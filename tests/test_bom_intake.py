"""Priority 1: predictable BOM intake (CSV/XLSX, mapping, flags, corrections).

All inputs are synthetic. Nothing here calls a supplier or touches real BOMs.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook
from starlette.testclient import TestClient

from apps.api.bom_validation import validation_preview
from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.synthetic_analyze import analyze_upload, parse_bom_bytes
from apps.api.workspace_store import reset_store_for_tests
from src.bom_intake import BomIntakeError, parse_intake
from tests.fixtures.sandbox_auth_accounts import (
    SANDBOX_SEED_USERS,
    SMOKE_EMAIL,
    SMOKE_PASSWORD,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bom_intake"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def issue_codes(result) -> set[str]:
    return {i["code"] for i in result.file_issues} | {
        i["code"] for row in result.rows for i in row.issues
    }


def row_codes(row) -> set[str]:
    return {i["code"] for i in row.issues}


def xlsx_bytes(rows: list[list], sheet: str = "BOM") -> bytes:
    workbook = Workbook()
    sheet_ws = workbook.active
    sheet_ws.title = sheet
    for row in rows:
        sheet_ws.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Vendor exports
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "filename,profile,mpn_header,qty_header,supplier_sku_header",
    [
        ("digikey_bom_manager.csv", "digikey", "Manufacturer Part Number", "Quantity", "Digi-Key Part Number"),
        ("mouser_project.csv", "mouser", "Mfr. No:", "Order Qty.", "Mouser No:"),
        ("newark_bom.csv", "newark", "Manufacturer Part Number", "Quantity", "Newark Part Number"),
    ],
)
def test_vendor_exports_map_without_user_input(filename, profile, mpn_header, qty_header, supplier_sku_header):
    result = parse_intake(filename, fixture_bytes(filename))
    assert result.can_analyze
    assert result.profile["id"] == profile
    by_source = {c.source: result.assigned.get(c.index) for c in result.columns}
    assert by_source[mpn_header] == "mpn"
    assert by_source[qty_header] == "quantity"
    assert by_source[supplier_sku_header] == "supplier_part_number"
    assert by_source.get("Manufacturer", by_source.get("Mfr. Name", by_source.get("Manufacturer Name"))) == "manufacturer"
    frame = result.dataframe()
    assert list(frame["mpn"]) == ["RC0603FR-0710KL", "GRM188R71H104KA93D", "LM358DR"]
    assert list(frame["quantity"]) == [10, 4, 1]
    # The distributor order code is kept for reference but is never the MPN.
    assert not set(frame["mpn"]) & {"311-10.0KHRCT-ND", "12R3456", "603-RC0603FR-0710KL"}


def test_vendor_price_and_stock_columns_are_not_used_or_stored():
    result = parse_intake("digikey_bom_manager.csv", fixture_bytes("digikey_bom_manager.csv"))
    unused = {c.source for c in result.columns if result.assigned.get(c.index) is None}
    assert {"Quantity Available", "Unit Price", "Extended Price"} <= unused
    frame = result.dataframe()
    assert not {"Quantity Available", "Unit Price", "Extended Price"} & set(frame.columns)
    stored = json.dumps(result.source_rows_by_part and [v for v in result.source_rows_by_part().values()])
    assert "500000" not in stored and "0.10" not in stored


def test_raw_value_is_preserved_beside_normalized_value():
    payload = b"MPN,Quantity,Manufacturer\n  lm358dr  ,\" 4 \",  Texas   Instruments \n"
    result = parse_intake("raw.csv", payload)
    row = result.rows[0]
    assert row.raw["mpn"] == "  lm358dr  "
    assert row.raw["quantity"] == " 4 "
    assert row.normalized["mpn"] == "lm358dr"
    assert row.normalized["quantity"] == 4
    assert row.normalized["manufacturer"] == "Texas Instruments"
    assert "mpn_trimmed" in row_codes(row)
    preview_row = result.preview()["rows"][0]
    assert preview_row["raw"]["quantity"] == " 4 " and preview_row["normalized"]["quantity"] == 4


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------
def test_xlsx_with_title_rows_numeric_cells_and_row_numbers():
    payload = xlsx_bytes(
        [
            ["Synthetic Acme Board BOM"],
            [],
            ["Manufacturer Part Number", "Quantity", "Manufacturer"],
            ["LM358DR", 2, "TI"],
            ["NE555P", 3.0, "TI"],
        ]
    )
    result = parse_intake("board.xlsx", payload)
    assert result.can_analyze
    assert result.header_row == 2
    assert "header_row_offset" in {i["code"] for i in result.file_issues}
    assert [r.row_number for r in result.rows] == [4, 5]
    assert [r.normalized["quantity"] for r in result.rows] == [2, 3]
    assert result.rows[1].raw["quantity"] == "3"  # 3.0 is shown as written, not as 3.0000


def test_xlsx_fractional_quantity_is_flagged_not_rounded():
    payload = xlsx_bytes([["MPN", "Qty"], ["LM358DR", 2.5]])
    result = parse_intake("frac.xlsx", payload)
    assert not result.can_analyze
    assert "quantity_not_whole" in row_codes(result.rows[0])
    assert result.rows[0].normalized["quantity"] is None


def test_scientific_notation_mpn_is_flagged_as_possible_spreadsheet_conversion():
    for result in (
        parse_intake("num.xlsx", xlsx_bytes([["MPN", "Qty"], ["1.2345E+11", 2]])),
        parse_intake("num.csv", b"MPN,Qty\n1.2345E+11,2\n"),
    ):
        assert "mpn_numeric_conversion" in row_codes(result.rows[0])
        assert result.rows[0].normalized["mpn"] == "1.2345E+11"  # kept as written


def test_plain_numeric_mpn_cell_is_kept_exactly_and_not_guessed_at():
    result = parse_intake("num.xlsx", xlsx_bytes([["MPN", "Qty"], [1234567, 2]]))
    assert result.rows[0].normalized["mpn"] == "1234567"
    assert "mpn_numeric_conversion" not in row_codes(result.rows[0])


def test_vendor_header_xlsx_matches_csv_result():
    csv_result = parse_intake("mouser.csv", fixture_bytes("mouser_project.csv"))
    rows = [[c.source for c in csv_result.columns]] + [r.cells for r in csv_result.rows]
    xlsx_result = parse_intake("mouser.xlsx", xlsx_bytes(rows))
    assert xlsx_result.profile["id"] == "mouser"
    assert xlsx_result.dataframe().equals(csv_result.dataframe())


@pytest.mark.parametrize(
    "filename,payload,fragment",
    [
        ("legacy.xls", b"\xd0\xcf\x11\xe0 not really", ".xls"),
        ("bom.xlsx", b"this is not a workbook", "not a valid XLSX"),
        ("bom.pdf", b"%PDF-1.4", "Unsupported file type"),
        ("empty.csv", b"", "Empty file"),
    ],
)
def test_unsupported_or_unreadable_files_fail_clearly(filename, payload, fragment):
    result = parse_intake(filename, payload)
    assert not result.can_analyze
    assert any(fragment in line for line in result.preview()["errors"])


def test_header_only_file_has_no_part_rows():
    result = parse_intake("h.csv", b"MPN,Quantity\n")
    assert not result.can_analyze
    assert any("no part rows" in e or "no data" in e for e in result.preview()["errors"])


def test_csv_semicolon_delimiter_and_utf8_bom_and_latin1():
    semicolon = parse_intake("s.csv", b"MPN;Quantity;Manufacturer\nLM358DR;2;TI\n")
    assert semicolon.can_analyze and semicolon.rows[0].normalized["quantity"] == 2
    bom = parse_intake("b.csv", "\ufeffMPN,Quantity\nLM358DR,2\n".encode("utf-8"))
    assert bom.can_analyze and bom.columns[0].source == "MPN"
    latin1 = parse_intake("l.csv", "MPN,Quantity,Manufacturer\nLM358DR,2,Société\n".encode("latin-1"))
    assert latin1.can_analyze
    assert latin1.rows[0].normalized["manufacturer"] == "Société"
    assert any(i["code"] == "encoding_fallback" for i in latin1.file_issues)


# ---------------------------------------------------------------------------
# Required / recommended / supplier-specific fields
# ---------------------------------------------------------------------------
def test_missing_quantity_column_blocks_analysis():
    result = parse_intake("q.csv", fixture_bytes("missing_quantity_column.csv"))
    assert not result.can_analyze
    assert "mapping_required_quantity" in issue_codes(result)
    assert result.preview()["missing_required"] == ["quantity"]


def test_missing_part_number_column_blocks_analysis():
    result = parse_intake("p.csv", fixture_bytes("missing_part_number_column.csv"))
    assert not result.can_analyze
    assert "mapping_required_mpn" in issue_codes(result)
    assert result.preview()["missing_required"] == ["mpn"]


def test_user_can_map_a_missing_column_and_proceed():
    payload = b"Item,Count,Maker\nLM358DR,2,TI\n"
    blocked = parse_intake("m.csv", payload)
    assert not blocked.can_analyze
    fixed = parse_intake("m.csv", payload, column_mapping={"0": "mpn", "1": "quantity", "2": "manufacturer"})
    assert fixed.can_analyze
    assert fixed.mapping_source == "user"
    assert list(fixed.dataframe()["mpn"]) == ["LM358DR"]


def test_manufacturer_is_recommended_not_required():
    no_column = parse_intake("n.csv", b"MPN,Quantity\nLM358DR,2\n")
    assert no_column.can_analyze
    assert "manufacturer_column_missing" in {i["code"] for i in no_column.file_issues}
    assert all(i["severity"] == "warning" for i in no_column.file_issues if i["code"] == "manufacturer_column_missing")
    blank = parse_intake("n.csv", b"MPN,Quantity,Manufacturer\nLM358DR,2,\nNE555P,1,TI\n")
    assert blank.can_analyze
    assert "missing_manufacturer" in row_codes(blank.rows[0])
    assert blank.rows[0].has_warning and not blank.rows[0].has_error


def test_supplier_is_not_required_by_default():
    result = parse_intake("s.csv", b"MPN,Quantity,Manufacturer\nLM358DR,2,TI\n")
    assert result.can_analyze
    assert "supplier_column_required" not in issue_codes(result)


def test_supplier_is_required_for_supplier_specific_sourcing():
    payload = b"MPN,Quantity,Manufacturer\nLM358DR,2,TI\n"
    blocked = parse_intake("s.csv", payload, supplier_specific=True)
    assert not blocked.can_analyze
    assert "supplier_column_required" in issue_codes(blocked)

    with_default = parse_intake("s.csv", payload, supplier_specific=True, default_supplier="Acme Distribution")
    assert with_default.can_analyze
    assert with_default.rows[0].normalized["supplier"] == "Acme Distribution"
    assert "supplier_from_default" in row_codes(with_default.rows[0])  # visible, not silent

    column = b"MPN,Quantity,Supplier\nLM358DR,2,Acme\nNE555P,1,\n"
    partial = parse_intake("s.csv", column, supplier_specific=True)
    assert not partial.can_analyze
    assert "missing_supplier" in row_codes(partial.rows[1])
    assert "missing_supplier" not in row_codes(partial.rows[0])


# ---------------------------------------------------------------------------
# Ambiguous headers
# ---------------------------------------------------------------------------
def test_ambiguous_quantity_headers_are_never_guessed():
    result = parse_intake("a.csv", fixture_bytes("ambiguous_headers.csv"))
    assert not result.can_analyze
    by_source = {c.source: result.assigned.get(c.index) for c in result.columns}
    assert by_source["Qty"] is None and by_source["Qty (2)"] is None
    assert "mapping_ambiguous_quantity" in issue_codes(result)
    assert "duplicate_header" in issue_codes(result)
    fixed = parse_intake("a.csv", fixture_bytes("ambiguous_headers.csv"), column_mapping={"3": "quantity"})
    assert fixed.can_analyze
    assert [r.normalized["quantity"] for r in fixed.rows] == [2, 1]
    other = parse_intake("a.csv", fixture_bytes("ambiguous_headers.csv"), column_mapping={"4": "quantity"})
    assert [r.normalized["quantity"] for r in other.rows] == [20, 10]


def test_generic_part_number_does_not_override_manufacturer_part_number():
    result = parse_intake("a.csv", fixture_bytes("ambiguous_headers.csv"), column_mapping={"3": "quantity"})
    by_source = {c.source: result.assigned.get(c.index) for c in result.columns}
    assert by_source["Manufacturer Part Number"] == "mpn"
    assert by_source["Part Number"] is None
    assert list(result.dataframe()["mpn"]) == ["LM358DR", "NE555P"]  # not INT-0001 / INT-0002
    assert "mapping_column_not_used" in issue_codes(result)


def test_generic_part_number_alone_needs_confirmation():
    payload = fixture_bytes("generic_part_number_only.csv")
    auto = parse_intake("g.csv", payload)
    assert auto.can_analyze
    assert "mapping_needs_confirmation" in issue_codes(auto)
    confirmed = parse_intake("g.csv", payload, column_mapping={"0": "mpn", "1": "quantity", "2": "manufacturer"})
    assert "mapping_needs_confirmation" not in issue_codes(confirmed)


def test_vendor_column_is_not_silently_assigned_a_role():
    result = parse_intake("a.csv", fixture_bytes("ambiguous_headers.csv"), column_mapping={"3": "quantity"})
    vendor = next(c for c in result.columns if c.source == "Vendor")
    assert result.assigned.get(vendor.index) is None
    assert "mapping_ambiguous_optional" in issue_codes(result)
    assert "supplier" not in result.dataframe().columns


def test_contradictory_user_mapping_is_rejected_not_resolved():
    result = parse_intake(
        "c.csv",
        b"MPN,Alt MPN,Quantity\nLM358DR,NE555P,2\n",
        column_mapping={"0": "mpn", "1": "mpn", "2": "quantity"},
    )
    assert not result.can_analyze
    assert "mapping_duplicate_field" in issue_codes(result)
    assert all(not r.normalized for r in result.rows)  # raw rows only; nothing normalized by guesswork


def test_invalid_mapping_entries_are_reported():
    result = parse_intake("c.csv", b"MPN,Quantity\nLM358DR,2\n", column_mapping={"9": "mpn", "x": "quantity", "0": "bogus"})
    assert not result.can_analyze
    assert "invalid_mapping" in issue_codes(result)


# ---------------------------------------------------------------------------
# Duplicate MPNs
# ---------------------------------------------------------------------------
def test_duplicate_mpns_are_flagged_and_summed_visibly():
    result = parse_intake("d.csv", fixture_bytes("duplicate_mpns.csv"))
    assert result.can_analyze  # duplicates are a warning the user reviews, not a silent merge
    first, second = result.rows[0], result.rows[1]
    assert "duplicate_mpn" in row_codes(first) and "duplicate_mpn" in row_codes(second)
    assert "row 3" in first.issues[0]["message"] or "row 3" in " ".join(i["message"] for i in first.issues)
    frame = result.dataframe()
    quantities = dict(zip(frame["mpn"], frame["quantity"]))
    assert quantities["LM358DR"] == 5
    assert quantities["NE555P"] == 5  # case-only difference is a flagged duplicate


def test_duplicate_rows_with_different_manufacturers_are_flagged():
    result = parse_intake("d.csv", fixture_bytes("duplicate_mpns.csv"))
    assert "duplicate_conflicting_manufacturer" in row_codes(result.rows[2])


def test_differently_written_duplicates_are_flagged_and_not_merged():
    result = parse_intake("d.csv", fixture_bytes("duplicate_mpns.csv"))
    variant_row = result.rows[4]  # "LM 358DR"
    assert "possible_duplicate_variant" in row_codes(variant_row)
    assert "mpn_contains_spaces" in row_codes(variant_row)
    assert variant_row.normalized["mpn"] == "LM 358DR"  # kept as written
    assert "LM 358DR" in set(result.dataframe()["mpn"])


def test_duplicate_preview_counts_source_rows_and_parts():
    preview = validation_preview("d.csv", fixture_bytes("duplicate_mpns.csv"))
    assert preview["row_count"] == 5
    assert preview["parsed_row_count"] == 3
    assert any("combined" in w for w in preview["warnings"])


# ---------------------------------------------------------------------------
# Invalid quantities
# ---------------------------------------------------------------------------
def test_invalid_quantities_each_get_a_specific_flag_and_block_analysis():
    result = parse_intake("q.csv", fixture_bytes("bad_quantities.csv"))
    assert not result.can_analyze
    expected = {
        2: "quantity_malformed",  # abc
        3: "missing_quantity",  # blank
        4: "quantity_not_whole",  # 1.5
        5: "quantity_not_positive",  # 0
        6: "quantity_not_positive",  # -3
        7: "quantity_ambiguous_format",  # 1,000
        8: "quantity_malformed",  # 5 pcs
    }
    for row in result.rows:
        if row.row_number in expected:
            assert expected[row.row_number] in row_codes(row), row.row_number
            assert row.normalized["quantity"] is None  # never coerced to 0 or guessed
        else:
            assert row.status == "ok"
    assert result.preview()["counts"]["rows_with_errors"] == 7


def test_part_count_does_not_shrink_while_rows_await_a_fix():
    blocked = validation_preview("q.csv", fixture_bytes("bad_quantities.csv"))
    assert blocked["can_analyze"] is False
    assert blocked["row_count"] == 8
    assert blocked["unique_part_count"] == 8  # every row has a usable part number
    excluded = validation_preview("q.csv", fixture_bytes("bad_quantities.csv"), exclude_invalid_rows=True)
    assert excluded["can_analyze"] is True
    assert excluded["unique_part_count"] == 1  # only what will actually be analyzed


def test_bad_rows_are_never_dropped_unless_the_user_chooses():
    with pytest.raises(BomIntakeError) as excinfo:
        parse_bom_bytes("q.csv", fixture_bytes("bad_quantities.csv"))
    assert excinfo.value.preview["can_analyze"] is False
    chosen = parse_intake("q.csv", fixture_bytes("bad_quantities.csv"), exclude_invalid_rows=True)
    assert chosen.can_analyze
    assert list(chosen.dataframe()["mpn"]) == ["CD4017BE"]
    record = chosen.excluded_rows_record()
    assert [r["row_number"] for r in record] == [2, 3, 4, 5, 6, 7, 8]
    assert record[0]["raw"]["quantity"] == "abc" and record[0]["reasons"]
    assert any(i["code"] == "rows_excluded" for i in chosen.file_issues)


def test_missing_part_number_on_a_row_is_an_error():
    result = parse_intake("m.csv", b"MPN,Quantity\n,3\nTBD,1\nLM358DR,2\n")
    assert "missing_mpn" in row_codes(result.rows[0])
    assert "placeholder_mpn" in row_codes(result.rows[1])
    assert not result.can_analyze


def test_distributor_code_in_mpn_column_is_flagged():
    result = parse_intake("m.csv", b"MPN,Quantity\n296-1177-1-ND,3\n")
    assert "mpn_supplier_sku" in row_codes(result.rows[0])


def test_huge_quantity_is_flagged_not_changed():
    result = parse_intake("m.csv", b"MPN,Quantity\nLM358DR,5000000\n")
    assert "quantity_large" in row_codes(result.rows[0])
    assert result.rows[0].normalized["quantity"] == 5_000_000


def test_reference_designator_count_mismatch_is_flagged():
    result = parse_intake("r.csv", b"MPN,Quantity,Reference Designator\nLM358DR,3,\"U1, U2\"\n")
    assert "refdes_quantity_mismatch" in row_codes(result.rows[0])


# ---------------------------------------------------------------------------
# Row corrections
# ---------------------------------------------------------------------------
def test_row_correction_keeps_original_and_is_recorded():
    result = parse_intake(
        "q.csv",
        fixture_bytes("bad_quantities.csv"),
        row_corrections={"2": {"quantity": "4"}, "3": {"quantity": "1"}},
        exclude_invalid_rows=True,
    )
    row = result.rows[0]
    assert row.raw["quantity"] == "abc"
    assert row.normalized["quantity"] == 4
    assert row.corrections == {"quantity": {"original": "abc", "corrected": "4"}}
    assert "value_corrected" in row_codes(row)
    assert not row.has_error
    record = result.intake_record()
    assert {"row_number": 2, "field": "quantity", "original": "abc", "corrected": "4"} in record["corrections"]
    assert dict(zip(result.dataframe()["mpn"], result.dataframe()["quantity"]))["LM358DR"] == 4


def test_correcting_every_bad_row_allows_analysis_without_exclusions():
    corrections = {
        "2": {"quantity": "2"},
        "3": {"quantity": "1"},
        "4": {"quantity": "2"},
        "5": {"quantity": "1"},
        "6": {"quantity": "3"},
        "7": {"quantity": "1000"},
        "8": {"quantity": "5"},
    }
    result = parse_intake("q.csv", fixture_bytes("bad_quantities.csv"), row_corrections=corrections)
    assert result.can_analyze
    assert result.excluded_rows_record() == []
    assert len(result.dataframe().index) == 8


def test_correct_part_number_and_manufacturer():
    result = parse_intake(
        "c.csv",
        b"MPN,Quantity,Manufacturer\n,2,\nLM358DR,1,TI\n",
        row_corrections={"2": {"mpn": "NE555P", "manufacturer": "Texas Instruments"}},
    )
    assert result.can_analyze
    assert result.rows[0].raw["mpn"] == ""
    assert result.rows[0].normalized["mpn"] == "NE555P"
    assert result.rows[0].normalized["manufacturer"] == "Texas Instruments"


def test_a_correction_that_does_not_change_the_value_is_not_recorded():
    result = parse_intake("c.csv", b"MPN,Quantity\nLM358DR,2\n", row_corrections={"2": {"quantity": "2"}})
    assert result.rows[0].corrections == {}


def test_invalid_corrections_are_reported_not_ignored():
    result = parse_intake(
        "c.csv",
        b"MPN,Quantity\nLM358DR,2\n",
        row_corrections={"2": {"mpn_key": "X"}, "99": {"quantity": "1"}, "abc": {"quantity": "1"}},
    )
    codes = {i["code"] for i in result.file_issues}
    assert "invalid_correction" in codes
    assert "correction_row_not_found" in codes
    assert not result.can_analyze  # invalid correction is an error the user must resolve


def test_a_corrected_value_is_still_checked():
    result = parse_intake("c.csv", b"MPN,Quantity\nLM358DR,2\n", row_corrections={"2": {"quantity": "two"}})
    assert not result.can_analyze
    assert "quantity_malformed" in row_codes(result.rows[0])


# ---------------------------------------------------------------------------
# Analysis keeps provenance
# ---------------------------------------------------------------------------
@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    reset_store_for_tests(tmp_path / "store.json")


def test_saved_report_keeps_raw_beside_normalized_and_the_mapping(store):
    report = analyze_upload(
        filename="d.csv",
        payload=fixture_bytes("duplicate_mpns.csv"),
        workspace_id="ws-intake",
        analysis_mode="synthetic-preview",
    )
    assert report["persisted"] is True
    parts = {p["mpn"]: p for p in report["parts"]}
    lm358 = parts["LM358DR"]
    assert [r["raw"]["quantity"] for r in lm358["source_rows"]] == ["2", "3"]
    assert [r["normalized"]["quantity"] for r in lm358["source_rows"]] == [2, 3]
    assert lm358["quantity"] == 5
    intake = report["intake"]
    assert intake["format"] == "csv"
    assert intake["mapping_source"] == "auto"
    assert {m["field"] for m in intake["mapping"]} >= {"mpn", "quantity", "manufacturer"}
    assert any(item["code"] == "duplicate_mpn" for item in intake["issue_summary"])
    json.dumps(report, allow_nan=False)


def test_saved_report_records_corrections_and_excluded_rows(store):
    report = analyze_upload(
        filename="q.csv",
        payload=fixture_bytes("bad_quantities.csv"),
        workspace_id="ws-intake",
        analysis_mode="synthetic-preview",
        row_corrections={"2": {"quantity": "4"}},
        exclude_invalid_rows=True,
    )
    intake = report["intake"]
    assert [c["row_number"] for c in intake["corrections"]] == [2]
    assert [r["row_number"] for r in intake["rows_excluded"]] == [3, 4, 5, 6, 7, 8]
    assert intake["rows_excluded"][0]["raw"]["quantity"] == ""
    assert {p["mpn"] for p in report["parts"]} == {"LM358DR", "CD4017BE"}


def test_analyze_upload_refuses_unresolved_errors_and_saves_nothing(store):
    with pytest.raises(BomIntakeError) as excinfo:
        analyze_upload(
            filename="q.csv",
            payload=fixture_bytes("bad_quantities.csv"),
            workspace_id="ws-intake",
            analysis_mode="synthetic-preview",
        )
    assert excinfo.value.code == "bom_validation_failed"
    from apps.api.workspace_store import get_store

    assert get_store().list_reports(workspace_id="ws-intake") == []


def test_xlsx_analysis_end_to_end(store):
    payload = xlsx_bytes(
        [
            ["Mouser No:", "Mfr. No:", "Order Qty.", "Mfr. Name"],
            ["595-LM358DR", "LM358DR", 2, "TI"],
            ["595-NE555P", "NE555P", 1, "TI"],
        ]
    )
    report = analyze_upload(
        filename="mouser.xlsx",
        payload=payload,
        workspace_id="ws-intake",
        analysis_mode="synthetic-preview",
    )
    assert report["total_parts"] == 2
    assert report["intake"]["format"] == "xlsx"
    assert report["intake"]["supplier_profile"]["id"] == "mouser"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CADIVOR_SANDBOX_AUTH_SECRET", "test-sandbox-auth-secret-key")
    monkeypatch.setenv("CADIVOR_ALLOW_EPHEMERAL_FILE_STORE", "1")
    monkeypatch.setenv("CADIVOR_ALLOW_SANDBOX_JWT", "1")
    monkeypatch.delenv("CADIVOR_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CADIVOR_FORCE_PRODUCTION_AUTH", raising=False)
    reset_store_for_tests(tmp_path / "store.json")
    reset_auth_store_for_tests(tmp_path / "auth.json", accounts=SANDBOX_SEED_USERS)
    from apps.api import synthetic_analyze as sa

    sa._REPORTS.clear()
    client = TestClient(app)
    login = client.post("/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD})
    assert login.status_code == 200
    return client, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_api_validate_returns_mapping_and_raw_beside_normalized_rows(api):
    client, headers = api
    response = client.post(
        "/boms/validate",
        headers=headers,
        files={"file": ("mouser_project.csv", fixture_bytes("mouser_project.csv"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_analyze"] is True
    assert body["supplier_profile"]["id"] == "mouser"
    assert {c["assigned_field"] for c in body["columns"]} >= {"mpn", "quantity", "manufacturer"}
    first = body["rows"][0]
    assert first["raw"]["mpn"] == "RC0603FR-0710KL" and first["normalized"]["quantity"] == 10
    assert {f["id"] for f in body["fields"]} >= {"mpn", "quantity", "manufacturer", "supplier"}


def test_api_validate_accepts_xlsx(api):
    client, headers = api
    payload = xlsx_bytes([["MPN", "Quantity"], ["LM358DR", 2]])
    response = client.post(
        "/boms/validate",
        headers=headers,
        files={
            "file": (
                "b.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["can_analyze"] is True
    assert response.json()["format"] == "xlsx"


def test_api_ambiguous_headers_block_analyze_until_user_maps(api):
    client, headers = api
    files = lambda: {"file": ("ambiguous_headers.csv", fixture_bytes("ambiguous_headers.csv"), "text/csv")}  # noqa: E731
    blocked = client.post("/boms/analyze", headers=headers, files=files())
    assert blocked.status_code == 400
    assert blocked.json()["code"] == "bom_validation_failed"
    assert blocked.json()["validation"]["missing_required"] == ["quantity"]
    ok = client.post(
        "/boms/analyze",
        headers=headers,
        files=files(),
        data={"column_mapping": json.dumps({"3": "quantity"})},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["total_parts"] == 2


def test_api_analyze_applies_corrections_and_exclusions_and_records_them(api):
    client, headers = api
    response = client.post(
        "/boms/analyze",
        headers=headers,
        files={"file": ("bad_quantities.csv", fixture_bytes("bad_quantities.csv"), "text/csv")},
        data={
            "row_corrections": json.dumps({"2": {"quantity": "4"}}),
            "exclude_invalid_rows": "true",
        },
    )
    assert response.status_code == 200, response.text
    saved = client.get(f"/reports/{response.json()['analysis_id']}", headers=headers).json()
    assert {p["mpn"] for p in saved["parts"]} == {"LM358DR", "CD4017BE"}
    assert saved["intake"]["corrections"][0]["original"] == "abc"
    assert len(saved["intake"]["rows_excluded"]) == 6


def test_api_rejects_malformed_option_json(api):
    client, headers = api
    for field in ("column_mapping", "row_corrections"):
        response = client.post(
            "/boms/validate",
            headers=headers,
            files={"file": ("a.csv", b"MPN,Quantity\nLM358DR,2\n", "text/csv")},
            data={field: "{not json"},
        )
        assert response.status_code == 400, field
        assert response.json()["code"] in {"invalid_column_mapping", "invalid_row_corrections"}


def test_api_supplier_specific_option(api):
    client, headers = api
    payload = b"MPN,Quantity,Manufacturer\nLM358DR,2,TI\n"
    blocked = client.post(
        "/boms/validate",
        headers=headers,
        files={"file": ("a.csv", payload, "text/csv")},
        data={"supplier_specific": "true"},
    )
    assert blocked.json()["can_analyze"] is False
    allowed = client.post(
        "/boms/validate",
        headers=headers,
        files={"file": ("a.csv", payload, "text/csv")},
        data={"supplier_specific": "true", "default_supplier": "Acme Distribution"},
    )
    assert allowed.json()["can_analyze"] is True
    plain = client.post("/boms/validate", headers=headers, files={"file": ("a.csv", payload, "text/csv")})
    assert plain.json()["can_analyze"] is True


def test_api_validate_has_no_analysis_side_effects(api):
    client, headers = api
    from apps.api import synthetic_analyze as sa

    before = set(sa._REPORTS)
    client.post(
        "/boms/validate",
        headers=headers,
        files={"file": ("bad_quantities.csv", fixture_bytes("bad_quantities.csv"), "text/csv")},
        data={"row_corrections": json.dumps({"2": {"quantity": "4"}})},
    )
    assert set(sa._REPORTS) == before
