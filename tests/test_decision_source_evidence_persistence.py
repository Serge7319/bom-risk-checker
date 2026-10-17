from __future__ import annotations

import unittest

import pandas as pd

from src.decision_engine import build_decision_center, monitoring_decision_id
from src.decision_repository import save_decision_source_evidence


class _Query:
    def __init__(self, table_name: str, calls: list[tuple]):
        self.table_name = table_name
        self.calls = calls

    def upsert(self, payload, *, on_conflict):
        self.calls.append((self.table_name, "upsert", payload, on_conflict))
        return self

    def insert(self, payload):
        self.calls.append((self.table_name, "insert", payload))
        return self

    def execute(self):
        return self


class _Supabase:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return _Query(name, self.calls)


class DecisionSourceEvidencePersistenceTests(unittest.TestCase):
    def test_persists_exact_mpn_snapshot_and_audit_event(self):
        database = _Supabase()
        evidence = {
            "identity_verified": True,
            "manufacturer_part_number": "DHT11",
            "source": "Mouser",
            "product_detail_url": "https://example.test/dht11",
            "datasheet_url": "https://example.test/dht11.pdf",
            "retrieved_at": "2026-10-17T14:00:00Z",
        }

        error = save_decision_source_evidence(
            database,
            user_id="user-1",
            workspace_id="workspace-1",
            decision={
                "decision_id": "decision-1",
                "mpn": "DHT11",
                "status": "New",
                "priority_score": 70,
            },
            evidence=evidence,
            actor_name="Engineer",
        )

        self.assertIsNone(error)
        self.assertEqual(len(database.calls), 2)
        saved = database.calls[0][2]
        self.assertEqual(saved["decision_payload"]["source_evidence"], evidence)
        self.assertEqual(database.calls[1][2]["event_type"], "supplier_evidence_saved")

    def test_saved_supplier_evidence_survives_decision_center_rebuild(self):
        alert = {
            "part_number": "DHT11",
            "alert_type": "Lifecycle Change",
            "alert_message": "Lifecycle changed from new to active",
            "previous_value": "new",
            "current_value": "active",
        }
        evidence = {
            "identity_verified": True,
            "manufacturer_part_number": "DHT11",
            "source": "Mouser",
            "product_detail_url": "https://example.test/dht11",
            "datasheet_url": "https://example.test/dht11.pdf",
        }
        rebuilt = build_decision_center(
            alert_df=pd.DataFrame([alert]),
            analyses=[],
            saved_state={
                monitoring_decision_id(alert): {
                    "decision_payload": {"source_evidence": evidence},
                }
            },
            part_links=[],
        )
        self.assertEqual(rebuilt["decisions"][0]["source_evidence"], evidence)

    def test_rejects_neighboring_mpn_before_writing(self):
        database = _Supabase()
        error = save_decision_source_evidence(
            database,
            user_id="user-1",
            workspace_id=None,
            decision={"decision_id": "decision-1", "mpn": "DHT11"},
            evidence={
                "identity_verified": True,
                "manufacturer_part_number": "DHT22",
            },
            actor_name="Engineer",
        )

        self.assertIn("does not match", error)
        self.assertEqual(database.calls, [])


if __name__ == "__main__":
    unittest.main()
