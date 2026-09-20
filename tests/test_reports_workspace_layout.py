"""Layout and interaction contracts for the Reports decision workspace."""
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
REPORTS = RUNTIME[RUNTIME.index("# ---------- Reports ----------"):]


class ReportsWorkspaceLayoutTests(unittest.TestCase):
    def test_reports_use_a_two_column_workspace(self) -> None:
        self.assertIn(
            "reports_workspace_col, reports_actions_col = st.columns(",
            REPORTS,
        )
        self.assertIn("[0.66, 0.34]", REPORTS)
        self.assertIn('key="reports_workspace"', REPORTS)
        self.assertIn('key="reports_package_center"', REPORTS)

    def test_report_center_contains_only_actionable_package_cards(self) -> None:
        for key in (
            "report_package_engineering",
            "report_package_procurement",
            "report_package_lifecycle",
            "report_package_alternatives",
        ):
            self.assertIn(f'key="{key}"', REPORTS)
        self.assertNotIn('key="report_package_executive"', REPORTS)
        self.assertIn('"Viewing" if preview_is_active else "Preview"', REPORTS)
        self.assertIn("_report_download_button(**download)", REPORTS)
        self.assertNotIn("Professional report library", REPORTS)
        self.assertNotIn('label="Formats"', REPORTS)

    def test_supporting_card_actions_share_one_compact_row(self) -> None:
        self.assertIn("action_columns = card.columns(", REPORTS)
        self.assertIn("1 + len(downloads)", REPORTS)
        self.assertIn("with action_columns[0]:", REPORTS)
        self.assertIn("with action_columns[download_index + 1]:", REPORTS)
        self.assertNotIn("download_index % 2", REPORTS)

    def test_preview_is_stateful_and_uses_plain_language_titles(self) -> None:
        self.assertIn('key="reports_preview_type"', REPORTS)
        self.assertIn('"Executive Decision Brief"', REPORTS)
        self.assertIn('"Procurement Decision Brief"', REPORTS)
        self.assertNotIn("preview_tabs = st.tabs(", REPORTS)

    def test_executive_exports_stay_with_the_default_preview(self) -> None:
        executive_preview = REPORTS[
            REPORTS.index('if selected_preview == "Executive Decision Brief":'):
            REPORTS.index('elif selected_preview == "Procurement Decision Brief":')
        ]
        for key in (
            "preview_executive_brief_",
            "preview_executive_summary_",
            "preview_executive_csv_",
        ):
            self.assertIn(key, executive_preview)

    def test_selected_bom_context_explains_every_number(self) -> None:
        for label in (
            "Production readiness",
            "Health opportunity",
            "Risk requiring review",
            "Component scope",
        ):
            self.assertIn(label, REPORTS)

    def test_report_history_table_switches_the_selected_analysis(self) -> None:
        self.assertIn('key="reports_history_table"', REPORTS)
        self.assertIn("on_select=_select_report_from_history", REPORTS)
        self.assertIn('selection_mode="single-row"', REPORTS)
        self.assertIn(
            'st.session_state["reports_selected_analysis"] = history_labels[',
            REPORTS,
        )

    def test_page_actions_stay_with_the_selected_analysis(self) -> None:
        self.assertIn("action_cols = reports_workspace.columns(3", REPORTS)
        for key in (
            "reports_open_analysis_details",
            "reports_open_bom_analyzer",
            "reports_open_alternative_finder",
        ):
            self.assertIn(f'key="{key}"', REPORTS)


if __name__ == "__main__":
    unittest.main()
