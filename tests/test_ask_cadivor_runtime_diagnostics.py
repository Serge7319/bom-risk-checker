"""Sprint 72.3.5 — Ask Cadivor production runtime identity diagnostics."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules
from tests.harness_ask_cadivor_presentation import PC817_ANSWER, PC817_CONTEXT, PC817_QUESTION


def _load_assistant():
    for name in list(sys.modules):
        if name.startswith("src.components.engineering_assistant"):
            sys.modules.pop(name, None)
    import src.components.engineering_assistant as assistant

    return assistant


def _render_pc817_capture(*, silence_diagnostics: bool = False):
    st = install_ask_cadivor_streamlit_stub()
    session_before = deepcopy(dict(st.session_state))
    assistant = _load_assistant()
    patches = [
        patch.object(assistant, "_render_response_scroll_anchor"),
        patch.object(assistant, "_render_quick_actions"),
    ]
    if silence_diagnostics:
        patches.extend(
            [
                patch.object(assistant, "_log_ask_runtime_identity"),
                patch.object(assistant, "_log_ask_runtime_surface"),
                patch.object(assistant, "_log_ask_runtime_css_contract"),
            ]
        )
    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        assistant._render_response(
            question=PC817_QUESTION,
            answer=PC817_ANSWER,
            context=PC817_CONTEXT,
        )
    html = "\n".join(content for content, _kwargs, _side in st.markdown_calls)
    session_after = deepcopy(dict(st.session_state))
    return {
        "html": html,
        "markdown_calls": list(st.markdown_calls),
        "columns_calls": list(st.columns_calls),
        "session_before": session_before,
        "session_after": session_after,
    }


class AskCadivorRuntimeDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        restore_ask_cadivor_streamlit_modules()

    def tearDown(self) -> None:
        restore_ask_cadivor_streamlit_modules()

    def test_runtime_diagnostics_do_not_mutate_rendering_or_session_state(self) -> None:
        with_diagnostics = _render_pc817_capture(silence_diagnostics=False)
        without_diagnostics = _render_pc817_capture(silence_diagnostics=True)

        self.assertEqual(with_diagnostics["html"], without_diagnostics["html"])
        self.assertEqual(with_diagnostics["markdown_calls"], without_diagnostics["markdown_calls"])
        self.assertEqual(with_diagnostics["columns_calls"], without_diagnostics["columns_calls"])
        self.assertEqual(with_diagnostics["session_after"], without_diagnostics["session_after"])

    def test_runtime_identity_log_is_metadata_only(self) -> None:
        assistant = _load_assistant()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            assistant._log_ask_runtime_identity()
        output = buffer.getvalue()
        self.assertIn("ASK_RUNTIME commit_sha=", output)
        self.assertIn("streamlit_version=", output)
        self.assertIn("renderer_version=72.3.2", output)
        self.assertIn("renderer_module=", output)
        self.assertIn("css_path=", output)
        self.assertIn("css_exists=", output)
        self.assertIn("css_bytes=", output)
        self.assertIn("css_sha256=", output)
        self.assertIn("response_path=native_085_115", output)
        self.assertIn("ASK_RUNTIME css_contract cv50=", output)
        self.assertNotIn(PC817_QUESTION, output)
        self.assertNotIn("Review PC817 first.", output)

    def test_runtime_surface_logs_fire_on_render(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _render_pc817_capture(silence_diagnostics=False)
        output = buffer.getvalue()
        for event in (
            "exchange_render",
            "answer_render",
            "decision_summary_render",
            "assessment_render",
            "evidence_render",
        ):
            self.assertIn(f"ASK_RUNTIME {event}", output)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
