"""Sprint 72.2.7 — Native Streamlit decision workspace tests."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"
ENGINEERING_AI_PY = REPO_ROOT / "src/services/engineering_ai.py"


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RecordingColumn:
    def __init__(self, side: str, st_module: types.ModuleType) -> None:
        self._side = side
        self._st = st_module

    def __enter__(self):
        self._st._active_column = self._side
        return self

    def __exit__(self, *args):
        self._st._active_column = None
        return False


def _install_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = {}
    st._active_column = None
    st.columns_calls: list[tuple[list[float], str | None]] = []
    markdown_calls: list[tuple[str, dict, str | None]] = []
    html_calls: list[str] = []

    def _markdown(content, **kwargs):
        markdown_calls.append((str(content), dict(kwargs), st._active_column))

    def _html(content, **kwargs):
        html_calls.append(str(content))

    def _columns(spec, gap=None):
        ratio = list(spec) if isinstance(spec, (list, tuple)) else [1] * int(spec)
        st.columns_calls.append((ratio, gap))
        return [_RecordingColumn("left", st), _RecordingColumn("right", st)]

    st.markdown = _markdown
    st.html = _html
    st.columns = _columns
    st.container = lambda **kwargs: _NullContext()

    scriptrunner = types.ModuleType("streamlit.runtime.scriptrunner")
    scriptrunner.get_script_run_ctx = lambda *args, **kwargs: types.SimpleNamespace(script_run_id="native-ws-run")
    runtime = types.ModuleType("streamlit.runtime")
    runtime.scriptrunner = scriptrunner
    components = types.ModuleType("streamlit.components.v1")
    components.html = lambda content, **kwargs: html_calls.append(str(content))

    sys.modules["streamlit"] = st
    sys.modules["streamlit.runtime"] = runtime
    sys.modules["streamlit.runtime.scriptrunner"] = scriptrunner
    sys.modules["streamlit.components"] = types.ModuleType("streamlit.components")
    sys.modules["streamlit.components.v1"] = components
    return st, markdown_calls, html_calls


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


class AskCadivorNativeWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.engineering_ai_source = ENGINEERING_AI_PY.read_text(encoding="utf-8")

    def _render_pc817(self):
        st, markdown_calls, html_calls = _install_streamlit_stub()
        assistant = _load_assistant()
        from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION

        with patch.object(assistant, "_render_response_scroll_anchor"):
            with patch.object(assistant, "_render_quick_actions"):
                assistant._render_response(
                    question=PC817_QUESTION,
                    answer=PC817_ANSWER,
                    context=PC817_CONTEXT,
                )
        html = "\n".join(content for content, _kwargs, _side in markdown_calls)
        left = "\n".join(content for content, _kwargs, side in markdown_calls if side == "left")
        right = "\n".join(content for content, _kwargs, side in markdown_calls if side == "right")
        return st, html, left, right, html_calls

    def test_uses_native_columns_ratio(self) -> None:
        st, _html, _left, _right, _html_calls = self._render_pc817()
        self.assertTrue(st.columns_calls)
        ratio, gap = st.columns_calls[0]
        self.assertEqual(ratio, [0.85, 1.15])
        self.assertEqual(gap, "medium")

    def test_no_giant_cv725_grid_shell(self) -> None:
        self.assertNotIn("def _build_decision_workspace_html", self.assistant_source)
        _st, html, _left, _right, _html_calls = self._render_pc817()
        self.assertNotIn("cv725-decision-workspace", html)

    def test_left_column_contains_answer_and_kpi(self) -> None:
        _st, _html, left, _right, _html_calls = self._render_pc817()
        self.assertIn("cv722-concise-answer", left)
        self.assertIn("cv722-summary-strip", left)
        self.assertIn("Review PC817 first.", left)

    def test_right_column_contains_assessment_without_details(self) -> None:
        _st, _html, _left, right, _html_calls = self._render_pc817()
        self.assertIn("cv727-assessment-panel", right)
        self.assertIn("Engineering Assessment", right)
        self.assertIn("cv724-impact-grid", right)
        self.assertNotIn("<details", right.lower())

    def test_duplicate_direct_answer_suppressed(self) -> None:
        _st, html, _left, _right, _html_calls = self._render_pc817()
        self.assertEqual(html.count("Review PC817 first."), 1)

    def test_evidence_cards_separated(self) -> None:
        _st, html, _left, right, _html_calls = self._render_pc817()
        self.assertIn("cv46-evidence-component", right)
        for bad in ("PC817Review", "BZX55C5V1Review", "DRV8825Review"):
            self.assertNotIn(bad, html)

    def test_visible_content_has_no_style_tag(self) -> None:
        _st, _html, left, right, _html_calls = self._render_pc817()
        visible = left + right
        self.assertNotIn("<style", visible.lower())

    def test_fake_assistant_shell_wrapper_removed(self) -> None:
        self.assertNotIn("cv-assistant-shell'>", self.assistant_source.replace(" ", ""))
        self.assertNotIn('<div class="cv-assistant-shell">', self.assistant_source)

    def test_css_uses_native_workspace_surfaces(self) -> None:
        section = self.v2_css.split("Sprint 72.2.7", 1)[1]
        self.assertIn(".cv727-assessment-panel", section)
        self.assertIn(".st-key-cv727_decision_workspace", section)
        self.assertNotIn(".cv725-decision-workspace", section)

    def test_full_path_harness_passes(self) -> None:
        from tests.harness_ask_cadivor_full_path import main as run_full_path

        self.assertEqual(run_full_path(), 0)

    def test_provider_auth_untouched(self) -> None:
        self.assertIn("def ask(", self.engineering_ai_source)
        self.assertNotIn("cv727-assessment-panel", self.engineering_ai_source)


if __name__ == "__main__":
    unittest.main()
