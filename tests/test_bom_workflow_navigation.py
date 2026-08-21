"""Focused regression checks for saved-BOM workflow continuity."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BomWorkflowNavigationTests(unittest.TestCase):
    def setUp(self):
        self.saved_modules = {name: sys.modules.get(name) for name in ("streamlit", "src.normalizer", "src.urls")}
        self.streamlit = types.ModuleType("streamlit")
        self.streamlit.session_state = {}
        self.streamlit.query_params = {}
        self.streamlit.rerun = lambda: None
        sys.modules["streamlit"] = self.streamlit
        normalizer = types.ModuleType("src.normalizer")
        normalizer.normalize_part_number = lambda value: str(value).strip().upper()
        sys.modules["src.normalizer"] = normalizer
        urls = types.ModuleType("src.urls")
        urls.internal_app_href = lambda *args, **kwargs: "/"
        sys.modules["src.urls"] = urls
        spec = importlib.util.spec_from_file_location("cadivor_bom_navigation_test", ROOT / "src/ui/navigation.py")
        self.navigation = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.navigation)

    def tearDown(self):
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_alternative_navigation_preserves_analysis_and_section_after_consumption(self):
        self.streamlit.session_state["cadivor_active_analysis_tab"] = "Components"
        self.navigation.navigate_to_alternative_finder(mpn="LM358N", analysis_id="bom-42", source_page="analysis_detail")
        context = self.navigation.consume_alternative_finder_context(lambda key, default="": default)
        self.assertEqual(context["analysis_id"], "bom-42")
        self.assertEqual(self.streamlit.session_state[self.navigation.ALT_FINDER_RETURN_ANALYSIS_KEY], "bom-42")
        self.assertEqual(self.streamlit.session_state[self.navigation.ALT_FINDER_RETURN_SECTION_KEY], "Components")

    def test_standalone_alternative_navigation_clears_previous_return(self):
        self.streamlit.session_state[self.navigation.ALT_FINDER_RETURN_ANALYSIS_KEY] = "old-bom"
        self.navigation.navigate_to_alternative_finder(mpn="LM358N")
        self.assertNotIn(self.navigation.ALT_FINDER_RETURN_ANALYSIS_KEY, self.streamlit.session_state)

    def test_external_context_preserves_return_after_query_cleanup(self):
        values = {"original_part": "LM358N", "analysis_id": "bom-21", "return_analysis_id": "bom-21"}
        self.navigation.consume_alternative_finder_context(lambda key, default="": values.get(key, default))
        self.assertEqual(self.streamlit.session_state[self.navigation.ALT_FINDER_RETURN_ANALYSIS_KEY], "bom-21")

    def test_reports_use_internal_navigation_and_selected_analysis(self):
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        start = source.index("incoming_report_analysis_id = str(")
        block = source[start:start + 250]
        self.assertIn('_qp_value("analysis_id", "")', block)
        self.assertIn('st.session_state.get("cadivor_active_analysis_id", "")', block)

    def test_bom_manager_has_explicit_saved_analysis_route(self):
        runtime = (ROOT / "src/authenticated_runtime.py").read_text()
        detail = (ROOT / "src/pages/analysis_detail.py").read_text()
        self.assertIn('not _show_saved_analyses', runtime)
        self.assertEqual(detail.count('show_saved_analyses="1"'), 2)

    def test_missing_lead_time_does_not_display_not_available_weeks(self):
        detail = (ROOT / "src/pages/analysis_detail.py").read_text()
        self.assertIn("html.escape(selected_lead_time_label)", detail)
        self.assertNotIn("html.escape(selected_lead_time)} weeks", detail)


if __name__ == "__main__":
    unittest.main()
