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

    def test_internal_navigation_commits_destination_in_widget_callback(self):
        reruns = []
        self.streamlit.rerun = lambda: reruns.append(True)

        def click_button(label, **kwargs):
            self.assertEqual(label, "Reports Center")
            kwargs["on_click"]()
            return True

        self.streamlit.button = click_button
        clicked = self.navigation.internal_nav_button(
            "Reports Center", "Reports", key="reports-test", analysis_id="bom-42"
        )

        self.assertTrue(clicked)
        self.assertEqual(self.streamlit.session_state["cadivor_route"], "Reports")
        self.assertEqual(self.streamlit.session_state["app_mode"], "Reports")
        self.assertEqual(
            self.streamlit.session_state["cadivor_nav_params"],
            {"page": "Reports", "analysis_id": "bom-42"},
        )
        self.assertEqual(reruns, [])

    def test_alternative_navigation_callback_preserves_return_context(self):
        reruns = []
        self.streamlit.rerun = lambda: reruns.append(True)
        self.streamlit.session_state["cadivor_active_analysis_tab"] = "Components"

        def click_button(label, **kwargs):
            kwargs["on_click"]()
            return True

        self.streamlit.button = click_button
        self.navigation.internal_nav_button(
            "Find Alternatives",
            self.navigation.ALTERNATIVE_FINDER_PAGE,
            key="alternatives-test",
            original_part="LM358N",
            analysis_id="bom-42",
            return_analysis_id="bom-42",
        )

        self.assertEqual(self.streamlit.session_state["cadivor_route"], "Alternative Finder")
        self.assertEqual(
            self.streamlit.session_state[self.navigation.ALT_FINDER_RETURN_ANALYSIS_KEY],
            "bom-42",
        )
        self.assertEqual(reruns, [])

    def test_direct_navigation_still_requests_one_rerun(self):
        reruns = []
        self.streamlit.rerun = lambda: reruns.append(True)

        self.navigation.navigate_to("Analysis Details", analysis_id="bom-42")

        self.assertEqual(self.streamlit.session_state["cadivor_route"], "Analysis Details")
        self.assertEqual(reruns, [True])

    def test_leaving_bom_analyzer_clears_transient_saved_bom_selection(self):
        self.streamlit.session_state.update(
            {
                "cadivor_route": "BOM Analyzer",
                "bom81_selected_analysis_ids": ["bom-42"],
                "bom81_pending_delete_ids": ["bom-42"],
                "bom81_saved_analysis_editor_revision": 2,
            }
        )

        self.navigation.navigate_to("Analysis Details", analysis_id="bom-42")

        self.assertEqual(self.streamlit.session_state["bom81_selected_analysis_ids"], [])
        self.assertEqual(self.streamlit.session_state["bom81_saved_analysis_editor_revision"], 3)
        self.assertNotIn("bom81_pending_delete_ids", self.streamlit.session_state)
        self.assertEqual(
            self.streamlit.session_state["cadivor_nav_params"]["analysis_id"], "bom-42"
        )

    def test_remaining_on_bom_analyzer_preserves_saved_bom_selection(self):
        self.streamlit.session_state.update(
            {
                "cadivor_route": "BOM Analyzer",
                "bom81_selected_analysis_ids": ["bom-42"],
                "bom81_saved_analysis_editor_revision": 2,
            }
        )

        self.navigation.navigate_to("BOM Analyzer", show_saved_analyses="1")

        self.assertEqual(
            self.streamlit.session_state["bom81_selected_analysis_ids"], ["bom-42"]
        )
        self.assertEqual(self.streamlit.session_state["bom81_saved_analysis_editor_revision"], 2)

    def test_other_page_navigation_does_not_change_saved_bom_state(self):
        self.streamlit.session_state.update(
            {
                "cadivor_route": "Reports",
                "bom81_selected_analysis_ids": ["bom-42"],
                "bom81_saved_analysis_editor_revision": 2,
            }
        )

        self.navigation.navigate_to("Analysis Details", analysis_id="bom-42")

        self.assertEqual(
            self.streamlit.session_state["bom81_selected_analysis_ids"], ["bom-42"]
        )
        self.assertEqual(self.streamlit.session_state["bom81_saved_analysis_editor_revision"], 2)

    def test_leaving_bom_analyzer_without_selection_does_not_remount_editor(self):
        self.streamlit.session_state["cadivor_route"] = "BOM Analyzer"

        self.navigation.navigate_to("Dashboard")

        self.assertNotIn("bom81_saved_analysis_editor_revision", self.streamlit.session_state)

    def test_saved_bom_editor_input_does_not_rebuild_from_selection(self):
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        start = source.index('editor_df = pd.DataFrame(', source.index('key="bom81_manager_sort"'))
        editor_input = source[start:source.index('edited_manager = st.data_editor(', start)]

        self.assertIn('"Select": False', editor_input)
        self.assertNotIn('.isin(current_selection)', editor_input)
        self.assertIn('bom81_saved_analysis_editor_revision', editor_input)

    def test_clear_selection_replaces_editor_widget_once(self):
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        start = source.index('key="bom81_clear_selection"')
        clear_handler = source[start:source.index('pending_delete_ids = [', start)]

        self.assertIn('"bom81_selected_analysis_ids"] = []', clear_handler)
        self.assertIn('"bom81_saved_analysis_editor_revision"]', clear_handler)
        self.assertIn('editor_revision + 1', clear_handler)

    def test_alternative_return_commits_in_widget_callback(self):
        source = (ROOT / "src/authenticated_runtime.py").read_text()
        start = source.index('def _return_to_saved_bom() -> None:')
        handler = source[start:source.index('st.markdown(', start)]

        self.assertIn('_rerun=False', handler)
        self.assertIn('on_click=_return_to_saved_bom', handler)


if __name__ == "__main__":
    unittest.main()
