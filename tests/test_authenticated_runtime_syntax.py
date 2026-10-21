"""Compilation and layout regressions for the authenticated Cadivor runtime."""
from pathlib import Path
import ast
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AuthenticatedRuntimeSyntaxTests(unittest.TestCase):
    def test_authenticated_runtime_compiles(self) -> None:
        source_path = ROOT / "src" / "authenticated_runtime.py"
        compile(source_path.read_text(encoding="utf-8"), str(source_path), "exec")

    def test_datetime_is_not_shadowed_in_authenticated_runtime(self) -> None:
        source = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("        from datetime import datetime, timezone\n", source)

    def test_runtime_query_state_annotation_names_are_imported(self) -> None:
        source = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("from typing import Any", source)
        self.assertIn("def _clean_query_state(values: dict[str, Any])", source)

    def test_navigation_query_reader_returns_flat_string_values(self) -> None:
        source_path = ROOT / "src" / "ui" / "navigation.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        reader = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "read_query_params"
        )
        namespace = {
            "st": types.SimpleNamespace(
                query_params={
                    "page": "Dashboard",
                    "analysis_id": ["old", "current"],
                    "empty": "",
                }
            )
        }
        isolated_module = ast.Module(body=[reader], type_ignores=[])
        exec(compile(isolated_module, str(source_path), "exec"), namespace)
        self.assertEqual(
            namespace["read_query_params"](),
            {"page": "Dashboard", "analysis_id": "current"},
        )

    def test_one_time_report_offers_buy_first_and_analyze_first_paths(self) -> None:
        source = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("Buy one report now", source)
        self.assertIn("Analyze first, then decide", source)
        self.assertIn("Continue this BOM analysis", source)
        self.assertIn("Resuming the completed analysis from this session", source)
        self.assertIn("Cadivor will ask for payment before saving the full report", source)
        self.assertIn("if not _one_time_feature_enabled:", source)

    def test_one_time_and_subscription_reports_share_the_saved_detailed_export(self) -> None:
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        report = (ROOT / "src" / "ui" / "ei_bom_report.py").read_text(encoding="utf-8")
        self.assertIn('navigate_to("Analysis Details", analysis_id=str(analysis_id))', runtime)
        self.assertIn("detailed_risk_excel_bytes(", report)
        self.assertIn("detailed_risk_csv_bytes(", report)

    def test_bom_candidate_evidence_is_carried_into_saved_analysis_parts(self) -> None:
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        migration = (
            ROOT / "supabase" / "migrations" / "20261021_analysis_part_alternate_candidates.sql"
        ).read_text(encoding="utf-8")
        self.assertIn('"Alternate Candidates": part_data.get("alternate_candidates") or []', runtime)
        self.assertIn('"alternate_candidates": part_row.get("Alternate Candidates") or []', runtime)
        self.assertIn("add column if not exists alternate_candidates jsonb", migration)

    def test_bom_workspace_keeps_only_primary_analysis_and_saved_manager(self) -> None:
        source = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")

        self.assertIn('input_col, saved_manager_col = st.columns([0.38, 0.62], gap="large")', source)
        self.assertIn('def _render_saved_bom_manager()', source)
        self.assertIn('with saved_manager_col:', source)
        self.assertIn('_bom_saved_panel_context = st.container(', source)
        self.assertIn('_render_saved_bom_manager()\n                    _bom_saved_panel_context.__exit__', source)
        self.assertIn('key="bom9_upload_panel"', source)
        self.assertIn('key="bom9_saved_panel"', source)
        self.assertIn('bom9-panel-intro', source)
        self.assertNotIn('workflow_steps(["Prepare", "Upload", "Analyze", "Review"], active=1)', source)
        self.assertIn('if app_mode in {"BOM Analyzer", "High Risk Review"}:', source)
        self.assertIn('"High Risk Review",', source)
        self.assertIn('if _incoming_high_risk_review:', source)
        self.assertIn('st.session_state["bom81_high_risk_review"] = True', source)
        self.assertNotIn('guidance_col, saved_manager_col = st.columns', source)


if __name__ == "__main__":
    unittest.main()
