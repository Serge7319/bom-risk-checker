"""Sprint 72.1.1 — Ask Cadivor structured response field separation tests."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"

REVIVED_7143_HELPERS = (
    "_format_engineering_prose",
    "_inline_engineering_format",
    "_render_structured_answer_sections",
)


def _install_streamlit_stub(session_state: dict | None = None):
    st = types.ModuleType("streamlit")
    st.session_state = session_state if session_state is not None else {}
    markdown_calls: list[tuple[str, dict]] = []
    st.markdown = lambda content, **kwargs: markdown_calls.append((content, kwargs))
    st.columns = MagicMock(side_effect=lambda spec: [MagicMock() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))])
    st.expander = lambda *args, **kwargs: _NullContext()

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")

    class _Ctx:
        script_run_id = "run-a"

    scriptrunner.get_script_run_ctx = lambda: _Ctx()
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = MagicMock()

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st, markdown_calls


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AskCadivorStructuredResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def _load_assistant(self):
        for name in list(sys.modules):
            if name in {"src.components.engineering_assistant"} or name.startswith("src.components.engineering_assistant."):
                sys.modules.pop(name, None)
        import src.components.engineering_assistant as assistant

        return assistant

    def setUp(self) -> None:
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)

    def _render_sample_response(self) -> str:
        st_stub, markdown_calls = _install_streamlit_stub()
        assistant = self._load_assistant()
        sample_answer = (
            "### Intent\nGeneral Engineering Review\n"
            "### Executive Summary\nLine one.\nLine two.\n"
            "### Evidence\n- **U1** — lifecycle risk\n"
            "### Confidence\nMedium. Coverage is partial.\n"
        )
        context = {
            "analysis": {"analysis_id": "a1", "health_score": 93},
            "summary": {"health_score": 93, "release_posture": "focused_review"},
            "components": [{"part_number": "PC817", "risk_score": 40, "supplier_count": 2}],
            "coverage": {"score": 56},
        }
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                with patch.object(st_stub, "columns", side_effect=lambda spec: [MagicMock() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]):
                    assistant._render_response(
                        question="What should I review first?",
                        answer=sample_answer,
                        context=context,
                    )
        return "\n".join(content for content, _kwargs in markdown_calls if isinstance(content, str))

    def test_decision_confidence_label_value_separate_elements(self) -> None:
        html = self._render_sample_response()
        self.assertIn('class="cv722-summary-label"', html)
        self.assertIn('class="cv722-summary-value"', html)
        self.assertIn("Confidence", html)
        self.assertIn("56%", html)
        self.assertNotRegex(html, r"Confidence\s*56%")
        self.assertNotRegex(html, r"StatusReview")

    def test_bom_health_label_value_description_separated(self) -> None:
        html = self._render_sample_response()
        self.assertIn('class="cv39-impact-label"', html)
        self.assertIn('class="cv39-impact-value"', html)
        self.assertIn('class="cv39-impact-note"', html)
        self.assertIn("BOM health", html)
        self.assertIn("Projected after mitigation", html)

    def test_release_readiness_values_do_not_share_label_element(self) -> None:
        html = self._render_sample_response()
        self.assertRegex(
            html,
            r'class="cv39-impact-label"[^>]*>Release readiness</span>\s*<strong class="cv39-impact-value"[^>]*>Focused review → Ready</strong>',
        )

    def test_priority_component_label_value_separate(self) -> None:
        html = self._render_sample_response()
        self.assertRegex(
            html,
            r'class="cv722-summary-label"[^>]*>Priority component</span>\s*<strong class="cv722-summary-value"[^>]*>PC817</strong>',
        )

    def test_evidence_confidence_driver_fields_separated(self) -> None:
        html = self._render_sample_response()
        self.assertIn('class="cv46-driver-label"', html)
        self.assertIn('class="cv46-driver-value"', html)
        self.assertIn('class="cv46-driver-note"', html)

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
        self.assertEqual(
            assistant._plain_markdown("**Bold** text"),
            "Bold text",
        )

    def test_engineering_ai_ask_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)
        self.assertNotIn("cv39-kpi-label", self.engineering_ai_source)

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
        self.assertIn(".cv39-kpi-label", self.v2_css)
        self.assertIn(".cv39-impact-label", self.v2_css)
        self.assertIn("display: block", self.v2_css.split(".cv39-kpi-label", 1)[1].split("}", 1)[0])

    def test_executive_sidebar_uses_semantic_label_value_classes(self) -> None:
        html = self._render_sample_response()
        self.assertIn('class="cv722-section-label"', html)
        self.assertIn("Key engineering reasons", html)
        self.assertIn("Recommended actions", html)
        self.assertIn('class="cv722-reason-list"', html)
        self.assertIn('class="cv722-action-list"', html)

    def test_ranking_rows_use_separate_title_and_detail_classes(self) -> None:
        st_stub, markdown_calls = _install_streamlit_stub()
        assistant = self._load_assistant()
        sample_answer = (
            "### Intent\nGeneral Engineering Review\n"
            "### Rankings\n"
            "- **U1** — highest lifecycle risk\n"
            "- **U2** — supplier concentration\n"
        )
        context = {
            "analysis": {"analysis_id": "a1"},
            "components": [{"part_number": "U1", "risk_score": 90}],
            "coverage": {"score": 56},
        }
        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                with patch.object(st_stub, "columns", side_effect=lambda spec: [MagicMock() for _ in (spec if isinstance(spec, (list, tuple)) else range(int(spec)))]):
                    assistant._render_response(
                        question="Rank these parts",
                        answer=sample_answer,
                        context=context,
                    )
        html = "\n".join(content for content, _kwargs in markdown_calls if isinstance(content, str))
        self.assertIn('class="cv47-ranking-title"', html)
        self.assertIn('class="cv47-ranking-detail"', html)

    def test_shell_independent_polish_css_exists(self) -> None:
        self.assertIn("Sprint 72.1.2", self.v2_css)
        for selector in (
            ".cv49-side-label",
            ".cv47-ranking-detail",
            ".cv-assistant-followups-panel",
            ".cv35-section-label",
        ):
            self.assertIn(selector, self.v2_css)
            block = self.v2_css.split(selector, 1)[1].split("}", 1)[0]
            self.assertNotIn(".cv-assistant-shell", block)


if __name__ == "__main__":
    unittest.main()
