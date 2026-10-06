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
                '<style id="cadivor-reports-decision-workspace-v11">'
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
        end = RUNTIME.index(
            "reports_workspace_actions = reports_workspace.container(",
            start,
        )
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
            '<style id="cadivor-reports-decision-workspace-v11">'
        )
        css_end = RUNTIME.index("</style>", css_start)
        css = RUNTIME[css_start:css_end]
        self.assertIn("@media(max-width:760px)", css)
        self.assertIn("grid-template-columns:1fr", css)
        self.assertIn("@media(max-width:650px)", css)

    def test_marketing_names_only_configured_distributor_sources(self):
        coverage = MARKETING.split('<div class="coverage">', 1)[1].split("</div>", 1)[0]
        self.assertIn("DISTRIBUTOR DATA SOURCES", coverage)
        self.assertIn("COVERAGE VARIES BY PART", coverage)
        self.assertIn("<b>DigiKey</b>", coverage)
        self.assertIn("<b>Mouser</b>", coverage)
        self.assertIn("<b>Newark</b>", coverage)
        self.assertNotIn("Octopart", coverage)

    def test_marketing_demo_is_labeled_as_sample_and_uses_a_coherent_baseline(self):
        self.assertIn('class="sample-indicator">Illustrative sample', MARKETING)
        self.assertIn("ILLUSTRATIVE RELEASE REVIEW · SAMPLE BOM", MARKETING)
        self.assertIn("1,842 sample rows", MARKETING)
        self.assertIn('data-kpi-counter="72"', MARKETING)
        self.assertIn("BOM Health 72 · 4 blockers", MARKETING)
        self.assertIn("17 lifecycle alerts", MARKETING)
        self.assertIn("36 supplier records normalized", MARKETING)
        self.assertNotIn("Live review", MARKETING)
        self.assertNotIn("LIVE REVIEW", MARKETING)
        self.assertNotIn("LIVE RECOMMENDATION", MARKETING)

        marketing_js = (ROOT / "marketing-web" / "app.js").read_text()
        self.assertIn("$('#heroMonitoringStatus').textContent = i >= 10 ? 'Monitoring active'", marketing_js)
        self.assertIn("'Illustrative sample · 1,842 components'", marketing_js)


if __name__ == "__main__":
    unittest.main()
