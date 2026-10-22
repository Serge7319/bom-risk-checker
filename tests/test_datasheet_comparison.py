import sys
import types
import unittest
from unittest import mock


sys.modules.setdefault("requests", types.SimpleNamespace())

from src import datasheet_comparison
from src.datasheet_comparison import (
    build_recommendation_score_breakdown,
    build_datasheet_comparison,
    build_datasheet_review_evidence,
    build_pdf_field_evidence,
    compare_datasheet_dimension_evidence,
    extract_datasheet_text,
    extract_datasheet_dimension_evidence,
    infer_component_family,
    normalize_mounting_style,
)
from src.plans import get_plan


class DatasheetComparisonTests(unittest.TestCase):
    def test_capacitor_comparison_is_family_aware_and_marks_differences(self):
        original = {
            "description": "0.1 uF 50V X7R Ceramic Capacitor",
            "package": "0603",
            "capacitance": "0.1 uF",
            "rated_voltage": "50V",
            "dielectric": "X7R",
        }
        candidate = {
            "package": "0603",
            "capacitance": "0.1 uF",
            "rated_voltage": "25V",
            "dielectric": "X7R",
        }
        result = build_datasheet_comparison(original, candidate)
        statuses = {row["Attribute"]: row["Status"] for row in result["rows"]}
        self.assertEqual(result["family"], "Capacitor")
        self.assertEqual(statuses["Capacitance"], "Match")
        self.assertEqual(statuses["Rated voltage"], "Different")

    def test_transistor_and_inductor_get_different_engineering_checks(self):
        transistor = infer_component_family({"description": "N-Channel MOSFET 60V"})
        inductor = infer_component_family({"description": "Power Inductor 10 uH"})
        self.assertEqual(transistor, "MOSFET")
        self.assertEqual(inductor, "Inductor")

    def test_missing_data_is_never_reported_as_a_match(self):
        result = build_datasheet_comparison(
            {"description": "Resistor", "package": "0603"},
            {"package": "0603"},
        )
        self.assertGreater(result["counts"]["Needs data"], 0)
        self.assertEqual(result["counts"]["Different"], 0)

    def test_pdf_evidence_includes_page_citations(self):
        original_pdf = {"pages": [{"page": 2, "text": "Capacitance: 0.1 uF\nRated Voltage: 50V"}]}
        candidate_pdf = {"pages": [{"page": 4, "text": "Capacitance: 0.1 uF\nRated Voltage: 25V"}]}
        rows = build_pdf_field_evidence(original_pdf, candidate_pdf, "Capacitor")
        values = {row["Attribute"]: row for row in rows}
        self.assertEqual(values["Capacitance"]["Status"], "Match")
        self.assertEqual(values["Rated voltage"]["Status"], "Different")
        self.assertEqual(values["Rated voltage"]["Source pages"], "p. 2 / p. 4")

    def test_pdf_headers_without_values_are_not_mistaken_for_matches(self):
        pdf = {"available": True, "pages": [{"page": 3, "text": "Package\nPin count\nSupply voltage (V)"}]}
        rows = build_pdf_field_evidence(pdf, pdf, "Integrated Circuit")
        values = {row["Key"]: row for row in rows}
        self.assertEqual(values["package"]["Status"], "Needs data")
        self.assertEqual(values["pin_count"]["Status"], "Needs data")
        self.assertEqual(values["voltage_range"]["Status"], "Needs data")

    def test_generic_powerpad_phrase_is_not_a_package_conflict_or_match(self):
        pdf = {
            "available": True,
            "pages": [{
                "page": 1,
                "document": "TI datasheet Rev L",
                "text": "PowerPAD integrated circuit package",
            }],
        }

        row = next(
            row for row in build_pdf_field_evidence(pdf, pdf, "Regulator")
            if row["Key"] == "package"
        )

        self.assertEqual(row["Status"], "Needs data")
        self.assertEqual(row["Original PDF value"], "Not found")
        self.assertEqual(row["Original PDF evidence"], "Not found")
        self.assertIn("package-outline drawing", row["Evidence"])

    def test_prose_about_package_ranges_and_pin_count_is_not_a_field_value(self):
        pdf = {
            "available": True,
            "pages": [
                {
                    "page": 9,
                    "text": "Package types: from 36 pins to 100 pins. Depending on the device chosen, different sets of implementation.",
                },
                {
                    "page": 14,
                    "text": "Pin count implementation, with a reduced pin count and low-power consumption, while delivering.",
                },
            ],
        }
        rows = build_pdf_field_evidence(pdf, {}, "MCU / processor")
        values = {row["Key"]: row for row in rows}
        self.assertEqual(values["package"]["Original PDF value"], "Not found")
        self.assertEqual(values["pin_count"]["Original PDF value"], "Not found")
        self.assertEqual(values["package"]["Status"], "Needs data")
        self.assertEqual(values["pin_count"]["Status"], "Needs data")

    def test_explicit_hsoic_package_designation_is_preserved(self):
        pdf = {
            "available": True,
            "pages": [{
                "page": 3,
                "document": "TI datasheet Rev L",
                "text": "DDA Package 8-Pin HSOIC With Thermal Pad (Top View)",
            }],
        }

        row = next(
            row for row in build_pdf_field_evidence(pdf, pdf, "Regulator")
            if row["Key"] == "package"
        )

        self.assertEqual(row["Status"], "Match")
        self.assertIn("8-Pin HSOIC", row["Original PDF value"])
        self.assertIn("p. 3", row["Original PDF page"])

    def test_specific_package_page_is_preferred_over_generic_powerpad_phrase(self):
        pdf = {
            "available": True,
            "pages": [
                {"page": 1, "text": "PowerPAD integrated circuit package"},
                {"page": 3, "text": "Figure 4-1. DDA Package 8-Pin HSOIC With Thermal Pad (Top View)"},
            ],
        }

        row = next(
            row for row in build_pdf_field_evidence(pdf, pdf, "Regulator")
            if row["Key"] == "package"
        )

        self.assertIn("8-Pin HSOIC", row["Original PDF value"])
        self.assertIn("p. 3", row["Original PDF page"])
        self.assertEqual(row["Status"], "Match")

    def test_pdf_package_evidence_is_not_taken_from_an_ambiguous_family_datasheet(self):
        pdf = {
            "available": True,
            "pages": [
                {
                    "page": 2,
                    "text": "LM317DCYR Adjustable Regulator\nDCY Package 4-Pin SOT-223",
                },
                {
                    "page": 7,
                    "text": "LM317DCYR and LM317MDCYR ordering options\nDDA Package 8-Pin SOIC",
                },
            ],
        }

        row = next(
            row for row in build_pdf_field_evidence(
                pdf,
                pdf,
                "Regulator",
                original_mpn="LM317DCYR",
                candidate_mpn="LM317DCYR",
            )
            if row["Key"] == "package"
        )

        self.assertEqual(row["Original PDF value"], "Not found")
        self.assertEqual(row["Candidate PDF value"], "Not found")
        self.assertEqual(row["Status"], "Needs data")
        self.assertIn("No unique package designation", row["Evidence"])

    def test_pdf_package_requires_exact_mpn_identity_when_available(self):
        pdf = {
            "available": True,
            "pages": [{
                "page": 2,
                "text": "LM317 family\nPackage: 4-Pin SOT-223",
            }],
        }

        row = next(
            row for row in build_pdf_field_evidence(
                pdf,
                pdf,
                "Regulator",
                original_mpn="LM317DCYR",
                candidate_mpn="LM317DCYR",
            )
            if row["Key"] == "package"
        )

        self.assertEqual(row["Original PDF value"], "Not found")
        self.assertEqual(row["Status"], "Needs data")

    def test_pdf_mpn_identity_does_not_accept_a_longer_order_code_prefix(self):
        pdf = {
            "available": True,
            "pages": [{
                "page": 2,
                "text": "LM317DCYR adjustable regulator, SOT-223 package",
            }],
        }

        row = next(
            row for row in build_pdf_field_evidence(
                pdf,
                pdf,
                "Regulator",
                original_mpn="LM317D",
                candidate_mpn="LM317D",
            )
            if row["Key"] == "package"
        )

        self.assertEqual(row["Original PDF value"], "Not found")
        self.assertEqual(row["Candidate PDF value"], "Not found")
        self.assertEqual(row["Status"], "Needs data")

    def test_pdf_mpn_identity_accepts_exact_code_with_surrounding_text(self):
        pdf = {
            "available": True,
            "pages": [{
                "page": 2,
                "text": "LM317DCYR adjustable regulator\nPackage: 4-Pin SOT-223",
            }],
        }

        row = next(
            row for row in build_pdf_field_evidence(
                pdf,
                pdf,
                "Regulator",
                original_mpn="LM317DCYR",
                candidate_mpn="LM317DCYR",
            )
            if row["Key"] == "package"
        )

        self.assertEqual(row["Original PDF value"], "4-Pin SOT-223")
        self.assertEqual(row["Status"], "Match")

    def test_dimension_excerpts_keep_document_and_page_citations(self):
        pdf = {
            "available": True,
            "pages": [{
                "page": 12,
                "document": "MCU datasheet Rev D",
                "text": "Package outline dimensions\nBody length 10.0 mm\nBody width 10.0 mm\nLead pitch 0.8 mm",
            }],
        }
        excerpts = extract_datasheet_dimension_evidence(pdf)
        self.assertTrue(excerpts)
        self.assertEqual(excerpts[0]["document"], "MCU datasheet Rev D")
        self.assertEqual(excerpts[0]["page"], 12)
        self.assertIn("10.0 mm", excerpts[0]["excerpt"])

    def test_dimension_evidence_deduplicates_repeated_geometry_lines(self):
        excerpts = extract_datasheet_dimension_evidence(
            {
                "pages": [{
                    "page": 12,
                    "text": "Package outline dimensions\nBody length 10.0 mm\nBody length 10.0 mm",
                }]
            }
        )
        self.assertEqual(len(excerpts), 1)

    def test_dimension_excerpts_exclude_prose_without_measured_geometry(self):
        excerpts = extract_datasheet_dimension_evidence(
            {
                "pages": [{
                    "page": 9,
                    "text": "Package types: from 36 pins to 100 pins. Depending on the device chosen, different implementations.",
                }]
            }
        )
        self.assertEqual(excerpts, [])

    def test_product_page_datasheet_link_is_followed_and_pdf_is_extracted(self):
        import fitz

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Package: LQFP-48")
        pdf_payload = document.tobytes()
        document.close()

        class Response:
            def __init__(self, payload, content_type):
                self.payload = payload
                self.status_code = 200
                self.headers = {"Content-Type": content_type}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield self.payload

            def close(self):
                return None

        responses = [
            Response(
                b'<html><a href="/docs/stm32.pdf">Official datasheet PDF</a></html>',
                "text/html",
            ),
            Response(pdf_payload, "application/pdf"),
        ]
        with (
            mock.patch.object(datasheet_comparison, "_public_datasheet_url", return_value=True),
            mock.patch.object(
                datasheet_comparison.requests,
                "get",
                side_effect=responses,
                create=True,
            ),
        ):
            result = extract_datasheet_text("https://parts.example.com/stm32f103c8t6")

        self.assertTrue(result["available"])
        self.assertEqual(result["retrieval_path"], "product_page_pdf_link")
        self.assertEqual(result["pages"][0]["text"], "Package: LQFP-48")
        self.assertEqual(
            result["final_url"],
            "https://parts.example.com/docs/stm32.pdf",
        )

    def test_pdf_with_octet_stream_content_type_uses_pdf_size_limit(self):
        import fitz

        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Package: LQFP-48")
        payload = document.tobytes() + (b"\n" * (2 * 1024 * 1024))
        document.close()

        class Response:
            status_code = 200
            headers = {"Content-Type": "application/octet-stream"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                yield payload

            def close(self):
                return None

        with (
            mock.patch.object(datasheet_comparison, "_public_datasheet_url", return_value=True),
            mock.patch.object(datasheet_comparison.requests, "get", return_value=Response(), create=True),
        ):
            result = extract_datasheet_text("https://parts.example.com/unknown-type")
        self.assertTrue(result["available"])
        self.assertIn("Package: LQFP-48", result["pages"][0]["text"])

    def test_matching_dimension_labels_with_different_values_flag_a_conflict(self):
        findings = compare_datasheet_dimension_evidence(
            [{"excerpt": "Package outline · Body length 10.0 mm · Lead pitch 0.8 mm"}],
            [{"excerpt": "Package outline · Body length 12.0 mm · Lead pitch 0.8 mm"}],
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("body length", findings[0])
        self.assertIn("10 mm vs 12 mm", findings[0])

    def test_review_evidence_marks_unavailable_pdfs_as_unavailable(self):
        result = build_datasheet_review_evidence(
            {"available": False, "reason": "No text", "pages": []},
            {"available": False, "reason": "No text", "pages": []},
            "Integrated Circuit",
        )
        self.assertFalse(result["source"]["available"])
        self.assertFalse(result["candidate"]["available"])
        self.assertTrue(all(row["Status"] == "Needs data" for row in result["field_evidence"]))

    def test_datasheet_fetcher_rejects_local_and_insecure_urls(self):
        for url in (
            "http://8.8.8.8/example.pdf",
            "https://127.0.0.1/example.pdf",
            "https://localhost/example.pdf",
            "https://supplier.example:badport/datasheet.pdf",
            "file:///etc/passwd",
        ):
            with self.subTest(url=url):
                result = extract_datasheet_text(url)
                self.assertFalse(result["available"])
                self.assertEqual(result["pages"], [])

    def test_pdf_evidence_is_a_professional_entitlement(self):
        self.assertFalse(get_plan("Starter")["datasheet_comparison"])
        self.assertTrue(get_plan("Professional")["datasheet_comparison"])
        self.assertTrue(get_plan("Business")["datasheet_comparison"])

    def test_close_match_scores_above_candidate_with_documented_differences(self):
        close = build_recommendation_score_breakdown(
            69, 95, {"Match": 8, "Different": 0, "Needs data": 1},
            is_explicit_substitute=False,
        )
        different = build_recommendation_score_breakdown(
            69, 70, {"Match": 4, "Different": 3, "Needs data": 2},
            is_explicit_substitute=False,
        )
        self.assertGreater(close["recommendation_score"], different["recommendation_score"])
        self.assertEqual(close["matches"], 8)
        self.assertEqual(different["differences"], 3)


    def test_supplier_listed_direct_substitute_is_not_inflated_when_evidence_is_sparse(self):
        score = build_recommendation_score_breakdown(
            60, 55, {"Match": 2, "Different": 0, "Needs data": 7},
            is_explicit_substitute=True,
        )
        # Direct relationship must remain separate from engineering confidence;
        # sparse packaging-only matches must not floor recommendation to 85+.
        self.assertLess(score["recommendation_score"], 85)

    def test_supplier_listed_direct_with_substantial_engineering_coverage_keeps_floor(self):
        score = build_recommendation_score_breakdown(
            60, 80, {"Match": 6, "Different": 0, "Needs data": 1},
            is_explicit_substitute=True,
        )
        self.assertGreaterEqual(score["recommendation_score"], 85)


    def test_capacitor_uses_rated_voltage_not_ic_supply_voltage(self):
        result = build_datasheet_comparison(
            {"description": "Ceramic capacitor", "package": "0603", "rated_voltage": "50V"},
            {"description": "Ceramic capacitor", "package": "0603", "rated_voltage": "50V"},
        )
        fields = {row["Attribute"]: row for row in result["rows"]}
        self.assertEqual(fields["Rated voltage"]["Status"], "Match")
        self.assertNotIn("Supply voltage", fields)

    def test_surface_mount_mlcc_and_smd_mounting_values_match(self):
        result = build_datasheet_comparison(
            {
                "description": "Ceramic capacitor",
                "mounting_style": "Surface Mount, MLCC",
            },
            {
                "description": "Ceramic capacitor",
                "mounting_style": "SMD",
            },
        )
        statuses = {row["Attribute"]: row["Status"] for row in result["rows"]}
        self.assertEqual(statuses["Mounting"], "Match")
        self.assertEqual(normalize_mounting_style("Surface Mount, MLCC"), "smd")
        self.assertEqual(normalize_mounting_style("SMT"), "smd")

    def test_through_hole_versus_smd_mounting_remains_different(self):
        result = build_datasheet_comparison(
            {"description": "Ceramic capacitor", "mounting_style": "Through Hole"},
            {"description": "Ceramic capacitor", "mounting_style": "SMD"},
        )
        statuses = {row["Attribute"]: row["Status"] for row in result["rows"]}
        self.assertEqual(statuses["Mounting"], "Different")

    def test_passive_families_do_not_include_pin_count_rows(self):
        cases = (
            {"description": "Ceramic capacitor 0.1uF", "package": "0603", "pin_count": 603},
            {"description": "Thick film resistor 10k", "package": "0603", "pin_count": 603},
            {"description": "Power inductor 10uH", "package": "6x6mm", "pin_count": 603},
        )
        for original in cases:
            with self.subTest(description=original["description"]):
                rows = build_datasheet_comparison(original, dict(original))["rows"]
                attributes = {row["Attribute"] for row in rows}
                self.assertNotIn("Pin count", attributes)
                self.assertIn("Package", attributes)

    def test_engineering_evidence_assessment_high_coverage(self):
        from src.datasheet_comparison import build_engineering_evidence_assessment

        assessment = build_engineering_evidence_assessment(
            {"Match": 7, "Different": 0, "Needs data": 1},
            classification="Verified direct substitute",
            substitute_type="Direct",
            evidence_source="DigiKey",
            supplier_relationship_evidence=[{
                "supplier": "DigiKey",
                "substitute_type": "Direct",
                "summary": "DigiKey relationship: Direct.",
                "source_url": "https://www.digikey.com/example",
                "original_mpn": "C0603C104K5RACTU",
                "candidate_mpn": "C0603C104K5RAC3121",
            }],
        )
        self.assertGreaterEqual(assessment["engineering_comparison_confidence"], 82)
        self.assertEqual(assessment["supplier_relationship_confidence"], 95)
        self.assertIn("DigiKey relationship: Direct.", assessment["supplier_relationship_summary"])
        self.assertNotIn(
            "DigiKey identifies this candidate as a Direct substitute for the original part number.",
            assessment["supplier_relationship_summary"],
        )
        self.assertIn("7 confirmed matches", assessment["engineering_evidence_summary"])

    def test_engineering_evidence_assessment_sparse_coverage(self):
        from src.datasheet_comparison import build_engineering_evidence_assessment

        assessment = build_engineering_evidence_assessment(
            {"Match": 1, "Different": 0, "Needs data": 7},
            classification="Verified direct substitute",
            substitute_type="Direct",
            evidence_source="DigiKey",
            supplier_relationship_evidence=[{
                "supplier": "DigiKey",
                "substitute_type": "Direct",
                "summary": "DigiKey relationship: Direct.",
                "original_mpn": "C0603C104K5RACTU",
                "candidate_mpn": "C0603C104K5RAC3121",
            }],
        )
        self.assertLess(assessment["engineering_comparison_confidence"], 55)
        self.assertEqual(assessment["supplier_relationship_confidence"], 95)
        self.assertIn("incomplete", assessment["engineering_evidence_summary"])


if __name__ == "__main__":
    unittest.main()
