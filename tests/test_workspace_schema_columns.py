import unittest
from pathlib import Path
from types import SimpleNamespace

from src.core.workspace_search import build_workspace_commands
from src.services.knowledge_graph import KnowledgeGraphService


class _FakeSupabase:
    def __init__(self, records):
        self.records = records
        self.selections = []
        self.schemas = {
            "analyses": {
                "id", "project_name", "filename", "total_parts", "health_score",
                "high_risk_count", "created_at", "workspace_id", "user_id",
            },
            "analysis_parts": {
                "analysis_id", "mpn", "manufacturer_part_number", "manufacturer",
                "risk_level", "risk", "lifecycle_status", "lifecycle", "user_id",
                "created_at",
            },
            "monitor_alerts": {
                "id", "part_number", "alert_type", "change_type", "event_type",
                "message", "alert_message", "summary", "status", "analysis_id",
                "created_at", "user_id",
            },
            "engineering_decisions": {
                "id", "part_number", "mpn", "decision", "status",
                "decision_status", "rationale", "reason", "notes", "updated_at",
                "user_id", "scope_key", "decision_key",
            },
            "alternative_recommendations": {
                "id", "original_part", "alternative_part", "alternative_mpn",
                "supplier", "recommendation_score", "score", "created_at", "user_id",
            },
        }

    def table(self, name):
        return _FakeQuery(self, name)


class _FakeQuery:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.columns = "*"
        self.filters = []

    def select(self, columns):
        self.columns = columns
        self.client.selections.append((self.table_name, columns))
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, tuple(values)))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        columns = [column.strip() for column in self.columns.split(",")]
        if self.columns != "*":
            missing = set(columns) - self.client.schemas.get(self.table_name, set())
            if missing:
                raise ValueError(f"column {sorted(missing)[0]} does not exist on {self.table_name}")

        rows = list(self.client.records.get(self.table_name, []))
        for kind, column, expected in self.filters:
            if kind == "eq":
                rows = [row for row in rows if row.get(column) == expected]
            else:
                rows = [row for row in rows if row.get(column) in expected]

        if self.columns != "*":
            rows = [
                {column: row[column] for column in columns if column in row}
                for row in rows
            ]
        return SimpleNamespace(data=rows)


def _synthetic_records():
    analysis_id = "synthetic-analysis-1"
    timestamp = "2026-10-24T12:00:00Z"
    return {
        "analyses": [{
            "id": analysis_id,
            "project_name": "TEST - Synthetic QA BOM",
            "filename": "TEST - Synthetic QA BOM.csv",
            "total_parts": 1,
            "health_score": 90,
            "high_risk_count": 0,
            "created_at": timestamp,
            "workspace_id": "synthetic-workspace",
            "user_id": "synthetic-user",
        }],
        "analysis_parts": [{
            "analysis_id": analysis_id,
            "mpn": "SYNTH-PART-001",
            "manufacturer_part_number": "SYNTH-PART-001",
            "manufacturer": "TEST Semiconductor",
            "risk_level": "Low",
            "risk": "Low",
            "lifecycle_status": "Active",
            "lifecycle": "Active",
            "user_id": "synthetic-user",
            "created_at": timestamp,
        }],
        "monitor_alerts": [{
            "id": "synthetic-alert-1",
            "user_id": "synthetic-user",
            "analysis_id": analysis_id,
            "part_number": "SYNTH-PART-001",
            "alert_type": "Lifecycle Change",
            "change_type": "Lifecycle Change",
            "event_type": "Lifecycle Change",
            "message": "Synthetic lifecycle alert",
            "alert_message": "Synthetic lifecycle alert",
            "summary": "Synthetic lifecycle alert",
            "status": "Open",
            "created_at": timestamp,
        }],
        "engineering_decisions": [{
            "id": "synthetic-decision-1",
            "user_id": "synthetic-user",
            "scope_key": "synthetic-workspace",
            "decision_key": "synthetic-decision-1",
            "part_number": "SYNTH-PART-001",
            "mpn": "SYNTH-PART-001",
            "decision": "Review",
            "status": "Open",
            "decision_status": "Open",
            "rationale": "Synthetic rationale",
            "reason": "Synthetic rationale",
            "notes": "Synthetic note",
            "updated_at": timestamp,
        }],
        "alternative_recommendations": [{
            "id": "synthetic-alternative-1",
            "user_id": "synthetic-user",
            "original_part": "SYNTH-PART-001",
            "alternative_part": "SYNTH-ALT-001",
            "alternative_mpn": "SYNTH-ALT-001",
            "supplier": "DigiKey",
            "recommendation_score": 85,
            "score": 85,
            "created_at": timestamp,
        }],
    }


class WorkspaceSearchSchemaColumnsTest(unittest.TestCase):
    def test_workspace_search_runs_with_known_table_columns(self):
        client = _FakeSupabase(_synthetic_records())

        commands = build_workspace_commands(client, "synthetic-user", limit_per_source=10)

        entity_types = {command["entityType"] for command in commands}
        self.assertTrue({"bom", "component", "alert", "decision", "alternative"} <= entity_types)

        missing_columns = {
            "analysis_parts": {"part_number"},
            "monitor_alerts": {"mpn"},
            "engineering_decisions": {"original_part"},
            "alternative_recommendations": {"original_mpn"},
        }
        for table, invalid in missing_columns.items():
            selections = [fields for source, fields in client.selections if source == table]
            self.assertTrue(selections, f"Expected a query for {table}")
            for fields in selections:
                self.assertFalse(invalid.intersection(fields.split(",")), f"{table}: {fields}")


class KnowledgeGraphSchemaColumnsTest(unittest.TestCase):
    def test_where_used_query_uses_available_analysis_part_columns(self):
        client = _FakeSupabase(_synthetic_records())
        context = SimpleNamespace(
            analysis={
                "analysis_id": "synthetic-analysis-1",
                "project_name": "TEST - Synthetic QA BOM",
            },
            components=[{
                "part_number": "SYNTH-PART-001",
                "manufacturer": "TEST Semiconductor",
                "best_source": "DigiKey",
                "risk_level": "Low",
            }],
            alternatives=[],
            monitoring=[],
            decisions=[],
        )

        graph = KnowledgeGraphService(client).build(
            context=context,
            user_id="synthetic-user",
        )

        part_queries = [
            fields for table, fields in client.selections if table == "analysis_parts"
        ]
        self.assertTrue(part_queries)
        self.assertTrue(all("part_number" not in fields.split(",") for fields in part_queries))
        self.assertEqual(
            graph.where_used["SYNTH-PART-001"],
            [{
                "analysis_id": "synthetic-analysis-1",
                "project_name": "TEST - Synthetic QA BOM",
            }],
        )


if __name__ == "__main__":
    unittest.main()


class AnalysisDecisionRlsMigrationTest(unittest.TestCase):
    def test_authenticated_decision_policy_is_user_and_workspace_scoped(self):
        migration = (
            Path(__file__).resolve().parents[1]
            / "supabase"
            / "migrations"
            / "20261024_analysis_decisions_workspace_rls.sql"
        ).read_text(encoding="utf-8").lower()

        self.assertIn("create table if not exists public.analysis_decisions", migration)
        self.assertIn("alter table public.analysis_decisions enable row level security", migration)
        self.assertIn("for select to authenticated", migration)
        self.assertIn("for insert to authenticated", migration)
        self.assertIn("for update to authenticated", migration)
        self.assertIn("user_id::text = auth.uid()::text", migration)
        self.assertIn("wm.user_id::text = auth.uid()::text", migration)
        self.assertIn("wm.status = 'active'", migration)
        self.assertIn("workspace_id is null", migration)
        self.assertIn("revoke all on table public.analysis_decisions from anon", migration)
