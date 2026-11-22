from __future__ import annotations

import unittest

from apps.api.compliance_packs import build_pack
from apps.api.evidence_contract import (
    EVIDENCE_LIVE,
    EVIDENCE_MISSING,
    EVIDENCE_SYNTHETIC,
    EVIDENCE_UNVERIFIED,
    classify_part_evidence,
    evidence_mode_and_gap,
    is_current_supplier_snapshot,
)
from integrations.supplier_aggregator import _aggregate_compliance_evidence, _compliance_reading
from src.procurement_advisor import _recommend, normalize_supplier_offer_records, sourcing_editor_values
from tests.evidence_fixtures import live_supplier_part, retrieved_now, supplier_url


class EvidenceIdentityTests(unittest.TestCase):
    def _live_part(self, **extra):
        return {
            "MPN": "PART-123",
            "manufacturer_part_number": "PART-123",
            "Manufacturer": "Acme",
            "supplier_data_verified": True,
            "evidence_source": EVIDENCE_LIVE,
            "source": "DigiKey",
            "product_url": "https://www.digikey.com/product/PART-123",
            "retrieved_at": retrieved_now(),
            **extra,
        }

    def test_wrong_returned_mpn_cannot_verify_identity_or_price(self):
        evidence = classify_part_evidence(self._live_part(
            manufacturer_part_number="PART-123-ALT",
            **{
                "Unit Price": 1.25,
                "unit_price_currency": "USD",
                "supplier_offers": [{
                    "mpn": "PART-123-ALT",
                    "distributor": "DigiKey",
                    "unit_price": 1.25,
                    "currency": "USD",
                    "price_break_quantity": 1,
                    "product_url": "https://www.digikey.com/product/PART-123-ALT",
                    "retrieved_at": retrieved_now(),
                }],
            }
        ))
        self.assertEqual(evidence["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertEqual(evidence["fields"]["identity"]["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertEqual(evidence["fields"]["price"]["evidence_class"], EVIDENCE_UNVERIFIED)

    def test_supplier_label_alone_does_not_create_live_identity(self):
        evidence = classify_part_evidence({
            "MPN": "PART-123",
            "source": "DigiKey",
            "Unit Price": 1.25,
        })
        self.assertEqual(evidence["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertEqual(evidence["fields"]["identity"]["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertEqual(evidence["fields"]["price"]["evidence_class"], EVIDENCE_UNVERIFIED)

    def test_synthetic_data_wins_over_a_supplier_name_label(self):
        evidence = classify_part_evidence({
            "MPN": "PART-123",
            "identity_source": "DigiKey",
            "evidence_source": EVIDENCE_SYNTHETIC,
            "source": "DigiKey",
            "Unit Price": 1.25,
        })
        self.assertEqual(evidence["evidence_class"], EVIDENCE_SYNTHETIC)
        self.assertEqual(evidence["fields"]["identity"]["evidence_class"], EVIDENCE_SYNTHETIC)

    def test_missing_part_identity_is_not_mislabeled_as_synthetic(self):
        evidence = classify_part_evidence({"Unit Price": 1.25})
        self.assertEqual(evidence["evidence_class"], EVIDENCE_MISSING)
        self.assertFalse(evidence["synthetic"])

    def test_live_price_requires_exact_offer_and_applicable_quantity(self):
        part = self._live_part(
            **{
                "Unit Price": 1.25,
                "unit_price_currency": "USD",
                "Quantity": 20,
                "supplier_offers": [{
                    "mpn": "PART-123",
                    "distributor": "DigiKey",
                    "unit_price": 1.25,
                    "currency": "USD",
                    "price_break_quantity": 10,
                    "product_url": "https://www.digikey.com/product/PART-123",
                    "retrieved_at": retrieved_now(),
                }],
            }
        )
        evidence = classify_part_evidence(part)
        self.assertEqual(evidence["fields"]["price"]["evidence_class"], EVIDENCE_LIVE)
        self.assertTrue(evidence["fields"]["price"]["quantity_break_applies"])

        part["Quantity"] = 5
        evidence = classify_part_evidence(part)
        self.assertEqual(evidence["fields"]["price"]["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertFalse(evidence["fields"]["price"]["quantity_break_applies"])

    def test_lifecycle_requires_exact_timestamped_supplier_record(self):
        part = self._live_part(Lifecycle="Active", lifecycle_evidence=[{
            "source": "DigiKey",
            "mpn": "PART-123",
            "product_url": "https://www.digikey.com/product/PART-123",
            "status": "Active",
            "normalized_status": "active",
            "retrieved_at": retrieved_now(),
        }])
        self.assertEqual(classify_part_evidence(part)["fields"]["lifecycle"]["evidence_class"], EVIDENCE_LIVE)

        part["lifecycle_evidence"][0]["mpn"] = "PART-123-ALT"
        self.assertEqual(classify_part_evidence(part)["fields"]["lifecycle"]["evidence_class"], EVIDENCE_UNVERIFIED)

    def test_mixed_mode_includes_unverified_rows(self):
        mode, gap = evidence_mode_and_gap(
            live_count=1,
            synthetic_count=0,
            missing_count=0,
            unverified_count=2,
            configured_sources=2,
        )
        self.assertEqual(mode, "mixed-evidence")
        self.assertIn("varies", gap or "")

    def test_future_supplier_timestamp_cannot_verify_identity(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        future = (now + timedelta(minutes=5)).isoformat()
        part = live_supplier_part("PART-FUTURE", unit_price=0.25, retrieved_at=future)
        evidence = classify_part_evidence(part, now=now)
        self.assertEqual(evidence["fields"]["identity"]["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertFalse(evidence["identity_verified"])

    def test_future_stock_observation_is_excluded_from_current_total(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        part = live_supplier_part("PART-FUTURE-STOCK", retrieved_at=now.isoformat())
        future = (now + timedelta(minutes=5)).isoformat()
        for observation in part["stock_evidence"]:
            observation["retrieved_at"] = future
        stock = classify_part_evidence(part, now=now)["fields"]["stock"]
        self.assertEqual(stock["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertFalse(stock.get("current", False))
        self.assertIn("future retrieval timestamp", stock.get("gap", ""))

    def test_future_lifecycle_record_is_not_treated_as_live(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        part = live_supplier_part("PART-FUTURE-LIFE", retrieved_at=now.isoformat())
        for reading in part["lifecycle_evidence"]:
            reading["retrieved_at"] = (now + timedelta(minutes=5)).isoformat()
        lifecycle = classify_part_evidence(part, now=now)["fields"]["lifecycle"]
        self.assertEqual(lifecycle["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertFalse(lifecycle.get("current", False))

    def test_future_compliance_source_record_is_not_treated_as_live(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        part = live_supplier_part("PART-FUTURE-COMPLIANCE", retrieved_at=now.isoformat())
        part["compliance_evidence"] = {
            "rohs": {
                "reported_value": "RoHS compliant",
                "evidence_class": EVIDENCE_LIVE,
                "source": "DigiKey",
                "mpn": part["MPN"],
                "retrieved_at": now.isoformat(),
                "sources": [{
                    "source": "DigiKey",
                    "mpn": part["MPN"],
                    "source_url": "https://www.digikey.com/product/" + part["MPN"],
                    "reported_value": "RoHS compliant",
                    "retrieved_at": (now + timedelta(minutes=5)).isoformat(),
                }],
            }
        }
        rohs = classify_part_evidence(part, now=now)["fields"]["compliance"]["rohs"]
        self.assertEqual(rohs["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertFalse(rohs.get("current", False))


class ComplianceSemanticsTests(unittest.TestCase):
    def test_common_rohs_wording_normalizes_without_false_conflict(self):
        self.assertEqual(_compliance_reading("rohs", "ROHS3 Compliant")[0], "compliant")
        self.assertEqual(_compliance_reading("rohs", "RoHS Compliant")[0], "compliant")
        rows = [
            {"source": "DigiKey", "compliance_evidence": {"rohs": {"reported_value": "ROHS3 Compliant"}}},
            {"source": "Mouser", "compliance_evidence": {"rohs": {"reported_value": "RoHS Compliant"}}},
        ]
        evidence = _aggregate_compliance_evidence(rows)["rohs"]
        self.assertFalse(evidence["conflict"])
        self.assertFalse(evidence["partial"])

    def test_rohs_exemption_is_qualified_and_not_a_conflict(self):
        self.assertEqual(_compliance_reading("rohs", "RoHS compliant by exemption"), ("compliant", "exemption"))
        evidence = _aggregate_compliance_evidence([
            {"source": "DigiKey", "compliance_evidence": {"rohs": {"reported_value": "RoHS compliant"}}},
            {"source": "Mouser", "compliance_evidence": {"rohs": {"reported_value": "RoHS compliant by exemption"}}},
        ])["rohs"]
        self.assertFalse(evidence["conflict"])
        self.assertTrue(evidence["partial"])

    def test_generic_reach_compliant_is_not_converted_to_unaffected(self):
        key, _ = _compliance_reading("reach", "Compliant")
        self.assertTrue(key.startswith("unclassified:"))

    def test_conflict_and_missing_compliance_are_counted_as_unknown_review_states(self):
        retrieved_at = retrieved_now()
        base = {
            **live_supplier_part("PART-123"),
            "compliance_evidence": {
                "rohs": {
                    "reported_value": "Conflicting supplier declarations",
                    "source": "DigiKey; Mouser",
                    "source_url": "https://www.digikey.com/product/PART-123",
                    "evidence_class": EVIDENCE_LIVE,
                    "mpn": "PART-123",
                    "conflict": True,
                    "sources": [
                        {"mpn": "PART-123", "source": "DigiKey", "source_url": "https://www.digikey.com/product/PART-123", "reported_value": "RoHS compliant", "retrieved_at": retrieved_at},
                        {"mpn": "PART-123", "source": "Mouser", "source_url": "https://www.mouser.com/PART-123", "reported_value": "Non-compliant", "retrieved_at": retrieved_at},
                    ],
                }
            },
        }
        pack = build_pack({"parts": [base, {"MPN": "NO-DECLARATION"}]}, "rohs")
        self.assertEqual(pack["summary"]["conflicting_evidence"], 1)
        self.assertEqual(pack["summary"]["missing_evidence"], 1)
        self.assertEqual(pack["summary"]["unknown"], 1)
        self.assertFalse(pack["summary"]["compliance_claimed"])

    def test_old_price_snapshot_is_not_current_even_when_identity_is_live(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        old = now - timedelta(days=2)
        part = live_supplier_part("PART-OLD", unit_price=0.25, retrieved_at=old.isoformat())
        price = classify_part_evidence(part, now=now)["fields"]["price"]
        self.assertEqual(price["evidence_class"], EVIDENCE_UNVERIFIED)
        self.assertFalse(price["current"])
        self.assertEqual(price["freshness"], "stale")

    def test_shared_supplier_freshness_limits_reject_stale_and_future_values(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        self.assertTrue(is_current_supplier_snapshot("stock", now.isoformat(), now=now))
        self.assertFalse(is_current_supplier_snapshot(
            "stock", (now - timedelta(hours=25)).isoformat(), now=now
        ))
        self.assertFalse(is_current_supplier_snapshot(
            "lead_time", (now + timedelta(minutes=1)).isoformat(), now=now
        ))
        self.assertFalse(is_current_supplier_snapshot("unknown_field", now.isoformat(), now=now))


class ProcurementEvidenceSemanticsTests(unittest.TestCase):
    def _part_with_offer(self, *, retrieved_at=None, url=None, offered_mpn="PART-OFFER"):
        part = live_supplier_part("PART-OFFER", unit_price=0.25, retrieved_at=retrieved_at)
        part["supplier_offers"] = [{
            "mpn": offered_mpn,
            "distributor": "DigiKey",
            "unit_price": 0.25,
            "currency": "USD",
            "price_break_quantity": 1,
            "product_url": url or supplier_url("DigiKey", "PART-OFFER"),
            "retrieved_at": retrieved_at or retrieved_now(),
            "stock": 80,
            "lead_time_weeks": 6,
        }]
        return part

    def test_procurement_offer_requires_live_exact_identity_freshness_and_matching_domain(self):
        row = normalize_supplier_offer_records(self._part_with_offer())[0]
        self.assertTrue(row["price_verified"])
        self.assertTrue(row["stock_verified"])
        self.assertTrue(row["lead_time_verified"])
        self.assertTrue(row["is_current"])

        wrong_domain_part = self._part_with_offer(url="https://example.test/product/PART-OFFER")
        wrong_domain_part["stock_evidence"] = []
        wrong_domain_part["stock_data_complete"] = False
        wrong_domain = normalize_supplier_offer_records(wrong_domain_part)[0]
        self.assertFalse(wrong_domain["price_verified"])
        self.assertFalse(wrong_domain["stock_verified"])
        self.assertFalse(wrong_domain["lead_time_verified"])

        wrong_mpn_part = self._part_with_offer(offered_mpn="PART-OTHER")
        wrong_mpn_part["stock_evidence"] = []
        wrong_mpn_part["stock_data_complete"] = False
        wrong_mpn = normalize_supplier_offer_records(wrong_mpn_part)[0]
        self.assertFalse(wrong_mpn["price_verified"])
        self.assertFalse(wrong_mpn["stock_verified"])
        self.assertFalse(wrong_mpn["lead_time_verified"])

    def test_procurement_offer_stale_fields_are_not_current(self):
        from datetime import datetime, timedelta, timezone

        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        row = normalize_supplier_offer_records(self._part_with_offer(retrieved_at=old))[0]
        self.assertFalse(row["price_verified"])
        self.assertFalse(row["stock_verified"])
        self.assertTrue(row["lead_time_verified"])

    def test_unverified_saved_score_and_supplier_name_do_not_become_current_priority(self):
        row = _recommend({
            "mpn": "PART-STALE",
            "primary_supplier": "DigiKey",
            "supplier_data_verified": False,
            "risk_score": 100,
            "risk_level": "High",
            "stock_available": 0,
            "supplier_count": 0,
            "lead_time_weeks": 0,
            "lifecycle_status": "Obsolete",
        })
        self.assertEqual(row["Priority Score"], 0)
        self.assertIn("Not assessed", row["Priority Basis"])
        self.assertEqual(row["Recommendation"], "Check a configured source")

        editor = sourcing_editor_values({
            "mpn": "PART-STALE",
            "primary_supplier": "DigiKey",
            "supplier_data_verified": False,
        })
        self.assertEqual(editor["primary_supplier"], "")


if __name__ == "__main__":
    unittest.main()
