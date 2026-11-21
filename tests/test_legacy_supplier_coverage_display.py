from __future__ import annotations

import unittest
import sys
import types
from unittest.mock import patch


class LegacySupplierCoverageDisplayTests(unittest.TestCase):
    def test_row_distinguishes_no_match_outage_and_unconfigured_provider(self):
        from apps.api import legacy_supplier_workflow

        alternative_engine = types.ModuleType("src.alternative_engine")
        alternative_engine.suggest_alternatives_v2 = lambda *_args, **_kwargs: []
        risk_engine = types.ModuleType("src.risk_engine")
        risk_engine.calculate_risk = lambda *_args, **_kwargs: {
            "risk_reasons": [], "risk_level": "Medium", "risk_score": 40
        }

        part = {
            "mpn": "LM358DR",
            "manufacturer_part_number": "LM358DR",
            "bom_manufacturer": "Texas Instruments",
            "supplier_data_verified": True,
            "provider_health": {
                "configured_count": 3,
                "successful_count": 1,
                "responded_count": 2,
                "no_match_count": 1,
                "failed_count": 1,
                "summary_message": "1 exact match; one no match and one unavailable.",
            },
            "all_supplier_results": [
                {"source": "Mouser", "provider_status": "AVAILABLE"},
                {"source": "DigiKey", "provider_status": "PART_NOT_FOUND"},
                {"source": "Newark", "provider_status": "TIMEOUT", "error": "Supplier lookup timed out."},
                {"source": "Nexar Supply", "provider_status": "NOT_CONFIGURED", "error": "Nexar Supply is not configured"},
            ],
        }

        with (
            patch.dict(sys.modules, {
                "src.alternative_engine": alternative_engine,
                "src.risk_engine": risk_engine,
            }),
            patch.object(legacy_supplier_workflow, "_part_data_for_row", return_value=part),
        ):
            row = legacy_supplier_workflow._part_analysis({"mpn": "LM358DR", "manufacturer": "Texas Instruments", "quantity": 1})

        self.assertEqual(
            row["supplier_sources_checked"],
            "2/3 supplier queries responded; 1 exact match(es), 1 no match(es), 1 unavailable",
        )
        details = {item["source"]: item["label"] for item in row["supplier_query_details"]}
        self.assertEqual(details["Mouser"], "Exact MPN and manufacturer match")
        self.assertEqual(details["DigiKey"], "No exact MPN match returned")
        self.assertEqual(details["Newark"], "Supplier unavailable")
        self.assertEqual(details["Nexar Supply"], "Not configured")


if __name__ == "__main__":
    unittest.main()
