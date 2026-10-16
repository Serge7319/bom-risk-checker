from __future__ import annotations

import unittest

from integrations.legacy_mpn_routes import legacy_mpn_route, legacy_route_status


class LegacyMPNRouteTests(unittest.TestCase):
    def test_known_routes_are_exact_and_do_not_strip_suffixes(self):
        route = legacy_mpn_route("AM29F010B-70EC")
        self.assertEqual(route["query_mpns"], ("AM29F010B",))
        self.assertIsNone(legacy_mpn_route("AM29F010B-70E"))
        self.assertIsNone(legacy_mpn_route("UNRELATED-PART"))

    def test_related_result_is_labeled_review_only_and_keeps_evidence_separate(self):
        status = legacy_route_status(
            "IRF540N",
            [{"mpn": "IRF540NPBF", "supplier": "DigiKey"}],
        )
        self.assertIn("review only", status)
        self.assertIn("no candidate stock, price, or lifecycle is attributed", status)
        self.assertIn("IRF540NPBF (DigiKey)", status)

    def test_route_without_live_lookup_does_not_claim_suppliers_were_searched(self):
        status = legacy_route_status("PCF8574P", searched=False)
        self.assertIn("no configured distributor was available", status)
        self.assertIn("remains unassessed", status)


if __name__ == "__main__":
    unittest.main()
