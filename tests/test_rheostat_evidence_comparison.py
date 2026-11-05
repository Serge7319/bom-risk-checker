"""Datasheet-first comparison for a rheostat, using a local synthetic fixture.

The fixture text is not the customer's attached PDF. Those files were not in
this worktree, so the test does not open stored BOM records.
"""

import unittest
from io import BytesIO
from threading import Barrier

from src.compatibility_gate import assess_part_compatibility
from src.datasheet_comparison import (
    _parse_datasheet_pdf,
    _pdf_mentions_exact_part,
    build_datasheet_comparison,
    build_pdf_field_evidence,
    classify_distributor_cross_reference,
    datasheet_extraction_summary,
    family_for_datasheet_review,
    merge_verified_datasheet_rows,
    mpn_search_plan,
)
from src.parts_compare import build_parts_comparison, run_compare_parts


ORIGINAL_PAGES = [
    {
        "page": 1,
        "document": "RES10K-synthetic.pdf",
        "text": "Ohmite RES10K\nRheostat\nResistance 10 kOhm\nPower rating 12.5 W",
    },
    {
        "page": 2,
        "document": "RES10K-synthetic.pdf",
        "text": "Mounting style Panel Mount\nTerminal style Solder lug\nShaft 6.35 mm",
    },
    {
        "page": 3,
        "document": "RES10K-synthetic.pdf",
        "text": "Tolerance ±10%",
    },
]

CANDIDATE_PAGES = [
    {
        "page": 1,
        "document": "RES10KE-synthetic.pdf",
        "text": "Ohmite RES10KE\nRheostat\nResistance 10 kOhm\nPower rating 12.5 W",
    },
    {
        "page": 2,
        "document": "RES10KE-synthetic.pdf",
        "text": "Mounting style Panel Mount\nTerminal style Solder lug\nShaft 6.35 mm",
    },
    {
        "page": 3,
        "document": "RES10KE-synthetic.pdf",
        "text": "Tolerance ±10%",
    },
]


def _rheostat(mpn: str, **extra):
    part = {
        "manufacturer": "Ohmite",
        "manufacturer_part_number": mpn,
        "description": f"Ohmite rheostat {mpn} 10 kOhm 12.5 W",
        "mounting_style": "Panel Mount",
    }
    part.update(extra)
    return part


class RheostatEvidenceComparisonTests(unittest.TestCase):
    def test_raw_mpn_identity_is_preserved(self):
        original = mpn_search_plan("RES10K")
        candidate = mpn_search_plan("RES10KE")
        hyphenated = mpn_search_plan("RES-10K")

        self.assertEqual(original["raw"], "RES10K")
        self.assertEqual(candidate["raw"], "RES10KE")
        self.assertNotEqual(original["normalized"], candidate["normalized"])
        self.assertNotIn("RES10KE", original["search_aliases"])
        self.assertIn("RES-10K", original["search_aliases"])
        self.assertEqual(hyphenated["normalized"], "RES10K")
        self.assertEqual(hyphenated["raw"], "RES-10K")
        self.assertFalse(_pdf_mentions_exact_part({"pages": ORIGINAL_PAGES}, "RES10KE"))
        self.assertTrue(_pdf_mentions_exact_part({"pages": ORIGINAL_PAGES}, "RES10K"))
        self.assertTrue(_pdf_mentions_exact_part({"pages": CANDIDATE_PAGES}, "RES10KE"))

    def test_catalog_rows_match_counts_and_keep_lifecycle_records(self):
        original = _rheostat(
            "RES10K",
            lifecycle_status="Conflicting supplier data",
            lifecycle_conflict=True,
            lifecycle_evidence=[
                {"source": "Supplier A", "status": "Active", "retrieved_at": "2024-01-02"},
                {"source": "Supplier B", "status": "Obsolete", "retrieved_at": "2024-03-04"},
            ],
        )
        candidate = _rheostat("RES10KE", lifecycle_status="Active")
        comparison = build_parts_comparison(
            original,
            candidate,
            part_a_mpn="RES10K",
            part_b_mpn="RES10KE",
        )

        self.assertEqual(comparison["family"], "Potentiometer / rheostat")
        labels = [row["Attribute"] for row in comparison["rows"]]
        self.assertNotIn("Pin count", labels)
        self.assertNotIn("Package", labels)
        self.assertIn("Resistance", labels)
        self.assertIn("Power rating", labels)
        counts = comparison["counts"]
        self.assertEqual(
            len(comparison["rows"]),
            counts["compatible"] + counts["material_difference"] + counts["needs_data"],
        )

        lifecycle = next(row for row in comparison["rows"] if row["Attribute"] == "Lifecycle")
        self.assertIn("Supplier A: Active (2024-01-02)", lifecycle["Part A"])
        self.assertIn("Supplier B: Obsolete (2024-03-04)", lifecycle["Part A"])
        self.assertNotEqual(lifecycle["Part A"], "Conflicting supplier data")
        self.assertEqual(lifecycle["Assessment"], "Material difference")

        mounting = next(row for row in comparison["rows"] if row["Attribute"] == "Mounting")
        self.assertEqual(mounting["Assessment"], "Compatible on available evidence")
        self.assertIn("supplier listing", mounting["Evidence"].lower())
        self.assertNotIn("p. ", mounting["Evidence"])

        matrix = build_datasheet_comparison(original, candidate)
        self.assertEqual(sum(matrix["counts"].values()), len(matrix["rows"]))

    def test_rheostat_warning_names_the_mechanical_gap(self):
        gate = assess_part_compatibility(
            _rheostat("RES10K"),
            _rheostat("RES10KE"),
        )
        warning = " ".join(gate["review_warnings"])
        self.assertFalse(gate["pin_count_applicable"])
        self.assertNotIn("pin-count", warning)
        self.assertNotIn("processor", warning.casefold())
        self.assertIn("terminal style", warning)
        self.assertIn("shaft", warning)
        self.assertNotIn("mounting", gate["physical_missing"])
        self.assertNotEqual(gate["drop_in_status"], "Not a drop-in replacement")

    def test_synthetic_datasheet_text_is_cited_by_page(self):
        original_pdf = {"available": True, "pages": ORIGINAL_PAGES}
        candidate_pdf = {"available": True, "pages": CANDIDATE_PAGES}
        family = family_for_datasheet_review(
            {"description": "10 kOhm 12.5 W"},
            original_pdf,
        )
        self.assertEqual(family, "Potentiometer / rheostat")
        rows = build_pdf_field_evidence(
            original_pdf,
            candidate_pdf,
            family,
            original_mpn="RES10K",
            candidate_mpn="RES10KE",
        )
        values = {row["Key"]: row for row in rows}
        self.assertNotIn("pin_count", values)
        self.assertNotIn("architecture", values)
        self.assertEqual(values["resistance"]["Status"], "Match")
        self.assertEqual(values["resistance"]["Original PDF value"], "10 kOhm")
        self.assertIn("p. 1", values["resistance"]["Original PDF page"])
        self.assertIn("RES10K-synthetic.pdf", values["resistance"]["Original PDF page"])
        self.assertEqual(values["power_rating"]["Status"], "Match")
        self.assertIn("p. 1", values["power_rating"]["Original PDF page"])
        self.assertEqual(values["mounting_style"]["Original PDF value"], "Panel Mount")
        self.assertIn("p. 2", values["mounting_style"]["Original PDF page"])
        self.assertEqual(values["shaft"]["Original PDF value"], "6.35 mm")
        self.assertIn("p. 2", values["shaft"]["Original PDF page"])

    def test_distributor_cross_reference_is_not_approval(self):
        claim = classify_distributor_cross_reference(
            {
                "source": "DigiKey",
                "relationship": "Direct substitute",
                "retrieved_at": "2024-05-01",
            }
        )
        self.assertEqual(claim["kind"], "distributor_cross_reference")
        self.assertFalse(claim["manufacturer_approval"])
        self.assertFalse(claim["drop_in_verified"])
        self.assertIn("not a verified drop-in", claim["note"])

    def test_page_cap_is_disclosed_and_ocr_is_not_claimed(self):
        from pypdf import PdfWriter

        writer = PdfWriter()
        for _ in range(41):
            writer.add_blank_page(width=200, height=200)
        payload = BytesIO()
        writer.write(payload)
        parsed = _parse_datasheet_pdf(payload.getvalue(), "https://example.test/rheostat.pdf")

        self.assertEqual(parsed["document_page_count"], 41)
        self.assertEqual(parsed["pages_examined"], 40)
        self.assertTrue(parsed["page_cap_applied"])
        self.assertFalse(parsed["search_complete"])
        self.assertFalse(parsed["ocr_supported"])
        self.assertEqual(parsed["extraction_method"], "none")
        summary = datasheet_extraction_summary(parsed)
        self.assertIn("not a full-document search", summary.casefold())
        self.assertIn("OCR", summary)

    def test_compare_parts_uses_verified_datasheet_citations(self):
        from unittest.mock import patch

        from src.compatibility_gate import assess_part_compatibility, comparison_row_part_values

        original = _rheostat(
            "RES10K",
            description="10 kOhm 12.5 W",
            lifecycle_status="Conflicting supplier data",
            lifecycle_conflict=True,
            lifecycle_evidence=[
                {"source": "Supplier A", "status": "Active", "retrieved_at": "2024-01-02"},
                {"source": "Supplier B", "status": "Obsolete", "retrieved_at": "2024-03-04"},
            ],
            datasheet_url="https://example.test/RES10K.pdf",
        )
        candidate = _rheostat(
            "RES10KE",
            description="10 kOhm 12.5 W",
            lifecycle_status="Active",
            datasheet_url="https://example.test/RES10KE.pdf",
        )
        original_pdf = {"available": True, "pages": ORIGINAL_PAGES}
        candidate_pdf = {"available": True, "pages": CANDIDATE_PAGES}
        comparison = build_parts_comparison(
            original,
            candidate,
            part_a_mpn="RES10K",
            part_b_mpn="RES10KE",
            datasheet_a=original_pdf,
            datasheet_b=candidate_pdf,
        )
        self.assertEqual(comparison["family"], "Potentiometer / rheostat")
        self.assertTrue(comparison["datasheet_identity"]["part_a"]["verified"])
        self.assertTrue(comparison["datasheet_identity"]["part_b"]["verified"])
        counts = comparison["counts"]
        self.assertEqual(len(comparison["rows"]), 17)
        self.assertEqual(
            len(comparison["rows"]),
            counts["compatible"] + counts["material_difference"] + counts["needs_data"],
        )
        self.assertEqual(counts["compatible"], 6)
        self.assertEqual(counts["material_difference"], 1)
        self.assertEqual(counts["needs_data"], 10)
        by_name = {row["Attribute"]: row for row in comparison["rows"]}
        self.assertEqual(by_name["Resistance"]["Part A"], "10 kOhm")
        self.assertEqual(by_name["Resistance"]["Part B"], "10 kOhm")
        self.assertIn("RES10K-synthetic.pdf p. 1", by_name["Resistance"]["Evidence"])
        self.assertIn("RES10KE-synthetic.pdf p. 1", by_name["Resistance"]["Evidence"])
        self.assertIn("12.5 W", by_name["Power rating"]["Part A"])
        self.assertIn("p. 1", by_name["Power rating"]["Evidence"])
        self.assertIn("p. 2", by_name["Shaft"]["Evidence"])
        self.assertEqual(by_name["Shaft"]["Part A"], "6.35 mm")
        self.assertEqual(by_name["Terminal style"]["Assessment"], "Compatible on available evidence")
        self.assertIn("Supplier A: Active (2024-01-02)", by_name["Lifecycle"]["Part A"])
        self.assertIn("Supplier B: Obsolete (2024-03-04)", by_name["Lifecycle"]["Part A"])
        self.assertIn("supplier listing", by_name["Lifecycle"]["Evidence"].lower())
        self.assertNotIn("p. ", by_name["Lifecycle"]["Evidence"])
        self.assertEqual(by_name["Taper"]["Part A"], "Not stated in this datasheet")
        warning = " ".join(comparison["review_warnings"])
        self.assertNotIn("pin", warning.casefold())
        self.assertNotIn("processor", warning.casefold())
        self.assertIn("Taper", warning)
        self.assertNotIn("Resistance", warning)
        self.assertNotIn("Shaft", warning)

        source = {
            "manufacturer_part_number": "RES10K",
            "manufacturer": "Ohmite",
            "category": comparison["family"],
        }
        alternate = {
            "manufacturer_part_number": "RES10KE",
            "manufacturer": "Ohmite",
            "category": comparison["family"],
        }
        source.update(comparison_row_part_values(comparison["rows"], "Part A"))
        alternate.update(comparison_row_part_values(comparison["rows"], "Part B"))
        gate = assess_part_compatibility(source, alternate)
        gate_warning = " ".join(gate["review_warnings"])
        self.assertNotIn("pin-count", gate_warning)
        self.assertNotIn("terminal style", gate["physical_missing"])
        self.assertNotIn("shaft", gate["physical_missing"])
        self.assertNotIn("mounting", gate["physical_missing"])

        def _gather(*, mpn, manufacturer="", datasheet_url="", **_kwargs):
            pages = ORIGINAL_PAGES if mpn == "RES10K" else CANDIDATE_PAGES
            document = {
                "available": True,
                "pages": pages,
                "source_type": "datasheet_pdf",
                "source_name": "Linked datasheet",
                "extraction_method": "native_pdf_text",
                "final_url": datasheet_url,
            }
            return {
                "mpn": mpn,
                "manufacturer": manufacturer,
                "sources": [
                    {
                        "source": "linked_datasheet",
                        "source_type": "manufacturer_or_supplier_datasheet",
                        "url": datasheet_url,
                        "status": "available",
                        "detail": f"Extracted text names {manufacturer} {mpn}.",
                        "identity_verified": True,
                    }
                ],
                "documents": [document],
                "verified_documents": [document],
                "primary_document": document,
                "identity": {
                    "attached": True,
                    "verified": True,
                    "mpn_verified": True,
                    "manufacturer_verified": True,
                    "reason": f"Extracted text names {manufacturer} {mpn}.",
                },
            }

        with patch("src.parts_compare.lookup_part_for_compare", side_effect=[original, candidate]):
            with patch(
                "src.compare_evidence_search.gather_part_evidence",
                side_effect=_gather,
            ) as gathered:
                result = run_compare_parts("RES10K", "RES10KE")
        self.assertEqual(gathered.call_count, 2)
        linked = {row["Attribute"]: row for row in result["comparison"]["rows"]}
        self.assertEqual(linked["Resistance"]["Part A"], "10 kOhm")
        self.assertEqual(result["comparison"]["counts"], counts)
        self.assertEqual(len(result["comparison"]["evidence_sources"]["part_a"]), 1)

    def test_datasheet_for_a_different_mpn_or_manufacturer_is_not_used(self):
        original = _rheostat("RES10K")
        candidate = _rheostat("RES10KE")
        swapped = build_parts_comparison(
            original,
            candidate,
            part_a_mpn="RES10K",
            part_b_mpn="RES10KE",
            datasheet_a={"available": True, "pages": CANDIDATE_PAGES},
            datasheet_b={"available": True, "pages": ORIGINAL_PAGES},
        )
        resistance = next(row for row in swapped["rows"] if row["Attribute"] == "Resistance")
        self.assertNotEqual(resistance["Part A"], "10 kOhm")
        self.assertNotEqual(resistance["Part B"], "10 kOhm")
        self.assertIn("does not name the exact part number RES10K", resistance["Evidence"])
        self.assertIn("does not name the exact part number RES10KE", resistance["Evidence"])
        self.assertFalse(swapped["datasheet_identity"]["part_a"]["verified"])

        unnamed = [
            {**page, "text": str(page["text"]).replace("Ohmite ", "")}
            for page in ORIGINAL_PAGES
        ]
        rejected = build_parts_comparison(
            original,
            candidate,
            part_a_mpn="RES10K",
            part_b_mpn="RES10KE",
            datasheet_a={"available": True, "pages": unnamed},
            datasheet_b={"available": True, "pages": CANDIDATE_PAGES},
        )
        rejected_resistance = next(row for row in rejected["rows"] if row["Attribute"] == "Resistance")
        self.assertNotEqual(rejected_resistance["Part A"], "10 kOhm")
        self.assertIn("does not name Ohmite", rejected_resistance["Evidence"])
        self.assertFalse(rejected["datasheet_identity"]["part_a"]["manufacturer_verified"])

    def test_semiconductor_gate_still_requires_package_and_pins(self):
        gate = assess_part_compatibility(
            {"description": "Operational amplifier", "package": "SOIC-8", "pin_count": 8},
            {"description": "Timer", "package": "PDIP-8", "pin_count": 8},
        )
        self.assertTrue(gate["pin_count_applicable"])
        self.assertTrue(gate["package_mismatch"])
        self.assertIn("CRITICAL: Physical footprint change required.", gate["critical_warnings"])

    def test_product_page_evidence_requires_identity_and_records_blocked_sources(self):
        from unittest.mock import patch

        from src.compare_evidence_search import (
            PROVIDER_HTTP_BLOCKED,
            PROVIDER_NOT_CONFIGURED,
            _html_to_product_text,
            gather_part_evidence,
        )

        html = """
        <html><body>
        <span id='cds-product-number'>RES10KE</span>
        <table>
          <tr><td id='cds-al-ohms'>Ohms Value</td><td id='cds-av-ohms'>10000</td></tr>
          <tr><td id='cds-al-watts'>Watts</td><td id='cds-av-watts'>12.50</td></tr>
        </table>
        Ohmite Manufacturing
        </body></html>
        """
        text = _html_to_product_text(html)
        self.assertIn("Model: RES10KE", text)
        self.assertIn("Ohms Value: 10000", text)
        self.assertIn("Manufacturer: Ohmite", text)

        class _Resp:
            def __init__(self, status_code, text="", content=b"", url=""):
                self.status_code = status_code
                self.text = text
                self.content = content or text.encode()
                self.url = url
                self.headers = {"Content-Type": "text/html"}

        class _Session:
            max_redirects = 5

            def get(self, url, **_kwargs):
                if "digikey" in url:
                    return _Resp(403, "blocked RES10K", url=url)
                if "mouser" in url or "newark" in url:
                    return _Resp(200, "<html>search</html>", url=url)
                if url.endswith("/RES10KE"):
                    return _Resp(200, html, url=url)
                if url.endswith("/RES10K"):
                    return _Resp(404, "missing", url=url)
                if url.endswith(".pdf"):
                    return _Resp(200, "%PDF", content=b"%PDF-fake", url=url)
                return _Resp(404, "missing", url=url)

        with patch("src.compare_evidence_search.requests.Session", return_value=_Session()):
            with patch("src.compare_evidence_search._public_datasheet_url", return_value=True):
                with patch(
                    "src.compare_evidence_search.extract_datasheet_text",
                    return_value={
                        "available": True,
                        "pages": [
                            {
                                "page": 1,
                                "text": "Ohmite rheostats family overview without this order code.",
                            }
                        ],
                        "final_url": "https://www.ohmite.com/assets/files/Datasheets/rheostats.pdf",
                    },
                ):
                    evidence = gather_part_evidence(
                        mpn="RES10KE",
                        manufacturer="Ohmite",
                        datasheet_url="https://www.ohmite.com/assets/files/Datasheets/rheostats.pdf",
                        product_detail_url="https://www.ohmite.com/catalog/rheostats/RES10KE",
                    )
        self.assertTrue(
            any(
                row["source_type"] == "authorized_distributor_api"
                and row["status"] == PROVIDER_NOT_CONFIGURED
                for row in evidence["sources"]
            )
        )
        self.assertTrue(
            any(
                "digikey" in str(row["source_type"])
                and row["status"] == PROVIDER_HTTP_BLOCKED
                for row in evidence["sources"]
            )
        )
        self.assertTrue(evidence["identity"]["verified"])
        self.assertTrue(
            any(
                doc.get("source_type") == "manufacturer_product_page"
                for doc in evidence["verified_documents"]
            )
        )

        with patch("src.compare_evidence_search.requests.Session", return_value=_Session()):
            with patch("src.compare_evidence_search._public_datasheet_url", return_value=True):
                missing = gather_part_evidence(
                    mpn="RES10K",
                    manufacturer="Ohmite",
                    datasheet_url="",
                    product_detail_url="https://www.ohmite.com/catalog/rheostats/RES10K",
                    probe_distributor_pages=False,
                )
        self.assertFalse(missing["identity"]["verified"])
        self.assertTrue(
            any(
                row["status"] == "not_found" and "RES10K" in row.get("url", "")
                for row in missing["sources"]
            )
        )

    def test_product_page_volts_and_diameter_keep_source_wording(self):
        from src.datasheet_comparison import build_pdf_field_evidence
        from src.parts_compare import lookup_part_for_compare
        from unittest.mock import patch

        doc = {
            "available": True,
            "pages": [
                {
                    "page": "attributes",
                    "document": "Manufacturer product page",
                    "text": (
                        "Model: RES10KE\nManufacturer: Ohmite\n"
                        "Diameter: 0.875\nOhms Value: 10000\nWatts: 12.50\n"
                        "Volts: 305.000\nConstruction: Wirewound"
                    ),
                }
            ],
            "source_type": "manufacturer_product_page",
            "final_url": "https://www.ohmite.com/catalog/rheostats/RES10KE",
        }
        rows = build_pdf_field_evidence(
            {"pages": []},
            doc,
            "Potentiometer / rheostat",
            candidate_mpn="RES10KE",
        )
        by_key = {row["Key"]: row for row in rows}
        self.assertEqual(by_key["max_working_voltage"]["Attribute"], "Volts")
        self.assertEqual(by_key["max_working_voltage"]["Candidate PDF value"], "305.000")
        self.assertEqual(by_key["max_working_voltage"]["Candidate PDF evidence"], "Volts: 305.000")
        self.assertNotIn("RMS", by_key["max_working_voltage"]["Candidate PDF evidence"])
        self.assertEqual(by_key["diameter"]["Attribute"], "Diameter")
        self.assertEqual(by_key["diameter"]["Candidate PDF value"], "0.875")
        self.assertEqual(by_key["diameter"]["Candidate PDF evidence"], "Diameter: 0.875")
        self.assertEqual(by_key["body_dimensions"]["Candidate PDF value"], "Not found")

        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            return_value={
                "manufacturer": "Ohmite",
                "manufacturer_part_number": "RES10K",
                "catalog_fixture": True,
                "evidence_fixture": True,
                "test_fixture": True,
                "mounting_style": "[Test fixture] Panel Mount",
                "lifecycle_status": "[Test fixture] Active",
                "lifecycle_evidence": [
                    {"source": "Supplier A", "status": "Active", "retrieved_at": "2024-01-02"}
                ],
            },
        ):
            looked_up = lookup_part_for_compare("RES10K")
        # Stripping flags alone is not enough: fixture Mounting/Lifecycle values
        # must be cleared so they cannot appear as unlabeled catalog evidence.
        self.assertNotIn("catalog_fixture", looked_up)
        self.assertNotIn("evidence_fixture", looked_up)
        self.assertNotIn("test_fixture", looked_up)
        self.assertNotIn("mounting_style", looked_up)
        self.assertNotIn("lifecycle_status", looked_up)
        self.assertNotIn("lifecycle_evidence", looked_up)

        fixture_compare = build_parts_comparison(
            _rheostat("RES10K", catalog_fixture=True, lifecycle_status="Active"),
            _rheostat("RES10KE", catalog_fixture=True, lifecycle_status="Active"),
            part_a_mpn="RES10K",
            part_b_mpn="RES10KE",
        )
        mounting = next(row for row in fixture_compare["rows"] if row["Attribute"] == "Mounting")
        self.assertTrue(str(mounting["Part A"]).startswith("[Test fixture]"))
        self.assertTrue(
            fixture_compare["fixture_production_isolation"][
                "production_lookup_clears_fixture_mounting_lifecycle"
            ]
        )
        self.assertIn("Mounting", fixture_compare["fixture_kpi"]["fixture_attributes"])

    def test_fixture_mounting_lifecycle_cannot_enter_production_compare_path(self):
        """Production run_compare_parts must not keep synthetic Mounting/Lifecycle stubs."""
        from unittest.mock import patch

        from src.compare_evidence_search import PROVIDER_DISCOVERY_LEAD
        from src.parts_compare import run_compare_parts

        poisoned_a = {
            "manufacturer": "Ohmite",
            "manufacturer_part_number": "RES10K",
            "description": "Ohmite rheostat RES10K",
            "catalog_fixture": True,
            "evidence_fixture": True,
            "mounting_style": "[Test fixture] Panel Mount",
            "lifecycle_status": "[Test fixture] Conflicting supplier data",
            "lifecycle_conflict": True,
            "lifecycle_evidence": [
                {"source": "Supplier A", "status": "Active", "retrieved_at": "2024-01-02"},
                {"source": "Supplier B", "status": "Obsolete", "retrieved_at": "2024-03-04"},
            ],
            "datasheet_url": "https://www.ohmite.com/assets/files/Datasheets/rheostats.pdf",
        }
        poisoned_b = {
            "manufacturer": "Ohmite",
            "manufacturer_part_number": "RES10KE",
            "description": "Ohmite rheostat RES10KE",
            "catalog_fixture": True,
            "mounting_style": "[Test fixture] Panel Mount",
            "lifecycle_status": "[Test fixture] Active",
            "datasheet_url": "https://www.ohmite.com/assets/files/Datasheets/rheostats.pdf",
        }
        empty_evidence = {
            "mpn": "",
            "manufacturer": "Ohmite",
            "sources": [],
            "documents": [],
            "verified_documents": [],
            "primary_document": None,
            "identity": {
                "attached": False,
                "verified": False,
                "mpn_verified": False,
                "manufacturer_verified": False,
                "reason": "No datasheet was attached for this part.",
            },
        }

        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            side_effect=[poisoned_a, poisoned_b],
        ):
            with patch(
                "src.compare_evidence_search.gather_part_evidence",
                return_value=empty_evidence,
            ):
                # Production path: lookup_part_for_compare → sanitize → compare.
                result = run_compare_parts("RES10K", "RES10KE")

        self.assertEqual(result["status"], "completed")
        comparison = result["comparison"]
        self.assertEqual(comparison["fixture_kpi"]["fixture_row_count"], 0)
        self.assertEqual(comparison["fixture_kpi"]["fixture_attributes"], [])
        mounting = next(row for row in comparison["rows"] if row["Attribute"] == "Mounting")
        lifecycle = next(row for row in comparison["rows"] if row["Attribute"] == "Lifecycle")
        for row in (mounting, lifecycle):
            self.assertNotIn("[Test fixture]", str(row.get("Part A") or ""))
            self.assertNotIn("[Test fixture]", str(row.get("Part B") or ""))
            self.assertNotIn("test fixture", str(row.get("Evidence") or "").casefold())
            self.assertFalse(row.get("FixtureRow"))
        # Fixture values themselves must not survive as unlabeled Panel Mount / Active.
        self.assertNotEqual(mounting["Part A"], "Panel Mount")
        self.assertNotEqual(mounting["Part B"], "Panel Mount")
        self.assertTrue(str(mounting["Part A"]).casefold().startswith("not stated"))
        self.assertTrue(str(mounting["Part B"]).casefold().startswith("not stated"))
        self.assertTrue(
            comparison["fixture_production_isolation"][
                "production_lookup_clears_fixture_mounting_lifecycle"
            ]
        )

        # DigiKey indexed RES10K listing is a discovery lead only when API is unavailable.
        from src.compare_evidence_search import gather_part_evidence

        with patch("src.compare_evidence_search.requests.Session") as session_cls:
            session = session_cls.return_value
            session.max_redirects = 5

            class _Blocked:
                status_code = 403
                text = "blocked RES10K"
                content = b"blocked"
                url = "https://www.digikey.com/en/products/detail/ohmite/RES10K/258353"
                headers = {"Content-Type": "text/html"}

            session.get.return_value = _Blocked()
            with patch("src.compare_evidence_search._public_datasheet_url", return_value=True):
                with patch(
                    "src.compare_evidence_search.extract_datasheet_text",
                    return_value={"available": False, "pages": [], "reason": "unavailable"},
                ):
                    evidence = gather_part_evidence(
                        mpn="RES10K",
                        manufacturer="Ohmite",
                        datasheet_url="",
                        product_detail_url="",
                        probe_distributor_pages=False,
                    )
        lead_rows = [
            row
            for row in evidence["sources"]
            if row.get("source_type") == "digikey_indexed_listing_lead"
        ]
        self.assertEqual(len(lead_rows), 1)
        self.assertEqual(lead_rows[0]["status"], PROVIDER_DISCOVERY_LEAD)
        self.assertIn("/RES10K/258353", lead_rows[0]["url"])
        self.assertFalse(lead_rows[0]["identity_verified"])
        self.assertFalse(evidence["identity"]["verified"])
        self.assertTrue(
            any(
                row.get("source_type") == "authorized_distributor_api_lookup"
                and row.get("status") == "not_configured"
                for row in evidence["sources"]
            )
        )
        digikey_api = next(
            row
            for row in evidence["sources"]
            if row.get("source_type") == "authorized_distributor_api_lookup"
            and row.get("source") == "DigiKey"
        )
        self.assertIn("DIGIKEY_CLIENT_ID", digikey_api["detail"])
        self.assertIn("DIGIKEY_CLIENT_SECRET", digikey_api["detail"])

    def test_uploaded_exact_mpn_datasheet_cites_res10k_only_when_verified(self):
        """Upload path cites RES10K only after Ohmite + exact MPN identity."""
        from unittest.mock import patch

        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        from src.parts_compare import document_from_uploaded_datasheet

        def _pdf(lines: list[str]) -> bytes:
            buffer = BytesIO()
            pdf = canvas.Canvas(buffer, pagesize=letter)
            y = 720
            for line in lines:
                pdf.drawString(72, y, line[:110])
                y -= 14
            pdf.showPage()
            pdf.save()
            return buffer.getvalue()

        verified_doc = document_from_uploaded_datasheet(
            _pdf(
                [
                    "Ohmite RES10K",
                    "Rheostat",
                    "Resistance 10 kOhm",
                    "Power rating 12.5 W",
                    "Volts 305",
                    "Diameter 0.875",
                ]
            ),
            filename="RES10K-upload.pdf",
            manufacturer="Ohmite",
            mpn="RES10K",
        )
        self.assertTrue(verified_doc["available"])
        self.assertTrue(verified_doc["upload_identity"]["verified"])
        self.assertTrue(verified_doc["evidence_sources"][0]["identity_verified"])

        rejected_doc = document_from_uploaded_datasheet(
            _pdf(
                [
                    "Ohmite rheostat family overview",
                    "Resistance 10 kOhm",
                    "Power rating 12.5 W",
                ]
            ),
            filename="family-overview.pdf",
            manufacturer="Ohmite",
            mpn="RES10K",
        )
        self.assertTrue(rejected_doc["available"])
        self.assertFalse(rejected_doc["upload_identity"]["verified"])
        self.assertFalse(rejected_doc["evidence_sources"][0]["identity_verified"])

        empty_evidence = {
            "mpn": "RES10K",
            "manufacturer": "Ohmite",
            "sources": [
                {
                    "source": "DigiKey",
                    "source_type": "authorized_distributor_api_lookup",
                    "status": "not_configured",
                    "detail": "DigiKey API credentials are not configured.",
                    "identity_verified": False,
                }
            ],
            "documents": [],
            "verified_documents": [],
            "primary_document": None,
            "identity": {
                "attached": False,
                "verified": False,
                "mpn_verified": False,
                "manufacturer_verified": False,
                "reason": "No datasheet was attached for this part.",
            },
        }

        def _lookup(mpn: str):
            token = str(mpn or "").strip().upper()
            return {
                "manufacturer": "Ohmite",
                "manufacturer_part_number": token,
                "description": f"Ohmite rheostat {token}",
            }

        with patch(
            "integrations.supplier_aggregator.get_best_part_data",
            side_effect=_lookup,
        ):
            with patch(
                "src.compare_evidence_search.gather_part_evidence",
                return_value=empty_evidence,
            ):
                verified_run = run_compare_parts(
                    "RES10K",
                    "RES10KE",
                    datasheet_uploads={"a": {"bytes": _pdf(
                        [
                            "Ohmite RES10K",
                            "Resistance 10 kOhm",
                            "Power rating 12.5 W",
                            "Volts 305",
                            "Diameter 0.875",
                        ]
                    ), "filename": "RES10K-upload.pdf"}},
                    extract_linked_datasheets=True,
                )
                rejected_run = run_compare_parts(
                    "RES10K",
                    "RES10KE",
                    datasheet_uploads={"a": {"bytes": _pdf(
                        [
                            "Ohmite family overview",
                            "Resistance 10 kOhm",
                        ]
                    ), "filename": "wrong.pdf"}},
                    extract_linked_datasheets=True,
                )

        verified_cmp = verified_run["comparison"]
        self.assertTrue(verified_cmp["datasheet_identity"]["part_a"]["verified"])
        resistance = next(
            row for row in verified_cmp["rows"] if row["Attribute"] == "Resistance"
        )
        self.assertIn("10", resistance["Part A"])
        self.assertNotIn("Not stated", resistance["Part A"])
        self.assertIn("upload", resistance["Evidence"].casefold())

        rejected_cmp = rejected_run["comparison"]
        self.assertFalse(rejected_cmp["datasheet_identity"]["part_a"]["verified"])
        resistance_rejected = next(
            row for row in rejected_cmp["rows"] if row["Attribute"] == "Resistance"
        )
        self.assertTrue(
            str(resistance_rejected["Part A"]).casefold().startswith("not stated")
        )
        blockers = rejected_cmp["access_blockers"]
        self.assertIn("RES10K", blockers["unverified_mpns"])
        self.assertTrue(
            any(
                "DIGIKEY_CLIENT_ID" in (row.get("required_configuration") or [])
                and "DIGIKEY_CLIENT_SECRET" in (row.get("required_configuration") or [])
                for row in blockers["blockers"]
            )
        )
        self.assertTrue(
            any(
                row.get("provider") == "Exact-MPN datasheet upload"
                for row in blockers["permitted_paths"]
            )
        )

    def test_arrow_authorized_page_cites_after_ohmite_res10k_identity(self):
        """Arrow HTML values are cited only after Ohmite + exact RES10K identity."""
        from unittest.mock import patch

        from src.compare_evidence_search import (
            PROVIDER_HTTP_BLOCKED,
            PROVIDER_TIMEOUT,
            _document_from_html,
            _probe_authorized_distributor_product_page,
            gather_part_evidence,
        )
        from src.datasheet_comparison import build_pdf_field_evidence, verify_datasheet_identity
        from src.parts_compare import build_parts_comparison

        arrow_html = """
        <html><body>
        <h1>RES10K</h1>
        <div>Ohmite</div>
        <script type="application/ld+json">
        {"@type":"Product","mpn":"RES10K","brand":{"name":"Ohmite"},
         "additionalProperty":[
           {"@type":"PropertyValue","name":"Resistance Value (Ohm)","value":"10K"},
           {"@type":"PropertyValue","name":"Tolerance","value":"10%"},
           {"@type":"PropertyValue","name":"Maximum Voltage Rating (V)","value":"305"},
           {"@type":"PropertyValue","name":"Power Rating (W)","value":"12.5"},
           {"@type":"PropertyValue","name":"Technology","value":"Wirewound"},
           {"@type":"PropertyValue","name":"Termination Style","value":"Solder Lug"},
           {"@type":"PropertyValue","name":"Mounting","value":"Panel Mount"},
           {"@type":"PropertyValue","name":"Family/Series","value":"R"}
         ]}
        </script>
        <table>
          <tr><th>Resistance Value (Ohm)</th><td>10K</td></tr>
          <tr><th>Maximum Voltage Rating (V)</th><td>305</td></tr>
          <tr><th>Power Rating (W)</th><td>12.5</td></tr>
          <tr><th>Mounting</th><td>Panel Mount</td></tr>
        </table>
        </body></html>
        """
        wrong_mpn_html = arrow_html.replace("RES10K", "RES10KE")
        doc = _document_from_html(
            html=arrow_html,
            url="https://www.arrow.com/en/products/res10k/ohmite",
            source_name="Arrow authorized product page",
            source_type="arrow_authorized_product_page",
            extraction_method="authorized_distributor_product_html",
        )
        identity = verify_datasheet_identity(doc, manufacturer="Ohmite", mpn="RES10K")
        self.assertTrue(identity["verified"])
        self.assertIn("Resistance Value (Ohm)", "\n".join(doc["source_field_labels"]))
        self.assertNotIn("RMS", "\n".join(p["text"] for p in doc["pages"]))

        wrong = _document_from_html(
            html=wrong_mpn_html,
            url="https://www.arrow.com/en/products/res10ke/ohmite",
            source_name="Arrow authorized product page",
            source_type="arrow_authorized_product_page",
        )
        self.assertFalse(
            verify_datasheet_identity(wrong, manufacturer="Ohmite", mpn="RES10K")["verified"]
        )

        res10ke_doc = {
            "available": True,
            "pages": [
                {
                    "page": "attributes",
                    "document": "Manufacturer product page",
                    "text": (
                        "Model: RES10KE\nManufacturer: Ohmite\n"
                        "Diameter: 0.875\nOhms Value: 10000\nWatts: 12.50\n"
                        "Volts: 305.000\nConstruction: Wirewound\n"
                        "Resistance: 10000\nPower rating: 12.50\nElement type: Wirewound"
                    ),
                }
            ],
            "source_type": "manufacturer_product_page",
            "source_name": "Manufacturer product page",
            "extraction_method": "manufacturer_product_html",
            "final_url": "https://www.ohmite.com/catalog/rheostats/RES10KE",
            "source_url": "https://www.ohmite.com/catalog/rheostats/RES10KE",
            "source_field_labels": [
                "Model",
                "Manufacturer",
                "Diameter",
                "Ohms Value",
                "Watts",
                "Volts",
                "Construction",
            ],
        }
        field_rows = build_pdf_field_evidence(
            doc,
            res10ke_doc,
            "Potentiometer / rheostat",
            original_mpn="RES10K",
            candidate_mpn="RES10KE",
        )
        by_key = {row["Key"]: row for row in field_rows}
        self.assertEqual(by_key["resistance"]["Original PDF value"], "10K")
        self.assertIn("Resistance Value (Ohm)", by_key["resistance"]["Original PDF evidence"])
        self.assertEqual(by_key["max_working_voltage"]["Original PDF value"], "305")
        self.assertNotIn("RMS", by_key["max_working_voltage"]["Original PDF evidence"])
        self.assertIn(
            "Maximum Voltage Rating",
            by_key["max_working_voltage"]["Original PDF evidence"],
        )
        self.assertEqual(by_key["max_working_voltage"]["Candidate PDF value"], "305.000")
        self.assertIn("Volts:", by_key["max_working_voltage"]["Candidate PDF evidence"])

        compare = build_parts_comparison(
            _rheostat("RES10K"),
            _rheostat("RES10KE"),
            part_a_mpn="RES10K",
            part_b_mpn="RES10KE",
            datasheet_a=doc,
            datasheet_b=res10ke_doc,
            extract_linked_datasheets=False,
        )
        self.assertTrue(compare["datasheet_identity"]["part_a"]["verified"])
        self.assertTrue(compare["datasheet_identity"]["part_b"]["verified"])
        resistance = next(row for row in compare["rows"] if row["Attribute"] == "Resistance")
        volts = next(row for row in compare["rows"] if row["Attribute"] == "Volts")
        self.assertEqual(resistance["Part A"], "10K")
        self.assertEqual(resistance["Part B"], "10000")
        self.assertIn("Resistance Value (Ohm)", resistance["Evidence"])
        for internal_term in (
            "api",
            "source field label",
            "source url",
            "extraction method",
            "native pdf text",
            "supplier catalog",
        ):
            self.assertNotIn(internal_term, " ".join(row["Evidence"] for row in compare["rows"]).casefold())
        self.assertEqual(volts["Part A"], "305")
        self.assertEqual(volts["Part B"], "305.000")
        self.assertNotIn("RMS", volts["Evidence"])
        # KPI / row agreement for material resistance wording difference.
        self.assertEqual(
            compare["counts"]["compatible"]
            + compare["counts"]["material_difference"]
            + compare["counts"]["needs_data"],
            len(compare["rows"]),
        )

        # Fail closed: timeout and Cloudflare bodies never become evidence.
        with patch(
            "src.compare_evidence_search._fetch_public_https",
            return_value=(PROVIDER_TIMEOUT, "The source timed out.", "https://www.arrow.com/en/products/res10k/ohmite"),
        ):
            row, probed = _probe_authorized_distributor_product_page(
                source_type="arrow_authorized_product_page",
                url="https://www.arrow.com/en/products/res10k/ohmite",
                manufacturer="Ohmite",
                mpn="RES10K",
            )
        self.assertEqual(row["status"], PROVIDER_TIMEOUT)
        self.assertIsNone(probed)
        self.assertTrue(row.get("retrieved_at"))

        with patch(
            "src.compare_evidence_search._fetch_public_https",
            return_value=(
                PROVIDER_HTTP_BLOCKED,
                "HTTP access challenge / Cloudflare interstitial. The body was not used as evidence.",
                "https://www.galco.com/buy/Ohmite/RES10K",
            ),
        ):
            galco_row, galco_doc = _probe_authorized_distributor_product_page(
                source_type="galco_authorized_product_page",
                url="https://www.galco.com/buy/Ohmite/RES10K",
                manufacturer="Ohmite",
                mpn="RES10K",
            )
        self.assertEqual(galco_row["status"], PROVIDER_HTTP_BLOCKED)
        self.assertIsNone(galco_doc)

        # gather_part_evidence records authorized probes before DigiKey HTML.
        def _fake_fetch(url, referer=""):
            if "arrow.com" in url:
                return PROVIDER_TIMEOUT, "The source timed out.", url
            if "galco.com" in url:
                return (
                    PROVIDER_HTTP_BLOCKED,
                    "HTTP access challenge / Cloudflare interstitial. The body was not used as evidence.",
                    url,
                )
            return PROVIDER_HTTP_BLOCKED, "HTTP 403. The body was not used as evidence.", url

        with patch("src.compare_evidence_search._fetch_public_https", side_effect=_fake_fetch):
            with patch(
                "src.compare_evidence_search._try_digikey_api_exact_mpn",
                return_value=(
                    {
                        "source": "DigiKey",
                        "source_type": "authorized_distributor_api_lookup",
                        "status": "not_configured",
                        "detail": "DigiKey API credentials are not configured.",
                        "identity_verified": False,
                        "url": "",
                        "retrieved_at": "2026-01-01T00:00:00Z",
                    },
                    None,
                ),
            ):
                evidence = gather_part_evidence(
                    mpn="RES10K",
                    manufacturer="Ohmite",
                    datasheet_url="",
                    product_detail_url="",
                    probe_distributor_pages=True,
                )
        self.assertFalse(evidence["identity"]["verified"])
        self.assertTrue(
            any(
                row.get("source_type") == "arrow_authorized_product_page"
                and row.get("status") == PROVIDER_TIMEOUT
                for row in evidence["sources"]
            )
        )
        self.assertTrue(
            any(
                row.get("source_type") == "galco_authorized_product_page"
                and row.get("status") == PROVIDER_HTTP_BLOCKED
                for row in evidence["sources"]
            )
        )

    def test_rs_group_search_is_lead_and_detail_403_fails_closed(self):
        """RS stock search is a lead; HTTP 403 detail pages never become evidence."""
        from unittest.mock import patch

        from src.compare_evidence_search import (
            PROVIDER_DISCOVERY_LEAD,
            PROVIDER_HTTP_BLOCKED,
            _probe_authorized_distributor_product_page,
            gather_part_evidence,
        )

        with patch(
            "src.compare_evidence_search._fetch_public_https",
            return_value=(
                PROVIDER_HTTP_BLOCKED,
                "HTTP 403. The body was not used as evidence.",
                "https://uk.rs-online.com/web/p/potentiometers/70585847",
            ),
        ):
            row, doc = _probe_authorized_distributor_product_page(
                source_type="rs_group_authorized_product_page",
                url="https://uk.rs-online.com/web/p/potentiometers/70585847",
                manufacturer="Ohmite",
                mpn="RES10K",
            )
        self.assertEqual(row["source"], "RS Group")
        self.assertEqual(row["status"], PROVIDER_HTTP_BLOCKED)
        self.assertIsNone(doc)
        self.assertTrue(row.get("retrieved_at"))

        def _fake_fetch(url, referer=""):
            if "rs-online.com" in url and "/web/p/" in url:
                return (
                    PROVIDER_HTTP_BLOCKED,
                    "HTTP 403. The body was not used as evidence.",
                    url,
                )
            if "rs-online.com" in url and "product/ohmite" in url:
                return (
                    PROVIDER_HTTP_BLOCKED,
                    "HTTP 403. The body was not used as evidence.",
                    url,
                )
            return PROVIDER_HTTP_BLOCKED, "HTTP 403. The body was not used as evidence.", url

        with patch("src.compare_evidence_search._fetch_public_https", side_effect=_fake_fetch):
            with patch(
                "src.compare_evidence_search._try_digikey_api_exact_mpn",
                return_value=(
                    {
                        "source": "DigiKey",
                        "source_type": "authorized_distributor_api_lookup",
                        "status": "not_configured",
                        "detail": "DigiKey API credentials are not configured.",
                        "identity_verified": False,
                        "url": "",
                        "retrieved_at": "2026-01-01T00:00:00Z",
                    },
                    None,
                ),
            ):
                evidence = gather_part_evidence(
                    mpn="RES10K",
                    manufacturer="Ohmite",
                    datasheet_url="",
                    product_detail_url="",
                    probe_distributor_pages=True,
                )
        self.assertFalse(evidence["identity"]["verified"])
        lead = next(
            row
            for row in evidence["sources"]
            if row.get("source_type") == "rs_group_search_listing_lead"
        )
        self.assertEqual(lead["status"], PROVIDER_DISCOVERY_LEAD)
        self.assertIn("70585847", lead["url"])
        self.assertFalse(lead["identity_verified"])
        self.assertTrue(
            any(
                row.get("source_type") == "rs_group_authorized_product_page"
                and row.get("status") == PROVIDER_HTTP_BLOCKED
                for row in evidence["sources"]
            )
        )


    def test_independent_evidence_probes_run_concurrently_and_keep_input_order(self):
        from src.compare_evidence_search import _parallel_ordered

        barrier = Barrier(3)

        def probe(value):
            try:
                barrier.wait(timeout=1.5)
                return value
            except Exception:
                return None

        self.assertEqual(
            _parallel_ordered(["a", "b", "c"], probe, limit=3),
            ["a", "b", "c"],
        )

    def test_customer_evidence_uses_plain_source_citations_without_internal_terms(self):
        document = {
            "available": True,
            "source_type": "authorized_distributor_api",
            "source_name": "DigiKey authorized API",
            "extraction_method": "authorized_distributor_api",
            "pages": [{
                "page": "DigiKey API",
                "document": "DigiKey authorized API",
                "text": "Manufacturer: Ohmite\nModel: RES10KE\nMounting style: Panel Mount",
            }],
        }
        rows = [{
            "Key": "mounting_style",
            "Attribute": "Mounting",
            "Original": "Panel Mount",
            "Candidate": "Panel Mount",
            "Status": "Match",
            "Evidence": "Panel Mount matches.",
        }]

        merged, identity, _warnings = merge_verified_datasheet_rows(
            rows,
            family="Potentiometer / rheostat",
            document_a=document,
            document_b=None,
            manufacturer_a="Ohmite",
            mpn_a="RES10KE",
            manufacturer_b="Ohmite",
            mpn_b="RES10K",
        )

        evidence = merged[0]["Evidence"].casefold()
        self.assertTrue(identity["part_a"]["verified"])
        self.assertIn("digikey product record", evidence)
        self.assertIn("mounting style: panel mount", evidence)
        for internal_term in ("api", "extraction method", "source field label", "source url"):
            self.assertNotIn(internal_term, evidence)


if __name__ == "__main__":
    unittest.main()
