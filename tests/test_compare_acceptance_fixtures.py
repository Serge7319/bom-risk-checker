"""Acceptance B fixtures: authoritative Compare Parts property comparison cases."""
from __future__ import annotations

import pytest

from src.component_family_profiles import (
    COMPARE_LIMIT_GE,
    COMPARE_LIMIT_LE,
    COMPARE_NOMINAL,
    FieldSpec,
)
from src.datasheet_comparison import (
    _find_pdf_evidence,
    _pdf_line_is_wrong_rating_context,
    build_pdf_field_evidence,
)
from src.parametric_compare import (
    classify_rating_context,
    compare_field_values,
    parse_numeric_with_unit,
    rating_context_conflict,
)
from src.parts_compare import (
    FINDING_CATALOG_DIFFERENCE,
    FINDING_COMPATIBLE,
    FINDING_LISTING_AGREEMENT,
    FINDING_MATERIAL,
    FINDING_NEEDS_VERIFICATION,
    assess_compare_row,
    build_parts_comparison,
)
from tests.test_compare_parts import _cap, _verified_cap_datasheet

NOMINAL_V = FieldSpec(
    key="coil_voltage", label="Coil voltage", compare=COMPARE_NOMINAL, unit="V"
)
LIMIT_GE_V = FieldSpec(
    key="rated_voltage",
    label="Rated voltage",
    compare=COMPARE_LIMIT_GE,
    unit="V",
    value_role="max",
)
CAP = FieldSpec(
    key="capacitance", label="Capacitance", compare=COMPARE_NOMINAL, unit="F"
)
RES = FieldSpec(key="resistance", label="Resistance", compare=COMPARE_NOMINAL, unit="Ohm")
PITCH = FieldSpec(key="pitch", label="Pitch", compare=COMPARE_NOMINAL, unit="m")
OFFSET = FieldSpec(
    key="input_offset_mv",
    label="Input offset",
    compare=COMPARE_LIMIT_LE,
    unit="mV",
    value_role="max",
)
SUPPLY = FieldSpec(
    key="supply_voltage", label="Supply voltage", compare=COMPARE_NOMINAL, unit="V"
)


# --- known Match / known Different -------------------------------------------------

@pytest.mark.parametrize("spec", [NOMINAL_V, LIMIT_GE_V])
def test_known_match(spec):
    assert compare_field_values("50 V", "50 V", spec)[0] == "Match"


@pytest.mark.parametrize("spec", [NOMINAL_V, LIMIT_GE_V])
@pytest.mark.parametrize(
    "a,b", [("50 V", "100 V"), ("100 V", "50 V"), ("50V", "25V")]
)
def test_explicit_50v_vs_100v_is_different_never_match(spec, a, b):
    """Higher voltage is never silently a Match, even under limit-GE semantics."""
    status, note = compare_field_values(a, b, spec)
    assert status == "Different", note


def test_equal_property_nominal_50v_vs_100v_different_with_note():
    status, note = compare_field_values("50 V", "100 V", NOMINAL_V)
    assert status == "Different"
    assert "differ" in note.lower()


# --- equivalent units ---------------------------------------------------------------

@pytest.mark.parametrize(
    "spec,a,b",
    [
        (NOMINAL_V, "1000 mV", "1 V"),
        (CAP, "100 nF", "0.1 uF"),
        (CAP, "0.1uF", "100000 pF"),
        (RES, "10k", "10000 Ohm"),
        (RES, "10 kOhm", "10000 Ohm"),
        (PITCH, "2.54 mm", '0.1 in'),
        (OFFSET, "3 mV", "0.003 V"),
    ],
)
def test_equivalent_units_match(spec, a, b):
    assert compare_field_values(a, b, spec)[0] == "Match", (a, b)


def test_inch_is_scaled_not_treated_as_metres():
    value, unit = parse_numeric_with_unit('0.1 in')
    assert unit == "m"
    assert value == pytest.approx(0.00254)


@pytest.mark.parametrize(
    "spec,a,b",
    [(NOMINAL_V, "50 V", "50 A"), (NOMINAL_V, "5 V", "5 mA"), (CAP, "100 nF", "100 nH")],
)
def test_different_physical_units_are_never_the_same_property(spec, a, b):
    status, _note = compare_field_values(a, b, spec)
    assert status == "Needs data"


# --- missing values -----------------------------------------------------------------

@pytest.mark.parametrize("a,b", [("", "50 V"), ("50 V", ""), ("", ""), (None, "50 V")])
def test_missing_values_need_data(a, b):
    assert compare_field_values(a, b, NOMINAL_V)[0] == "Needs data"


# --- operating vs absolute maximum --------------------------------------------------

@pytest.mark.parametrize(
    "operating,absolute",
    [
        ("Operating supply voltage 5 V", "Absolute maximum supply voltage 5 V"),
        ("3 V to 5.5 V operating", "Absolute max 6 V"),
        ("5 V (operating)", "5 V (absolute maximum rating)"),
    ],
)
def test_operating_and_absolute_max_never_match_each_other(operating, absolute):
    for a, b in ((operating, absolute), (absolute, operating)):
        status, note = compare_field_values(a, b, SUPPLY)
        assert status == "Needs data", (a, b, status)
        assert "absolute" in note.lower()
        assert status != "Match"


def test_two_absolute_max_ratings_are_not_flagged_as_context_conflict():
    assert not rating_context_conflict(
        "Absolute maximum 36 V", "Absolute maximum 40 V"
    )
    assert not rating_context_conflict("36 V", "40 V")
    assert rating_context_conflict("Absolute maximum 36 V", "36 V")
    # Same-context bare ratings still compare normally.
    assert compare_field_values("36 V", "40 V", SUPPLY)[0] == "Different"
    assert compare_field_values("36 V", "36 V", SUPPLY)[0] == "Match"


def test_rating_context_classifier():
    assert classify_rating_context("Absolute Maximum Ratings: 36 V") == "absolute_max"
    assert classify_rating_context("Abs. max supply 36 V") == "absolute_max"
    assert classify_rating_context("Recommended operating supply 3-32 V") == "operating"
    assert classify_rating_context("50 V") == "unspecified"


def test_pdf_extraction_does_not_read_abs_max_row_as_operating_supply():
    spec = FieldSpec(
        key="supply_voltage", label="Supply voltage", compare=COMPARE_NOMINAL, unit="V"
    )
    abs_max_line = "Absolute maximum supply voltage 36 V"
    operating_line = "Supply voltage 5 V"
    assert _pdf_line_is_wrong_rating_context(spec, abs_max_line) is True
    assert _pdf_line_is_wrong_rating_context(spec, operating_line) is False

    pdf = {
        "pages": [
            {"page": 1, "text": f"{abs_max_line}\n{operating_line}\n"},
        ]
    }
    value, citation, excerpt = _find_pdf_evidence(
        pdf, ("supply voltage",), field_spec=spec
    )
    assert value == "5 V"
    assert "Absolute" not in excerpt


def test_pdf_abs_max_only_page_yields_no_operating_value():
    spec = FieldSpec(
        key="supply_voltage", label="Supply voltage", compare=COMPARE_NOMINAL, unit="V"
    )
    pdf = {"pages": [{"page": 1, "text": "Absolute maximum supply voltage 36 V\n"}]}
    value, _citation, _excerpt = _find_pdf_evidence(
        pdf, ("supply voltage",), field_spec=spec
    )
    assert value == ""


def test_build_pdf_field_evidence_abs_max_never_matches_operating_rows():
    original = {
        "pages": [{"page": 2, "text": "Rated voltage 50 V\nCapacitance 0.1 uF\n"}]
    }
    candidate = {
        "pages": [
            {
                "page": 2,
                "text": (
                    "Absolute maximum rated voltage 50 V\nCapacitance 100 nF\n"
                ),
            }
        ]
    }
    rows = build_pdf_field_evidence(original, candidate, "Capacitor")
    by_key = {row["Key"]: row for row in rows}
    assert by_key["rated_voltage"]["Status"] != "Match"
    assert by_key["rated_voltage"]["Candidate PDF value"] == "Not found"
    assert by_key["capacitance"]["Status"] == "Match"


# --- catalog / unknown evidence → not Compatible -------------------------------------

def test_catalog_only_match_is_never_compatible_for_row_or_overall():
    for source in ("DigiKey catalog", "DigiKey", "Mouser", "Supplier catalog"):
        assessment = assess_compare_row(status="Match", source_a=source, source_b=source)
        assert assessment != FINDING_COMPATIBLE, source
        assert assessment in {FINDING_LISTING_AGREEMENT, FINDING_NEEDS_VERIFICATION}

    comparison = build_parts_comparison(
        _cap(source="DigiKey", field_sources={"capacitance": "DigiKey"}),
        _cap(
            mpn="ALT-CAP",
            source="DigiKey",
            field_sources={"capacitance": "DigiKey"},
        ),
    )
    assert comparison["finding"] != FINDING_COMPATIBLE
    assert FINDING_COMPATIBLE not in {
        row.get("Assessment") for row in comparison["rows"] if row.get("Part A")
    }


def test_catalog_vs_authoritative_or_missing_match_needs_verification():
    assert (
        assess_compare_row(
            status="Match", source_a="datasheet, p. 3", source_b="DigiKey catalog"
        )
        != FINDING_COMPATIBLE
    )
    assert (
        assess_compare_row(status="Match", source_a="datasheet, p. 3", source_b="")
        == FINDING_NEEDS_VERIFICATION
    )
    assert (
        assess_compare_row(status="Match", source_a="", source_b="")
        == FINDING_NEEDS_VERIFICATION
    )


def test_catalog_only_difference_is_not_a_material_claim():
    assert (
        assess_compare_row(
            status="Different", source_a="DigiKey catalog", source_b="DigiKey catalog"
        )
        == FINDING_CATALOG_DIFFERENCE
    )
    assert (
        assess_compare_row(
            status="Different", source_a="datasheet, p. 3", source_b="datasheet, p. 4"
        )
        == FINDING_MATERIAL
    )


def test_authoritative_match_on_both_sides_can_be_compatible():
    assert (
        assess_compare_row(
            status="Match", source_a="datasheet, p. 3", source_b="datasheet, p. 4"
        )
        == FINDING_COMPATIBLE
    )


# --- manufacturer mismatch ----------------------------------------------------------

def test_manufacturer_mismatch_in_datasheet_identity_is_never_compatible():
    part_a = _cap()
    part_b = _cap(mpn="ALT-CAP")
    comparison = build_parts_comparison(
        part_a,
        part_b,
        datasheet_a=_verified_cap_datasheet(mpn=part_a["manufacturer_part_number"]),
        # Datasheet names a different manufacturer than the looked-up part.
        datasheet_b=_verified_cap_datasheet(
            mpn=part_b["manufacturer_part_number"], manufacturer="Murata"
        ),
        extract_linked_datasheets=False,
    )
    assert comparison["finding"] != FINDING_COMPATIBLE
    assert not comparison["datasheet_identity"]["part_b"].get("verified")
    assert comparison["datasheet_identity"]["part_a"].get("verified")
