"""Focused launch contracts for report truthfulness and supplier marketing."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text()
DECISIONS = (ROOT / "src" / "engineering_decision_engine.py").read_text()
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

    def test_supporting_evidence_uses_the_saved_bom_health_score(self):
        self.assertIn('evidence.append(f"BOM health score: {health}/100")', DECISIONS)
        self.assertNotIn(
            'evidence.append(f"BOM health score: {intelligence_data[\'bom_health_score\']}/100")',
            DECISIONS,
        )

    def test_executive_pdf_uses_explicit_customer_typography(self):
        pdf_source = RUNTIME[
            RUNTIME.index("def _build_executive_pdf("):
            RUNTIME.index("        total_reports = len(report_records)")
        ]
        for style_name in (
            "CadivorReportTitle",
            "CadivorReportHeading",
            "CadivorReportBody",
        ):
            self.assertIn(style_name, pdf_source)
        self.assertIn('fontName="CadivorVera-Bold"', pdf_source)
        self.assertIn('fontName="CadivorVera"', pdf_source)
        self.assertIn('TTFont("CadivorVera"', pdf_source)
        self.assertNotIn('fontName="Helvetica"', pdf_source)

    def test_download_controls_prioritize_file_delivery_over_server_reruns(self):
        helpers = [
            node for node in ast.walk(TREE)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_report_download_button"
        ]
        self.assertEqual(len(helpers), 1)
        helper = helpers[0]
        self.assertFalse(helper.decorator_list)
        helper_source = ast.get_source_segment(RUNTIME, helper)
        self.assertIn('"on_click": "ignore"', helper_source)
        self.assertNotIn("_record_session_report", helper_source)

    def test_every_reports_download_uses_the_safe_download_helper(self):
        start = RUNTIME.index("preview_tabs = st.tabs(")
        end = RUNTIME.index("action_cols = st.columns(3)", start)
        report_downloads = RUNTIME[start:end]
        self.assertNotIn("st.download_button(", report_downloads)
        self.assertIn('"on_click": "ignore"', RUNTIME)
        self.assertEqual(report_downloads.count("_report_download_button("), 16)

    def test_reports_do_not_display_unreliable_session_download_counts(self):
        report_source = RUNTIME[RUNTIME.index("# ---------- Reports ----------"):]
        self.assertNotIn("reports_session_history", report_source)
        self.assertIn('label="Formats"', report_source)
        self.assertIn('value="PDF + CSV"', report_source)

    def test_reports_have_mobile_layout_guards(self):
        css_start = RUNTIME.index('<style id="cadivor-reports-professional-v9a">')
        css_end = RUNTIME.index("</style>", css_start)
        css = RUNTIME[css_start:css_end]
        self.assertIn("@media(max-width:760px)", css)
        self.assertIn("grid-template-columns:1fr", css)
        self.assertIn("@media(max-width:650px)", css)

    def test_octopart_is_live_without_claiming_it_is_a_distributor(self):
        coverage = MARKETING.split('<div class="coverage">', 1)[1].split("</div>", 1)[0]
        self.assertIn("SUPPLIER &amp; MARKET COVERAGE", coverage)
        self.assertIn("<b>Octopart</b>", coverage)
        self.assertNotIn("Planned", coverage)


if __name__ == "__main__":
    unittest.main()
