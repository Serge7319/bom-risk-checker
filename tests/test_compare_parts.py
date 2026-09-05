"""Compare Parts regressions across shared family profiles."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.datasheet_comparison import user_may_view_comparison_diagnostics
from src.parts_compare import (
    FINDING_COMPATIBLE,
    FINDING_MATERIAL,
    FINDING_NEEDS_DATA,
    USER_FACING_COMPARE_COLUMNS,
    build_parts_comparison,
    claim_compare_parts_submit,
    derive_overall_finding,
    generate_parts_comparison_pdf,
    map_status_to_assessment,
    public_part_card,
    run_compare_parts,
    user_facing_compare_rows,
)


def _cap(a="0.1uF", v="50V", pkg="0603", **extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "C0603C104K5RACTU"),
        "manufacturer": "KEMET",
        "description": "Ceramic capacitor",
        "package": pkg,
        "mounting_style": "SMD",
        "capacitance": a,
        "rated_voltage": v,
        "dielectric": "X7R",
        "tolerance": "10%",
        "lifecycle_status": "Active",
        "datasheet_url": "https://example.com/cap.pdf",
        **extra,
    }


def _res(r="10k", p="0.1W", pkg="0603", **extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "RC0603FR-0710KL"),
        "manufacturer": "Yageo",
        "description": "Thick film resistor",
        "package": pkg,
        "mounting_style": "SMD",
        "resistance": r,
        "power_rating": p,
        "tolerance": "1%",
        "lifecycle_status": "Active",
        **extra,
    }


def _ind(**extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "LQH32CN100K23L"),
        "manufacturer": "Murata",
        "description": "Power inductor 10uH",
        "package": "1210",
        "mounting_style": "SMD",
        "inductance": "10uH",
        "rated_current": "450mA",
        "dcr": "0.3Ohm",
        **extra,
    }


def _diode(**extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "1N5819"),
        "manufacturer": "Onsemi",
        "description": "Schottky diode 40V",
        "package": "DO-41",
        "mounting_style": "Through Hole",
        "reverse_voltage": "40V",
        "forward_current": "1A",
        "forward_voltage": "0.6V",
        **extra,
    }


def _bjt(**extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "MMBT3904LT1G"),
        "manufacturer": "Onsemi",
        "description": "NPN transistor",
        "package": "SOT-23",
        "mounting_style": "SMD",
        "pin_count": 3,
        "polarity": "NPN",
        "collector_emitter_voltage": "40V",
        "collector_current": "200mA",
        "pinout": extra.pop("pinout", "1=B 2=E 3=C"),
        **extra,
    }


def _mosfet(**extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "2N7002"),
        "manufacturer": "Onsemi",
        "description": "N-Channel MOSFET 60V",
        "package": "SOT-23",
        "mounting_style": "SMD",
        "pin_count": 3,
        "drain_source_voltage": "60V",
        "continuous_drain_current": "115mA",
        "rds_on": "7.5Ohm",
        "pinout": extra.pop("pinout", "1=G 2=S 3=D"),
        **extra,
    }


def _mcu(**extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "STM32F103C8T6"),
        "manufacturer": "STMicroelectronics",
        "description": "ARM Cortex-M microcontroller",
        "package": "LQFP-48",
        "mounting_style": "SMD",
        "pin_count": 48,
        "supply_voltage_min": 2.0,
        "supply_voltage_max": 3.6,
        "memory_size": "64KB",
        **extra,
    }


def _fpga(**extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "XC7A35T-1CPG236C"),
        "manufacturer": "AMD",
        "description": "Artix-7 FPGA",
        "package": "CSBGA-236",
        "mounting_style": "SMD",
        "pin_count": 236,
        "logic_resources": "33280",
        **extra,
    }


def _connector(**extra):
    return {
        "manufacturer_part_number": extra.pop("mpn", "HDR-2x20"),
        "manufacturer": "Samtec",
        "description": "Board-to-board connector header",
        "package": "Through Hole",
        "mounting_style": "Through Hole",
        "positions": "40",
        "pitch": "2.54mm",
        "mating_style": "Header",
        **extra,
    }


class ComparePartsCoreTests(unittest.TestCase):
    def test_user_facing_columns_exclude_internal_metadata(self):
        comparison = build_parts_comparison(_cap(), _cap(mpn="C0603C104K5RACTU-ALT"))
        for row in comparison["rows"]:
            self.assertEqual(set(row), set(USER_FACING_COMPARE_COLUMNS))
            self.assertNotIn("CompareMode", row)
            self.assertNotIn("ValueRole", row)
            self.assertNotIn("Key", row)
            self.assertNotIn("Required", row)

    def test_capacitor_compatible_on_available_evidence(self):
        comparison = build_parts_comparison(_cap(), _cap(mpn="ALT-CAP"))
        self.assertEqual(comparison["family"], "Capacitor")
        self.assertEqual(comparison["finding"], FINDING_COMPATIBLE)
        self.assertFalse(comparison["supplier_substitute_claim"])

    def test_capacitor_material_voltage_difference(self):
        comparison = build_parts_comparison(_cap(v="50V"), _cap(v="25V", mpn="ALT"))
        self.assertEqual(comparison["finding"], FINDING_MATERIAL)
        assessments = {row["Attribute"]: row["Assessment"] for row in comparison["rows"]}
        self.assertEqual(assessments.get("Rated voltage"), FINDING_MATERIAL)

    def test_resistor_inductor_diode_families(self):
        for builder, family in (
            (_res, "Resistor"),
            (_ind, "Inductor"),
            (_diode, "Diode / protection"),
        ):
            comparison = build_parts_comparison(builder(), builder(mpn="ALT"))
            self.assertEqual(comparison["family"], family)
            self.assertIn(
                comparison["finding"],
                {FINDING_COMPATIBLE, FINDING_NEEDS_DATA},
            )

    def test_bjt_requires_pinout_before_drop_in_style_compatible(self):
        left = _bjt(pinout="")
        right = _bjt(mpn="ALT", pinout="")
        comparison = build_parts_comparison(left, right)
        self.assertEqual(comparison["family"], "Bipolar transistor")
        # Without pinout evidence, do not treat as fully compatible drop-in style.
        self.assertIn(comparison["finding"], {FINDING_NEEDS_DATA, FINDING_COMPATIBLE})
        if comparison["finding"] == FINDING_COMPATIBLE:
            # Only allowed when profile does not require pinout — assert profile flag.
            from src.component_family_profiles import get_family_profile

            self.assertFalse(get_family_profile("Bipolar transistor").requires_pinout_for_dropin)

    def test_bjt_and_mosfet_pinout_gate(self):
        from src.component_family_profiles import get_family_profile

        for builder, family in ((_bjt, "Bipolar transistor"), (_mosfet, "MOSFET")):
            profile = get_family_profile(family)
            comparison = build_parts_comparison(
                builder(pinout=""),
                builder(mpn="ALT", pinout=""),
            )
            self.assertEqual(comparison["family"], family)
            if profile.requires_pinout_for_dropin:
                self.assertEqual(comparison["finding"], FINDING_NEEDS_DATA)

    def test_mcu_and_fpga_package_alone_not_compatible_claim(self):
        mcu_a = _mcu()
        mcu_b = {
            "manufacturer_part_number": "OTHER-MCU",
            "description": "ARM Cortex-M microcontroller",
            "package": "LQFP-48",
            "pin_count": 48,
        }
        comparison = build_parts_comparison(mcu_a, mcu_b)
        self.assertEqual(comparison["family"], "MCU / processor")
        # Sparse parametric evidence must not become a strong compatible claim.
        self.assertEqual(comparison["finding"], FINDING_NEEDS_DATA)

        fpga = build_parts_comparison(_fpga(), {"description": "Artix-7 FPGA", "package": "CSBGA-236", "pin_count": 236, "manufacturer_part_number": "OTHER"})
        self.assertEqual(fpga["family"], "FPGA / CPLD")
        self.assertEqual(fpga["finding"], FINDING_NEEDS_DATA)

    def test_connector_matrix(self):
        comparison = build_parts_comparison(_connector(), _connector(mpn="ALT"))
        self.assertEqual(comparison["family"], "Connector / electromechanical")
        attrs = {row["Attribute"] for row in comparison["rows"]}
        self.assertTrue(attrs.intersection({"Positions", "Pitch", "Mating style", "Package"}))

    def test_family_mismatch_is_material_difference(self):
        comparison = build_parts_comparison(_cap(), _res())
        self.assertTrue(comparison["family_mismatch"])
        self.assertEqual(comparison["finding"], FINDING_MATERIAL)
        family_row = next(row for row in comparison["rows"] if row["Attribute"] == "Component family")
        self.assertEqual(family_row["Assessment"], FINDING_MATERIAL)

    def test_missing_data_never_inferred_as_match(self):
        left = {"description": "Ceramic capacitor", "package": "0603", "manufacturer_part_number": "A"}
        right = {"description": "Ceramic capacitor", "package": "0603", "manufacturer_part_number": "B"}
        comparison = build_parts_comparison(left, right)
        self.assertGreater(comparison["counts"]["needs_data"], 0)
        self.assertNotEqual(comparison["finding"], FINDING_COMPATIBLE)

    def test_public_card_strips_diagnostics(self):
        card = public_part_card(
            {
                "manufacturer_part_number": "X",
                "diagnostic_status_code": "500",
                "provider_health": {"has_verified_data": True},
                "datasheet_url": "https://example.com/d.pdf",
            }
        )
        self.assertEqual(card["mpn"], "X")
        self.assertNotIn("diagnostic_status_code", card)
        self.assertNotIn("provider_health", card)

    def test_submit_debounce(self):
        session = {}
        self.assertTrue(claim_compare_parts_submit(session, "AAA", "BBB", now=100.0))
        self.assertFalse(claim_compare_parts_submit(session, "AAA", "BBB", now=100.5))
        self.assertTrue(claim_compare_parts_submit(session, "AAA", "BBB", now=103.0))

    def test_pdf_parity_with_user_facing_fields(self):
        from io import BytesIO

        from pypdf import PdfReader

        comparison = build_parts_comparison(_cap(), _cap(v="25V", mpn="ALT"))
        pdf = generate_parts_comparison_pdf(comparison)
        self.assertTrue(pdf.startswith(b"%PDF"))
        reader = PdfReader(BytesIO(pdf))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        self.assertIn(comparison["finding"], text)
        self.assertIn("Part A", text)
        self.assertIn("Part B", text)
        self.assertNotIn("CompareMode", text)
        self.assertNotIn("ValueRole", text)

    def test_run_compare_parts_uses_lookup(self):
        with patch("src.parts_compare.lookup_part_for_compare", side_effect=[_cap(), _cap(mpn="ALT")]):
            result = run_compare_parts("C0603C104K5RACTU", "ALT")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["comparison"]["family"], "Capacitor")

    def test_map_status_helpers(self):
        self.assertEqual(map_status_to_assessment("Match"), FINDING_COMPATIBLE)
        self.assertEqual(map_status_to_assessment("Different"), FINDING_MATERIAL)
        self.assertEqual(map_status_to_assessment("Needs data"), FINDING_NEEDS_DATA)
        self.assertEqual(
            derive_overall_finding(
                matches=0,
                differences=0,
                needs_data=5,
                evidence_status="incomplete",
                family_mismatch=False,
                requires_pinout_for_dropin=False,
                pinout_matched=False,
            ),
            FINDING_NEEDS_DATA,
        )


class ComparePartsUiWiringTests(unittest.TestCase):
    def test_nav_and_runtime_wire_compare_parts(self):
        root = Path(__file__).resolve().parents[1]
        shell = (root / "src" / "ui" / "unified_shell.py").read_text(encoding="utf-8")
        runtime = (root / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        page = (root / "src" / "pages" / "compare_parts.py").read_text(encoding="utf-8")
        self.assertIn('"Compare Parts"', shell)
        self.assertIn('"Compare Parts"', runtime)
        self.assertIn("render_compare_parts_page", runtime)
        self.assertIn("compare_parts_form", page)
        self.assertIn("cadivor_comparison_matrix_dataframe", page)
        self.assertIn("user_may_view_comparison_diagnostics", page)
        self.assertTrue(user_may_view_comparison_diagnostics(is_admin=True))
        self.assertFalse(user_may_view_comparison_diagnostics(is_admin=False, role="engineer"))

    def test_user_facing_projection_renames_columns(self):
        rows = user_facing_compare_rows(
            [
                {
                    "Attribute": "Package",
                    "Original": "0603",
                    "Candidate": "0603",
                    "Status": "Match",
                    "Evidence": "ok",
                    "Key": "package",
                    "CompareMode": "exact",
                    "ValueRole": "identity",
                    "Required": True,
                }
            ]
        )
        self.assertEqual(rows[0]["Part A"], "0603")
        self.assertEqual(rows[0]["Part B"], "0603")
        self.assertEqual(rows[0]["Assessment"], FINDING_COMPATIBLE)
        self.assertNotIn("Key", rows[0])


if __name__ == "__main__":
    unittest.main()
