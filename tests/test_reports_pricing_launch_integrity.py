"""Focused launch contracts for report truthfulness and supplier marketing."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text()
MARKETING = (ROOT / "marketing-web" / "index.html").read_text()
TREE = ast.parse(RUNTIME)


class ReportsPricingLaunchIntegrityTests(unittest.TestCase):
    def test_report_library_advertises_only_available_pdf_and_csv(self):
        start = RUNTIME.index("first_template_data = [")
        end = RUNTIME.index("second_template_cards = []", start)
        report_library = RUNTIME[start:end]
        self.assertNotIn('"Excel"', report_library)
        self.assertEqual(report_library.count('["PDF", "CSV"]'), 5)

    def test_decision_cache_changes_when_current_bom_evidence_changes(self):
        start = RUNTIME.index("report_evidence_df = (")
        end = RUNTIME.index("pdf_bytes = _build_executive_pdf(", start)
        evidence = RUNTIME[start:end]
        self.assertIn('report_evidence_df["Stock Available"]', evidence)
        self.assertIn('report_evidence_df["Supplier Count"]', evidence)
        self.assertIn("report_health_score", evidence)
        self.assertIn("hashlib.sha256", evidence)
        self.assertIn("evidence_fingerprint", evidence)
        self.assertIn("results_df=report_evidence_df", evidence)

    def test_executive_preview_and_decision_brief_share_current_evidence(self):
        start = RUNTIME.index("decision_brief = get_cached_decision_brief(")
        end = RUNTIME.index("ai_executive_pdf =", start)
        generation = RUNTIME[start:end]
        self.assertIn("results_df=report_evidence_df", generation)
        self.assertIn("selected_analysis,\n                report_evidence_df,", generation)

    def test_download_tracking_isolated_to_streamlit_fragment(self):
        helpers = [
            node for node in ast.walk(TREE)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_tracked_report_download"
        ]
        self.assertEqual(len(helpers), 1)
        helper = helpers[0]
        self.assertTrue(
            any(
                isinstance(decorator, ast.Attribute)
                and decorator.attr == "fragment"
                for decorator in helper.decorator_list
            )
        )
        helper_source = ast.get_source_segment(RUNTIME, helper)
        self.assertIn('"on_click": _record_session_report', helper_source)
        self.assertIn('"args": (report_type, file_name)', helper_source)
        self.assertNotIn('"ignore"', helper_source)

    def test_every_reports_download_uses_real_tracking_callback(self):
        start = RUNTIME.index("preview_tabs = st.tabs(")
        end = RUNTIME.index("action_cols = st.columns(3)", start)
        report_downloads = RUNTIME[start:end]
        self.assertNotIn("st.download_button(", report_downloads)
        self.assertNotIn('on_click="ignore"', report_downloads)
        self.assertEqual(report_downloads.count("_tracked_report_download("), 16)

    def test_first_download_completes_onboarding_without_repeating_writes(self):
        start = RUNTIME.index("def _record_session_report(")
        end = RUNTIME.index("@st.fragment", start)
        callback = RUNTIME[start:end]
        self.assertIn('if not st.session_state.get("onboarding_report_completed"):', callback)
        self.assertIn("_mark_first_report_complete()", callback)

    def test_octopart_is_live_without_claiming_it_is_a_distributor(self):
        coverage = MARKETING.split('<div class="coverage">', 1)[1].split("</div>", 1)[0]
        self.assertIn("SUPPLIER &amp; MARKET COVERAGE", coverage)
        self.assertIn("<b>Octopart</b>", coverage)
        self.assertNotIn("Planned", coverage)


if __name__ == "__main__":
    unittest.main()
