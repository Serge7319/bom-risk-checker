"""Sprint 72.3.1 — Real Streamlit API compatibility guards."""
from __future__ import annotations

import inspect
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINEERING_ASSISTANT_PY = REPO_ROOT / "src/components/engineering_assistant.py"
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"

import streamlit as real_st

from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules


class AskCadivorStreamlitApiCompatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.assistant_source = ENGINEERING_ASSISTANT_PY.read_text(encoding="utf-8")
        cls.v2_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
        cls.container_signature = inspect.signature(real_st.container)
        cls.columns_signature = inspect.signature(real_st.columns)

    def tearDown(self) -> None:
        restore_ask_cadivor_streamlit_modules()

    def test_installed_streamlit_version_reported(self) -> None:
        self.assertTrue(str(real_st.__version__).strip())

    def test_real_container_signature_has_no_key(self) -> None:
        self.assertNotIn("key", self.container_signature.parameters)

    def test_production_renderer_has_no_keyed_containers(self) -> None:
        self.assertIsNone(re.search(r"st\.container\(\s*key\s*=", self.assistant_source))

    def test_stub_rejects_unsupported_container_key(self) -> None:
        st = install_ask_cadivor_streamlit_stub()
        with self.assertRaises(TypeError):
            st.container(key="cv_conversation_exchange")
        restore_ask_cadivor_streamlit_modules()

    def test_native_surface_classes_present_in_css(self) -> None:
        self.assertIn(".cv50-exchange", self.v2_css)
        self.assertIn(".cv722-reason-list", self.v2_css)
        self.assertIn(".cv722-summary-strip", self.v2_css)
        self.assertIn(".cv46-evidence-card-header", self.v2_css)

    def test_native_renderer_uses_block_builders(self) -> None:
        self.assertIn("_build_concise_answer_html", self.assistant_source)
        self.assertIn("_build_assessment_panel_html", self.assistant_source)


def tearDownModule():
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
