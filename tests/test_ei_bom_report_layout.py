import unittest

from src.ui.ei_bom_report import (
    EI_TABS,
    bom_catalog_html,
    detailed_risk_report_html,
    engineering_intelligence_html,
)


PARTS = [
    {
        "mpn": "MPN-001",
        "description": "32-bit Microcontroller",
        "manufacturer": "AlphaSemi",
        "risk_score": 92,
        "risk_level": "High",
        "stock_available": 0,
        "supplier_count": 1,
        "lifecycle_status": "Obsolete",
        "lead_time_weeks": 52,
        "best_source": "Digi-Key",
    },
    {
        "mpn": "MPN-002",
        "description": "Voltage Regulator",
        "manufacturer": "BetaChip",
        "risk_score": 28,
        "risk_level": "Medium",
        "stock_available": 40,
        "supplier_count": 2,
        "lifecycle_status": "Active",
        "best_source": "Mouser",
        "unit_price": "1.20",
    },
]


class EngineeringIntelligenceLayoutTests(unittest.TestCase):
    def test_bom_risk_uses_the_approved_review_structure(self):
        html = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="BOM Risk",
            parts=PARTS,
            health_score=72,
        )
        self.assertIn("Engineering Intelligence", html)
        self.assertIn("Engineering review required", html)
        self.assertIn("Review these components first", html)
        self.assertIn("MPN-001", html)
        self.assertIn("72/100", html)
        self.assertIn("cv-part-photo__image", html)
        self.assertNotIn("Supply & Availability", html)

    def test_supply_and_alternatives_keep_the_same_report_family(self):
        supply = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Supply & Availability",
            parts=PARTS,
        )
        alternatives = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Alternatives",
            parts=PARTS,
            alternatives=[{"original_mpn": "MPN-001", "alternative_mpn": "MPN-901"}],
        )
        self.assertIn("Supply and availability", supply)
        self.assertIn("Digi-Key", supply)
        self.assertIn("cv-part-photo__image", supply)
        self.assertIn("MPN-901", alternatives)
        self.assertIn("cv-part-photo", alternatives)
        empty = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Alternatives",
            parts=PARTS,
            alternatives=[],
        )
        self.assertIn(
            "No approved alternative is stored for this BOM yet. Use Find a replacement to qualify one.",
            empty,
        )
        self.assertNotIn("cv-part-photo", empty)
        self.assertIn("BOM Risk", EI_TABS)
        self.assertIn("Supply & Availability", EI_TABS)
        self.assertIn("Alternatives", EI_TABS)

    def test_tables_use_catalog_photos_and_the_same_placeholder(self):
        catalog = "https://media.digikey.com/Photos/Texas%20Instruments/LM358.jpg"
        parts = [dict(PARTS[0], image_url=catalog), PARTS[1]]
        html = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Lifecycle",
            parts=parts,
        )
        self.assertIn(f'src="{catalog}"', html)
        self.assertIn("Product photo for MPN-001", html)
        self.assertIn("Representative component image; actual part may vary", html)
        self.assertNotIn("Product photo for MPN-002", html)
        self.assertIn('data-illustration="ic"', html)
        self.assertNotIn("https://example.test", html)

    def test_detailed_risk_report_expands_the_selected_part(self):
        html = detailed_risk_report_html(
            bom_name="Sample BOM",
            analyzed_on="Apr 26, 2025",
            parts=PARTS,
            expanded_mpn="MPN-001",
        )
        self.assertIn("Detailed Risk Report", html)
        self.assertIn("Risk drivers", html)
        self.assertIn("Recommended action", html)
        self.assertIn("MPN-001", html)

    def test_review_alternative_parts_action_is_a_prefilled_link(self):
        report = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="BOM Risk",
            parts=PARTS,
            analysis_id="analysis-1",
        )
        self.assertIn("Review alternative parts</a>", report)
        self.assertIn("page=Alternative%20Finder", report)
        self.assertIn("original_part=MPN-001", report)
        self.assertIn("analysis_id=analysis-1", report)
        self.assertRegex(report, r"prefill_id=[a-f0-9]{32}")
        again = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="BOM Risk",
            parts=PARTS,
            analysis_id="analysis-1",
        )
        first_token = __import__("re").search(r"prefill_id=([a-f0-9]{32})", report).group(1)
        next_token = __import__("re").search(r"prefill_id=([a-f0-9]{32})", again).group(1)
        self.assertNotEqual(first_token, next_token)

    def test_review_alternative_handoff_prefills_the_clicked_part(self):
        import streamlit as st
        from src.ui.navigation import (
            apply_alternative_finder_prefill,
            consume_alternative_finder_context,
        )

        st.session_state.clear()
        st.session_state["alternative_finder_nav_consumed_token"] = "analysis-1::MPN001"
        query = {
            "original_part": "MPN-001",
            "analysis_id": "analysis-1",
            "prefill_id": "fresh-click-id",
            "manufacturer": "AlphaSemi",
        }
        context = consume_alternative_finder_context(
            lambda key, default="": query.get(key, default)
        )
        apply_alternative_finder_prefill(context or {})
        self.assertEqual(st.session_state["alternative_original_part"], "MPN-001")
        self.assertEqual(st.session_state["alternative_original_manufacturer"], "AlphaSemi")

    def test_detailed_risk_rows_keep_package_for_the_correct_fallback_photo(self):
        from src.part_images import part_image_markup, part_image_source
        from src.ui.ei_bom_report import _part_rows

        row = _part_rows(
            [{
                "mpn": "CAP-TH",
                "description": "Radial through-hole capacitor",
                "category": "Capacitor",
                "package": "Radial through-hole",
            }]
        )[0]
        self.assertEqual(row["package"], "Radial through-hole")
        expected = part_image_source(
            "",
            "CAP-TH",
            category="Capacitor",
            part={"category": "Capacitor", "package": "Radial through-hole"},
        )
        self.assertIn(f'src="{expected}"', part_image_markup("", "CAP-TH", part=row))

    def test_new_contextual_click_is_not_blocked_by_an_old_consumed_mpn(self):
        from src.alternative_finder_state import should_apply_alternative_finder_prefill

        state = {"alternative_finder_nav_consumed_token": "analysis-1::MPN001"}
        self.assertTrue(
            should_apply_alternative_finder_prefill(
                state,
                mpn="MPN-001",
                analysis_id="analysis-1",
                navigation_id="new-click-identifier",
            )
        )

    def test_saved_markup_is_not_shown_as_a_component_description(self):
        markup = (
            "<p>Manufacturer AlphaSemi</p><p>Best source Digi-Key</p>"
            "<p>Lifecycle Obsolete</p>"
        )
        escaped = markup.replace("<", "&lt;").replace(">", "&gt;")
        double_escaped = escaped.replace("&", "&amp;")
        for description in (markup, escaped, double_escaped):
            with self.subTest(description=description[:20]):
                report = detailed_risk_report_html(
                    bom_name="Sample BOM",
                    analyzed_on="Apr 26, 2025",
                    parts=[dict(PARTS[0], description=description)],
                    expanded_mpn="MPN-001",
                )
                self.assertNotIn("<p>Manufacturer AlphaSemi</p><p>Best source Digi-Key", report)
                self.assertNotIn("Manufacturer AlphaSemi Best source Digi-Key Lifecycle Obsolete", report)

    def test_detailed_risk_starts_collapsed_until_a_part_is_selected(self):
        report = detailed_risk_report_html(
            bom_name="Sample BOM",
            analyzed_on="Apr 26, 2025",
            parts=PARTS,
        )
        self.assertNotIn("cv-risk-detail", report)
        selected = detailed_risk_report_html(
            bom_name="Sample BOM",
            analyzed_on="Apr 26, 2025",
            parts=PARTS,
            expanded_mpn="MPN-001",
        )
        self.assertIn("cv-risk-detail", selected)

    def test_cost_insights_does_not_treat_a_zero_price_as_money(self):
        parts = [
            {
                "mpn": "MAX32625ITK+",
                "manufacturer": "Analog Devices",
                "risk_level": "High",
                "risk_reasons": "Lifecycle and single-source exposure require a replacement review.",
                "unit_price": 0.0,
                "stock_available": 0,
            },
            {
                "mpn": "TPS54331D",
                "manufacturer": "Texas Instruments",
                "risk_level": "Medium",
                "risk_reasons": "Lead time is longer than the release window.",
                "unit_price": 1.2,
                "quantity": 10,
                "primary_supplier": "DigiKey",
                "stock_available": 1200,
                "product_url": "https://www.digikey.com/en/products/detail/ti/TPS54331D/1",
            },
        ]
        html = engineering_intelligence_html(
            bom_name="Industrial Controller BOM",
            part_count=2,
            tab="Cost Insights",
            parts=parts,
        )
        self.assertIn("Not recorded", html)
        self.assertNotIn("0.0", html)
        self.assertNotIn("$0.00", html)
        self.assertNotIn(">Best source<", html)
        self.assertIn("Recorded source", html)
        self.assertIn("DigiKey", html)
        self.assertIn("$1.2", html)
        self.assertIn("$12", html)
        self.assertIn("https://www.digikey.com/en/products/detail/ti/TPS54331D/1", html)
        self.assertIn("A distributor comparison is unavailable.", html)
        self.assertNotIn("Not labeled best", html)
        self.assertIn("Lifecycle and single-source exposure require a replacement review.", html)
        self.assertIn("Not calculated", html)
        self.assertIn("Re-run the BOM analysis", html)

    def test_bom_catalog_is_a_list_not_an_intelligence_report(self):
        html = bom_catalog_html(
            [
                {
                    "project_name": "Orion Controller",
                    "filename": "orion_controller_revB.xlsx",
                    "total_parts": 124,
                    "health_score": 90,
                    "high_risk_count": 2,
                    "updated_label": "Aug 26, 2024",
                }
            ]
        )
        self.assertIn("BOMs", html)
        self.assertIn("Orion Controller", html)
        self.assertIn("Healthy", html)
        self.assertNotIn("Engineering review required", html)


if __name__ == "__main__":
    unittest.main()
