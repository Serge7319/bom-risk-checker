from pathlib import Path
import unittest

from src.monitoring_engine import (
    build_monitor_record,
    detect_monitor_alerts,
    save_monitor_history,
)


class _Insert:
    def __init__(self, owner):
        self.owner = owner

    def insert(self, records):
        self.owner.records = records
        return self

    def execute(self):
        if self.owner.fail:
            raise ValueError("simulated persistence failure")
        return None


class _Table:
    def __init__(self, owner):
        self.owner = owner

    def insert(self, records):
        return _Insert(self.owner).insert(records)


class _Supabase:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.records = None

    def table(self, name):
        assert name == "part_monitor_history"
        return _Table(self)


class MonitoringHistoryPersistenceTests(unittest.TestCase):
    def test_monitor_snapshot_converts_nan_to_null_and_does_not_trigger_false_change(self):
        current = build_monitor_record(
            "user-1",
            "analysis-1",
            {
                "MPN": "ABC123",
                "Stock Available": float("nan"),
                "Unit Price": float("inf"),
                "Lifecycle Status": "Active",
            },
        )
        self.assertIsNone(current["stock"])
        self.assertIsNone(current["unit_price"])

        alerts, _ = detect_monitor_alerts(
            "user-1",
            "analysis-1",
            "ABC123",
            {"stock": 100, "unit_price": 1.0, "lifecycle_status": "Active"},
            current,
        )
        self.assertEqual(alerts, [])

    def test_monitor_history_persistence_strictly_serializes_and_is_nonfatal(self):
        client = _Supabase()
        record = build_monitor_record("user-1", "analysis-1", {"MPN": "ABC123"})
        self.assertTrue(save_monitor_history(client, [record]))
        self.assertIsNone(client.records[0]["stock"])
        self.assertIsNone(client.records[0]["unit_price"])

        failing_client = _Supabase(fail=True)
        with self.assertLogs("src.monitoring_engine", level="WARNING"):
            self.assertFalse(save_monitor_history(failing_client, [record]))

    def test_analysis_flow_keeps_monitoring_history_failure_nonblocking(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py").read_text()
        self.assertIn("if monitor_records and not save_monitor_history(supabase, monitor_records):", source)
        self.assertIn("Your BOM analysis was saved, but monitoring history could not be updated.", source)
        self.assertNotIn("Could not save monitoring history: {e}", source)


if __name__ == "__main__":
    unittest.main()
