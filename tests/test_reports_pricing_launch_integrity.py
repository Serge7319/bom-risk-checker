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
    def test_actionable_report_center_offers_only_available_pdf_and_csv(self):
        start = RUNTIME.index("preview_options = [")
        end = RUNTIME.index(
            "selected_preview = reports_workspace.selectbox(",
            start,
        )
        report_center = RUNTIME[start:end]
        self.assertNotIn("Excel", report_center)
        self.assertEqual(report_center.count('"mime": "application/pdf"'), 4)
        self.assertEqual(report_center.count('"mime": "text/csv"'), 4)
        self.assertEqual(report_center.count('key="report_package_'), 4)

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

    def test_pdf_export_uses_ascii_for_projected_health_direction(self):
        start = DECISIONS.index("def format_decision_brief_for_report(")
        report_formatter = DECISIONS[start:]
        self.assertIn('Projected BOM health: {int(_number(health.get(\'before\'), 0))} to ', report_formatter)
        self.assertNotIn('Projected BOM health: {int(_number(health.get(\'before\'), 0))} → ', report_formatter)

    def test_executive_pdf_uses_explicit_customer_typography(self):
        pdf_source = RUNTIME[
            RUNTIME.index("def _build_executive_pdf("):
            RUNTIME.index(
                '<style id="cadivor-reports-decision-workspace-v10">'
            )
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
        start = RUNTIME.index("def _report_download_button(")
        end = RUNTIME.index("action_cols = reports_workspace.columns(3", start)
        report_downloads = RUNTIME[start:end]
        helper_end = report_downloads.index("preview_options = [")
        helper_source = report_downloads[:helper_end]
        card_source = report_downloads[helper_end:]
        self.assertEqual(helper_source.count("st.download_button("), 1)
        self.assertNotIn("st.download_button(", card_source)
        self.assertIn('"on_click": "ignore"', RUNTIME)
        self.assertEqual(card_source.count('"key": f"report_center_'), 8)
        self.assertEqual(card_source.count('key=f"preview_'), 4)
        self.assertIn("_report_download_button(**download)", card_source)

    def test_reports_do_not_display_unreliable_session_download_counts(self):
        report_source = RUNTIME[RUNTIME.index("# ---------- Reports ----------"):]
        self.assertNotIn("reports_session_history", report_source)
        self.assertNotIn('label="Formats"', report_source)
        self.assertNotIn('value="PDF + CSV"', report_source)
        self.assertIn('key="reports_package_center"', report_source)
        self.assertNotIn("Professional report library", report_source)

    def test_reports_have_mobile_layout_guards(self):
        css_start = RUNTIME.index(
            '<style id="cadivor-reports-decision-workspace-v10">'
        )
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
