"""Sprint 72.2.3 — Ask Cadivor concise response presentation tests."""
from __future__ import annotations

import re
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

PC817_ANSWER = (
    "### Intent\nGeneral Engineering Review\n\n"
    "### Direct Answer\n"
    "Review PC817 first because it represents the most immediate lifecycle and sourcing exposure in this BOM.\n\n"
    "### Evidence\n"
    "- **PC817** — highest current component risk\n"
    "- **PC817** — sourcing position creates qualification exposure\n"
    "- **R1** — resolving PC817 improves BOM readiness\n"
    "- **R2** — should not appear in concise surface\n\n"
    "### Recommended Actions\n"
    "Validate the approved alternate for PC817. Confirm lifecycle and supplier evidence. "
    "Record the qualification decision in Cadivor. Extra action should not appear."
)

PC817_CONTEXT = {
    "analysis": {"analysis_id": "a-pc817", "health_score": 86},
    "summary": {"health_score": 86, "release_posture": "focused_review"},
    "components": [
        {
            "part_number": "PC817",
            "risk_score": 88,
            "supplier_count": 1,
            "stock_available": 5,
            "lead_time_weeks": 12,
        }
    ],
    "monitoring": [],
    "alternatives": [],
    "decisions": [],
    "coverage": {"score": 86},
}


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    markdown_calls: list[tuple[str, dict]] = []
    expander_calls: list[tuple[tuple, dict]] = []

    st.markdown = lambda content, **kwargs: markdown_calls.append((content, kwargs))

    def _expander(*args, **kwargs):
        expander_calls.append((args, kwargs))
        return _NullContext()

    st.expander = _expander
    st.columns = MagicMock(
        side_effect=lambda spec: [MagicMock() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]
    )

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="run-a")
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st, markdown_calls, expander_calls


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AskCadivorResponsePresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def setUp(self) -> None:
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def _load_assistant(self):
        import src.components.engineering_assistant as assistant

        return assistant

    def _render_pc817(self):
        st_stub, markdown_calls, expander_calls = _install_streamlit_stub()
        assistant = self._load_assistant()
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question="What should I review first in this BOM?",
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        html = "\n".join(content for content, _kwargs in markdown_calls if isinstance(content, str))
        return assistant, html, expander_calls

    def test_concise_answer_classes_exist(self) -> None:
        _, html, _ = self._render_pc817()
        for class_name in (
            "cv722-concise-answer",
            "cv722-direct-answer",
            "cv722-direct-answer-text",
            "cv722-section-label",
        ):
            self.assertIn(class_name, html)

    def test_reason_list_classes_exist(self) -> None:
        _, html, _ = self._render_pc817()
        self.assertIn('class="cv722-reason-list"', html)
        self.assertIn('class="cv722-list-index"', html)
        self.assertGreaterEqual(html.count("cv722-list-index"), 3)

    def test_action_list_classes_exist(self) -> None:
        _, html, _ = self._render_pc817()
        self.assertIn('class="cv722-action-list"', html)
        self.assertIn("Validate the approved alternate for PC817", html)

    def test_kpi_summary_semantic_label_value_elements(self) -> None:
        _, html, _ = self._render_pc817()
        for label in ("Status", "Priority component", "Confidence"):
            self.assertIn(label, html)
        self.assertIn("PC817", html)
        self.assertRegex(html, r'class="cv722-summary-label"[^>]*>Status</span>')
        self.assertRegex(html, r'class="cv722-summary-value"[^>]*>Review before release</strong>')
        self.assertRegex(html, r'class="cv722-summary-value"[^>]*>86%</strong>')

    def test_kpi_css_does_not_require_assistant_shell(self) -> None:
        block = self.v2_css.split("Sprint 72.2.3", 1)[1]
        for selector in (
            ".cv722-summary-strip",
            ".cv722-summary-label",
            ".cv722-summary-value",
            ".cv722-reason-list",
            ".cv722-action-list",
        ):
            self.assertIn(selector, block)
            rule = block.split(selector, 1)[1].split("}", 1)[0]
            self.assertNotIn(".cv-assistant-shell", rule)

    def test_expanded_assessment_classes_styled(self) -> None:
        _, html, _ = self._render_pc817()
        self.assertIn("cv722-expanded-assessment", html)
        self.assertIn("cv722-confidence-drivers-only", html)
        css_block = self.v2_css.split(".cv722-expanded-assessment", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid", css_block)

    def test_deep_assessment_structural_classes_have_css(self) -> None:
        for selector in (
            ".cv39-impact-label",
            ".cv46-driver-label",
            ".cv46-evidence-metric-label",
            ".cv47-ranking-title",
            ".cv39-progress-label",
        ):
            self.assertIn(selector, self.v2_css)

    def test_follow_up_panel_has_separation(self) -> None:
        self.assertIn("cv723-followups-panel", self.assistant_source)
        self.assertIn(".cv723-followups-panel", self.v2_css)
        block = self.v2_css.split(".cv723-followups-panel", 1)[1].split("}", 1)[0]
        self.assertIn("border-top", block)

    def test_responsive_media_queries_cover_breakpoints(self) -> None:
        section = self.v2_css.split("Sprint 72.2.3", 1)[1]
        self.assertIn("@media (max-width: 1024px)", section)
        self.assertIn("@media (max-width: 768px)", section)
        self.assertIn("@media (max-width: 390px)", section)
        tablet_block = section.split("@media (max-width: 768px)", 1)[1].split("}", 1)[0]
        self.assertIn(".cv722-summary-strip", tablet_block)
        self.assertIn("grid-template-columns: 1fr", tablet_block)

    def test_no_label_value_concatenation_in_markup(self) -> None:
        _, html, _ = self._render_pc817()
        self.assertNotRegex(html, r"StatusReview")
        self.assertNotRegex(html, r"Priority componentPC817")
        self.assertNotRegex(html, r"Confidence86%")
        self.assertNotRegex(html, r">Status[^<]*Review required</strong>")

    def test_no_direct_answer_duplication_in_expanded_assessment(self) -> None:
        _, html, _ = self._render_pc817()
        direct = "Review PC817 first because it represents the most immediate lifecycle and sourcing exposure in this BOM."
        self.assertEqual(html.count(direct), 1)

    def test_timeline_remains_gated_for_generic_review(self) -> None:
        assistant, html, _ = self._render_pc817()
        self.assertFalse(
            assistant._should_render_workflow_timeline(
                "What should I review first in this BOM?",
                detailed=False,
                workflow_text="",
                context=PC817_CONTEXT,
            )
        )
        self.assertNotIn("Priority timeline", html)

    def test_no_sprint_7143_helpers(self) -> None:
        for helper in (
            "_format_engineering_prose",
            "_inline_engineering_format",
            "_render_structured_answer_sections",
        ):
            self.assertNotIn(f"def {helper}", self.assistant_source)

    def test_no_arbitrary_llm_html_rendering(self) -> None:
        self.assertNotIn("unsafe_allow_html=True)", self.engineering_ai_source)
        self.assertNotIn("st.markdown(answer", self.assistant_source)

    def test_provider_auth_behavior_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)
        for marker in (
            "_queue_copilot_submission",
            "_apply_deferred_prompt_clear",
            "cv7142_ask_inflight",
        ):
            self.assertIn(marker, self.assistant_source)

    def test_mock_pc817_deterministic_render_contract(self) -> None:
        _, html, expander_calls = self._render_pc817()
        self.assertIn("What should I review first in this BOM?", html)
        self.assertIn("Key engineering reasons", html)
        self.assertIn("Recommended actions", html)
        self.assertIn("Evidence breakdown", html)
        self.assertEqual(len(expander_calls), 1)
        self.assertIn("View full engineering assessment", expander_calls[0][0][0])
        self.assertFalse(expander_calls[0][1].get("expanded"))

    def test_obsolete_cv46_why_css_removed(self) -> None:
        section_after_723 = self.v2_css.split("Sprint 72.2.3", 1)[1]
        self.assertNotIn(".cv46-why", section_after_723)
        self.assertNotIn("cv722-compact-decision", self.v2_css)
        self.assertNotIn("cv722-compact-label", self.v2_css)

    def test_quick_actions_wrapper_present(self) -> None:
        self.assertIn('class="cv722-quick-actions"', self.assistant_source)
        self.assertIn(".cv722-quick-actions", self.v2_css)


if __name__ == "__main__":
    unittest.main()
