from pathlib import Path
from types import SimpleNamespace
import unittest

from src.monitoring_refresh import refresh_monitored_part


class _Query:
    def __init__(self, owner, table):
        self.owner = owner
        self.table_name = table
        self.filters = []
        self.operation = "select"
        self.records = []

    def select(self, _columns):
        self.operation = "select"
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, _column, desc=False):
        return self

    def limit(self, _count):
        return self

    def insert(self, records):
        self.operation = "insert"
        self.records = records
        return self

    def execute(self):
        if self.operation == "insert":
            self.owner.writes.setdefault(self.table_name, []).extend(self.records)
            return SimpleNamespace(data=self.records)
        rows = self.owner.history if self.table_name == "part_monitor_history" else []
        matching = [
            row for row in rows
            if all(str(row.get(column) or "") == str(value or "") for column, value in self.filters)
        ]
        self.owner.read_filters.append((self.table_name, list(self.filters)))
        return SimpleNamespace(data=matching)


class _Supabase:
    def __init__(self, history):
        self.history = list(history)
        self.writes = {}
        self.read_filters = []

    def table(self, table_name):
        return _Query(self, table_name)


class MonitoringRefreshTests(unittest.TestCase):
    def setUp(self):
        self.baseline = {
            "user_id": "user-1",
            "workspace_id": "workspace-1",
            "analysis_id": "analysis-1",
            "part_number": "ABC123",
            "supplier": "DigiKey",
            "lifecycle_status": "Active",
            "stock": 1000,
            "unit_price": 1.0,
        }
        self.db = _Supabase([
            {**self.baseline, "workspace_id": "other-workspace"},
            self.baseline,
        ])

    def test_refresh_reads_only_the_scoped_baseline_and_saves_live_snapshot_and_alerts(self):
        observed = []

        def supplier_lookup(mpn):
            observed.append(mpn)
            return {
                "supplier_data_verified": True,
                "manufacturer_part_number": "ABC123",
                "source": "Mouser",
                "sources_available": "DigiKey, Mouser",
                "provider_health": {"configured_count": 3, "available_count": 2},
                "lifecycle_status": "Active",
                "stock_total": 200,
                "unit_price": 1.6,
                "product_detail_url": "https://supplier.example/ABC123",
                "datasheet_url": "https://maker.example/ABC123.pdf",
            }

        result = refresh_monitored_part(
            self.db,
            user_id="user-1",
            workspace_id="workspace-1",
            analysis_id="analysis-1",
            part_number="ABC123",
            supplier_lookup=supplier_lookup,
        )

        self.assertEqual(result["status"], "updated")
        self.assertEqual(observed, ["ABC123"])
        filters = dict(self.db.read_filters[0][1])
        self.assertEqual(filters["user_id"], "user-1")
        self.assertEqual(filters["workspace_id"], "workspace-1")
        self.assertEqual(filters["analysis_id"], "analysis-1")
        self.assertEqual(filters["part_number"], "ABC123")
        saved_snapshot = self.db.writes["part_monitor_history"][0]
        self.assertEqual(saved_snapshot["workspace_id"], "workspace-1")
        self.assertEqual(saved_snapshot["analysis_id"], "analysis-1")
        self.assertEqual(saved_snapshot["stock"], 200)
        self.assertEqual(saved_snapshot["unit_price"], 1.6)
        self.assertEqual(result["alert_count"], 2)
        self.assertEqual(len(self.db.writes["monitor_alerts"]), 2)
        self.assertEqual(
            {row["alert_type"] for row in self.db.writes["monitor_alerts"]},
            {"Stock Drop", "Price Increase"},
        )
        self.assertTrue(result["checked_at"].endswith("+00:00"))

    def test_refresh_does_not_start_monitoring_without_an_existing_baseline(self):
        self.db.history = []
        looked_up = []

        result = refresh_monitored_part(
            self.db,
            user_id="user-1",
            workspace_id="workspace-1",
            part_number="ABC123",
            supplier_lookup=lambda mpn: looked_up.append(mpn) or {},
        )

        self.assertEqual(result["status"], "no_baseline")
        self.assertEqual(looked_up, [])
        self.assertEqual(self.db.writes, {})

    def test_refresh_rejects_nonexact_or_unverified_supplier_results(self):
        result = refresh_monitored_part(
            self.db,
            user_id="user-1",
            workspace_id="workspace-1",
            part_number="ABC123",
            supplier_lookup=lambda _mpn: {
                "supplier_data_verified": True,
                "manufacturer_part_number": "ABC124",
                "stock_total": 0,
            },
        )

        self.assertEqual(result["status"], "exact_supplier_match_unavailable")
        self.assertEqual(self.db.writes, {})

    def test_refresh_keeps_last_snapshot_when_a_supplier_is_unavailable(self):
        result = refresh_monitored_part(
            self.db,
            user_id="user-1",
            workspace_id="workspace-1",
            part_number="ABC123",
            supplier_lookup=lambda _mpn: (_ for _ in ()).throw(TimeoutError()),
        )

        self.assertEqual(result["status"], "supplier_unavailable")
        self.assertEqual(self.db.writes, {})

    def test_monitoring_page_exposes_component_scoped_live_refresh(self):
        runtime = Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
        source = runtime.read_text(encoding="utf-8")

        self.assertIn(
            "with component_action_columns[action_position]:\n                                if st.button(\n                                    \"Refresh live supplier data\"",
            source,
        )
        self.assertIn("Refresh live supplier data", source)
        self.assertIn("refresh_monitored_part(", source)
        self.assertIn("The automatic supplier check runs every six hours", source)


if __name__ == "__main__":
    unittest.main()
