"""Sprint 72.3 — Ask Cadivor structured response field separation tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

REVIVED_7143_HELPERS = (
    "_format_engineering_prose",
    "_inline_engineering_format",
    "_render_structured_answer_sections",
)


class AskCadivorStructuredResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def _load_assistant(self):
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        import src.components.engineering_assistant as assistant

        return assistant

    def test_decision_confidence_label_value_separate_elements(self) -> None:
        assistant = self._load_assistant()
        html = assistant._build_decision_summary_html(
            status="Review",
            tone="warning",
            priority_part="PC817",
            confidence_score=56,
            confidence_label="Medium",
        )
        self.assertIn('class="cv722-summary-label"', html)
        self.assertIn('class="cv722-summary-value"', html)
        self.assertIn("Confidence", html)
        self.assertIn("56%", html)

    def test_bom_health_label_value_description_separated(self) -> None:
        assistant = self._load_assistant()
        html = assistant._html_impact_row("BOM health", "93", "Projected after mitigation")
        self.assertIn('class="cv39-impact-label"', html)
        self.assertIn('class="cv39-impact-value"', html)
        self.assertIn('class="cv39-impact-note"', html)

    def test_release_readiness_values_do_not_share_label_element(self) -> None:
        assistant = self._load_assistant()
        html = assistant._html_impact_row("Release readiness", "Focused review → Ready", "Posture")
        self.assertIn("Release readiness", html)
        self.assertIn("Focused review → Ready", html)

    def test_priority_component_label_value_separate(self) -> None:
        assistant = self._load_assistant()
        html = assistant._build_decision_summary_html(
            status="Review",
            tone="warning",
            priority_part="PC817",
            confidence_score=56,
            confidence_label="Medium",
        )
        self.assertIn("Priority component", html)
        self.assertIn("PC817", html)

    def test_evidence_confidence_driver_fields_separated(self) -> None:
        assistant = self._load_assistant()
        html = assistant._html_confidence_driver("Verified", "15/15", "Raises confidence")
        self.assertIn('class="cv46-driver-label"', html)
        self.assertIn('class="cv46-driver-value"', html)
        self.assertIn('class="cv46-driver-note"', html)

    def test_confidence_drivers_use_plain_data_coverage(self) -> None:
        assistant = self._load_assistant()
        drivers = assistant._confidence_drivers(
            {"components": [{"lifecycle_status": "Active", "supplier_count": 2, "stock_available": 5, "lead_time_weeks": 4}, {"lifecycle_status": "Active", "supplier_count": 1, "stock_available": 0}]},
            "- lifecycle evidence",
        )
        values = " ".join(value for _, value, _ in drivers)
        self.assertIn("Lifecycle data coverage — 2 of 2 parts", values)
        self.assertIn("Lead-time data coverage — 1 of 2 parts", values)

    def test_narrative_content_remains_escaped(self) -> None:
        assistant = self._load_assistant()
        evil = '<script>alert(1)</script>'
        cell = assistant._html_kpi_cell("Label", evil)
        self.assertNotIn("<script>", cell)
        self.assertIn("&lt;script&gt;", cell)

    def test_no_sprint_7143_helpers(self) -> None:
        for helper in REVIVED_7143_HELPERS:
            self.assertNotIn(f"def {helper}", self.assistant_source)

    def test_plain_markdown_unchanged(self) -> None:
        assistant = self._load_assistant()
        self.assertEqual(assistant._plain_markdown("**Bold** text"), "Bold text")

    def test_engineering_ai_ask_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)

    def test_queue_auth_prompt_clear_paths_untouched(self) -> None:
        for marker in (
            "_queue_copilot_submission",
            "_apply_deferred_prompt_clear",
            "_schedule_prompt_clear_on_next_run",
            "cv7142_ask_inflight",
        ):
            self.assertIn(marker, self.assistant_source)

    def test_shell_independent_structured_css_exists(self) -> None:
        self.assertIn("Sprint 72.1.1", self.v2_css)
        self.assertIn(".cv39-impact-label", self.v2_css)

    def test_concise_answer_builder_preserves_field_separation(self) -> None:
        assistant = self._load_assistant()
        html = assistant._build_concise_answer_html(
            headline="Review PC817 first.",
            answer_text="",
            reason_items=["Reason one"],
            action_items=["Action one"],
        )
        self.assertIn('class="cv722-section-label"', html)
        self.assertIn("Key engineering reasons", html)
        self.assertIn("Recommended actions", html)

    def test_ranking_rows_use_separate_title_and_detail_classes(self) -> None:
        assistant = self._load_assistant()
        html = assistant._build_engineering_assessment_html(
            question="Rank these parts",
            detailed=False,
            intent="general",
            evidence="",
            actions="",
            rankings="- **U1** — highest lifecycle risk\n- **U2** — supplier concentration",
            workflow_text="",
            context={"components": [], "coverage": {"score": 56}},
            priority_part="U1",
            confidence_detail="",
            confidence_drivers=[],
            impact=[],
            complete=1,
            total=2,
            progress=50,
        )
        self.assertIn('class="cv47-ranking-title"', html)
        self.assertIn('class="cv47-ranking-detail"', html)

    def test_native_renderer_present_in_production_path(self) -> None:
        self.assertIn("_render_native_answer_column", self.assistant_source)
        self.assertIn("_render_native_assessment_column", self.assistant_source)


if __name__ == "__main__":
    unittest.main()

def tearDownModule():
    from tests.ask_cadivor_streamlit_stub import restore_ask_cadivor_streamlit_modules
    restore_ask_cadivor_streamlit_modules()
