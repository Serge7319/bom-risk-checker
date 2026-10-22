from pathlib import Path
import unittest

import pandas as pd

from src.monitoring_engine import (
    build_monitor_record,
    detect_monitor_alerts,
    monitoring_risk_level,
    resolve_monitoring_workspace_id,
    save_monitor_alerts,
    save_monitor_history,
    save_monitor_history_with_diagnostic,
)


class _Insert:
    def __init__(self, owner):
        self.owner = owner

    def insert(self, records):
        self.owner.records = records
        return self

    def execute(self):
        if self.owner.fail:
            raise ValueError(self.owner.error_message)
        return None


class _Table:
    def __init__(self, owner):
        self.owner = owner

    def insert(self, records):
        return _Insert(self.owner).insert(records)


class _Supabase:
    def __init__(self, *, fail=False, error_message="simulated persistence failure"):
        self.fail = fail
        self.error_message = error_message
        self.records = None

    def table(self, name):
        assert name == "part_monitor_history"
        return _Table(self)


class _OptionalColumnSupabase:
    def __init__(self, missing_column):
        self.missing_column = missing_column
        self.attempts = []

    def table(self, name):
        return self

    def insert(self, records):
        self.attempts.append(records)
        if any(self.missing_column in row for row in records):
            raise ValueError(
                f"Could not find the '{self.missing_column}' column in the schema cache"
            )
        return self

    def execute(self):
        return None


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
                "Manufacturer Part Number": "ABC123",
                "Product URL": "https://example.test/parts/ABC123",
                "Datasheet URL": "https://example.test/docs/ABC123.pdf",
            },
        )
        self.assertIsNone(current["stock"])
        self.assertIsNone(current["unit_price"])
        self.assertEqual(current["product_url"], "https://example.test/parts/ABC123")
        self.assertEqual(current["datasheet_url"], "https://example.test/docs/ABC123.pdf")

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

    def test_dataframe_part_rows_keep_only_exact_mpn_urls(self):
        record = build_monitor_record(
            "user-1",
            "analysis-1",
            pd.Series({
                "MPN": "DHT11",
                "Manufacturer Part Number": "DHT11",
                "Product URL": "https://example.test/dht11",
                "Datasheet URL": "https://example.test/dht11.pdf",
            }),
        )
        self.assertEqual(record["product_url"], "https://example.test/dht11")
        self.assertEqual(record["datasheet_url"], "https://example.test/dht11.pdf")

    def test_monitor_baseline_reads_saved_bom_risk_level_without_inventing_a_label(self):
        self.assertEqual(monitoring_risk_level({"risk_level": "High"}), "High")
        self.assertEqual(monitoring_risk_level({"risk": "Medium"}), "Medium")
        self.assertEqual(monitoring_risk_level({}), "Needs verification")
        record = build_monitor_record(
            "user-1",
            "analysis-1",
            {"MPN": "ABC123", "risk_level": "High"},
        )
        self.assertEqual(record["risk_level"], "High")

    def test_analysis_flow_keeps_monitoring_history_failure_nonblocking(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py").read_text()
        self.assertIn("if monitor_records and not save_monitor_history(supabase, monitor_records):", source)
        self.assertIn("Your BOM analysis was saved, but monitoring history could not be updated.", source)
        self.assertNotIn("Could not save monitoring history: {e}", source)

    def test_missing_optional_url_columns_do_not_break_monitor_writes(self):
        history_db = _OptionalColumnSupabase("datasheet_url")
        snapshot = {"part_number": "ABC123", "datasheet_url": "https://example.test/a.pdf"}
        self.assertTrue(save_monitor_history(history_db, [snapshot]))
        self.assertEqual(len(history_db.attempts), 2)
        self.assertNotIn("datasheet_url", history_db.attempts[-1][0])

        alerts_db = _OptionalColumnSupabase("supplier")
        alert = {"part_number": "ABC123", "supplier": "Mouser", "product_url": "https://example.test/part"}
        self.assertTrue(save_monitor_alerts(alerts_db, [alert]))
        self.assertEqual(len(alerts_db.attempts), 2)
        self.assertNotIn("supplier", alerts_db.attempts[-1][0])

    def test_monitoring_uses_the_saved_bom_workspace_scope(self):
        self.assertEqual(
            resolve_monitoring_workspace_id(
                {"workspace_id": "workspace-from-part"},
                {"workspace_id": "workspace-from-analysis"},
                "active-workspace",
            ),
            "workspace-from-analysis",
        )
        self.assertEqual(
            resolve_monitoring_workspace_id(
                {}, {"workspace_id": "workspace-from-analysis"}, "active-workspace"
            ),
            "workspace-from-analysis",
        )
        self.assertEqual(
            resolve_monitoring_workspace_id({}, {}, "active-workspace"),
            "active-workspace",
        )

    def test_monitoring_baseline_write_returns_safe_database_diagnostic(self):
        client = _Supabase(
            fail=True,
            error_message="insert violates foreign key constraint (23503)",
        )
        saved, diagnostic = save_monitor_history_with_diagnostic(
            client,
            [build_monitor_record("user-1", "analysis-1", {"MPN": "ABC123"})],
        )
        self.assertFalse(saved)
        self.assertIn("saved BOM or workspace reference", diagnostic)
        self.assertNotIn("ABC123", diagnostic)

    def test_monitoring_check_constraint_error_is_actionable(self):
        client = _Supabase(
            fail=True,
            error_message="new row violates check constraint (23514)",
        )
        saved, diagnostic = save_monitor_history_with_diagnostic(
            client,
            [build_monitor_record("user-1", "analysis-1", {"MPN": "ABC123"})],
        )
        self.assertFalse(saved)
        self.assertIn("rejected a field value", diagnostic)

    def test_monitoring_scope_migration_adds_analysis_and_workspace_ids(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "supabase"
            / "migrations"
            / "20261022_monitoring_baseline_scope.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("public.part_monitor_history", migration)
        self.assertIn("public.monitor_alerts", migration)
        self.assertGreaterEqual(migration.count("add column if not exists analysis_id text"), 2)
        self.assertGreaterEqual(migration.count("add column if not exists workspace_id text"), 2)


if __name__ == "__main__":
    unittest.main()
