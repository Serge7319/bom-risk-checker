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
        self.assertIn("MPN-901", alternatives)
        self.assertIn("BOM Risk", EI_TABS)
        self.assertIn("Supply & Availability", EI_TABS)
        self.assertIn("Alternatives", EI_TABS)

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
