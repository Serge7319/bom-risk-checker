"""Regression checks for the approved Home and monitoring page layout."""
from pathlib import Path
import unittest

from src.ui.ei_bom_report import engineering_intelligence_html
from src.ui.main_transition import (
    DELAY_ROUTE_BODY_REVEAL_KEY,
    MAIN_TRANSITION_KIND_KEY,
    should_defer_navigation_reveal,
)


ROOT = Path(__file__).resolve().parents[1]
APPROVED_PAGES = (ROOT / "src" / "ui" / "approved_pages.py").read_text(
    encoding="utf-8"
)
MONITORING_HOME_CSS = (
    ROOT / "src" / "assets" / "css" / "monitoring_home_alignment.css"
).read_text(encoding="utf-8")
MONITORING_FINAL_CSS = (
    ROOT / "src" / "assets" / "css" / "monitoring_table_final.css"
).read_text(encoding="utf-8")
CORE_UI = (ROOT / "src" / "ui" / "core_premium_ui.py").read_text(encoding="utf-8")
EI_BOM_REPORT = (ROOT / "src" / "ui" / "ei_bom_report.py").read_text(encoding="utf-8")
MARKETING_SITE = (ROOT / "src" / "marketing_site.py").read_text(encoding="utf-8")
MARKETING_WEB = (ROOT / "marketing-web" / "index.html").read_text(encoding="utf-8")
MARKETING_JS = (ROOT / "marketing-web" / "app.js").read_text(encoding="utf-8")


class ApprovedPageVisualContractTests(unittest.TestCase):
    def test_home_analysis_button_tracks_average_health_card_edge(self):
        self.assertNotIn('left:-5px!important', APPROVED_PAGES)
        self.assertIn('justify-content: flex-end !important;', MONITORING_HOME_CSS)
        self.assertIn('st-key-approved_home_new_bom"] button', MONITORING_HOME_CSS)

    def test_monitoring_kpis_override_streamlit_column_sizing(self):
        self.assertIn(
            '.st-key-approved_monitoring_kpi_grid [data-testid="stHorizontalBlock"]{display:flex!important;flex-flow:row nowrap!important;justify-content:flex-start!important;',
            APPROVED_PAGES,
        )
        self.assertIn(
            '.st-key-approved_monitoring_kpi_grid [data-testid="column"]{box-sizing:border-box!important;display:flex!important;flex:1 1 0!important;width:0!important;max-width:none!important;',
            APPROVED_PAGES,
        )
        self.assertNotIn(
            '.st-key-approved_monitoring_kpi_grid [data-testid="stHorizontalBlock"]{display:grid!',
            APPROVED_PAGES,
        )

    def test_monitoring_category_filter_is_one_stateful_required_pills_widget(self):
        monitoring_renderer = APPROVED_PAGES.split("def render_monitoring(", 1)[1]
        self.assertIn('selected = st.pills(', monitoring_renderer)
        self.assertIn('key="approved_alert_category"', monitoring_renderer)
        self.assertIn('selection_mode="single"', monitoring_renderer)
        self.assertIn('required=True', monitoring_renderer)
        self.assertIn('on_change=_reset_monitoring_severity', monitoring_renderer)
        self.assertIn('st.session_state["approved_alert_category"] = target_category', monitoring_renderer)
        self.assertIn('st.session_state["approved_alert_severity"] = target_severity', monitoring_renderer)
        self.assertNotIn('category_columns = st.columns', monitoring_renderer)
        self.assertNotIn('key=f"approved_monitoring_category_', monitoring_renderer)

    def test_monitoring_matches_home_centered_workspace_width(self):
        self.assertIn(
            ".st-key-approved_page_canvas_standard_render_monitoring",
            MONITORING_HOME_CSS,
        )
        self.assertNotIn(
            '[data-testid="stMainBlockContainer"]:has(.st-key-approved_page_canvas_standard_render_monitoring)',
            MONITORING_HOME_CSS,
        )
        monitoring_canvas = MONITORING_HOME_CSS.split(
            "/* Monitoring matches Home's centered 1,440px workspace canvas. */",
            1,
        )[1].split("/* Match the larger, card-based Monitoring mockup", 1)[0]
        self.assertIn("max-width: 1440px !important;", monitoring_canvas)
        self.assertIn("width: 100% !important;", monitoring_canvas)
        self.assertIn("margin-left: auto !important;", monitoring_canvas)
        self.assertIn("margin-right: auto !important;", monitoring_canvas)
        self.assertNotIn("max-width: none !important;", monitoring_canvas)
        self.assertIn(
            '.st-key-approved_bom_upload_panel{box-sizing:border-box!important;width:100%!important;max-width:none!important',
            APPROVED_PAGES,
        )
        self.assertIn('("render_monitoring", "standard")', APPROVED_PAGES)
        self.assertIn('.st-key-approved_monitoring_alert_card {', MONITORING_HOME_CSS)

    def test_approved_alternatives_shortcut_uses_widget_callback(self):
        shortcut = EI_BOM_REPORT.split(
            'f"View approved alternatives ({approved_count})"',
            1,
        )[1].split(
            'with st.container(key="ei_refresh_saved_analysis"',
            1,
        )[0]
        self.assertIn("on_click=_select_ei_report_tab", shortcut)
        self.assertIn('args=("Alternatives",)', shortcut)
        self.assertNotIn('st.session_state[tab_state_key] = "Alternatives"', shortcut)

    def test_home_primary_action_starts_the_trial_and_keeps_audit_separate(self):
        self.assertIn('data-auth="signup" data-intent="trial">Start 14-day trial</a>', MARKETING_WEB)
        self.assertIn('data-auth="signup" data-intent="trial">Start 14-day free trial <span>→</span></a>', MARKETING_WEB)
        self.assertIn('data-auth="signup" data-stress-cta="true">Try the free 5-part BOM audit</a>', MARKETING_WEB)
        self.assertIn("intent: a.dataset.intent || 'trial'", MARKETING_JS)
        self.assertIn('st.button("Start 14-Day Trial", key="cv_public_signup"', MARKETING_SITE)


    def test_navigation_cover_waits_for_the_complete_destination_render(self):
        navigation_state = {
            DELAY_ROUTE_BODY_REVEAL_KEY: True,
            MAIN_TRANSITION_KIND_KEY: "navigation",
        }
        self.assertTrue(should_defer_navigation_reveal(navigation_state))
        self.assertFalse(should_defer_navigation_reveal(navigation_state, force=True))
        self.assertFalse(
            should_defer_navigation_reveal(
                {
                    DELAY_ROUTE_BODY_REVEAL_KEY: True,
                    MAIN_TRANSITION_KIND_KEY: "blocking",
                }
            )
        )
        navigation_source = (ROOT / "src" / "ui" / "navigation.py").read_text(
            encoding="utf-8"
        )
        runtime_source = (ROOT / "src" / "authenticated_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "if should_defer_navigation_reveal(st.session_state, force=force):",
            navigation_source,
        )
        stop_wrapper = runtime_source.split("def stop_authenticated_page", 1)[1].split(
            "from src.ui.executive_workspace", 1
        )[0]
        self.assertIn("force=True", stop_wrapper)

    def test_bom_risk_summary_and_metrics_precede_component_review_table(self):
        markup = engineering_intelligence_html(
            bom_name="Synthetic BOM",
            part_count=0,
            tab="BOM Risk",
            parts=[],
            health_score=88,
        )
        self.assertLess(markup.index("cv-ei-banner"), markup.index("cv-ei-kpis"))
        self.assertLess(markup.index("cv-ei-kpis"), markup.index("cv-ei-table"))

    def test_home_saved_bom_actions_align_with_the_actions_column(self):
        home = APPROVED_PAGES.split("def render_home(", 1)[1].split(
            "def _render_approved_bom_upload_name_fields()", 1
        )[0]
        self.assertIn(
            'header_labels = ("Name", "Project", "Part count", "Health", "High-risk parts", "Last analyzed", "Actions")',
            home,
        )
        self.assertIn('cells = st.columns(home_widths, gap="small"', home)
        self.assertIn('_render_saved_bom_actions(cells[6],', home)
        self.assertIn("flex-direction:row!important", APPROVED_PAGES)
        self.assertIn("justify-content:center!important;gap:6px!important", APPROVED_PAGES)

    def test_monitoring_period_has_no_overlapping_date_caption(self):
        monitoring_renderer = APPROVED_PAGES.split("def render_monitoring(", 1)[1]
        self.assertNotIn("cv-ap-monitoring-period-range", monitoring_renderer)
        self.assertNotIn("_alert_date_range_label", APPROVED_PAGES)

    def test_monitoring_filters_and_actions_match_mockup(self):
        self.assertIn(
            '.st-key-approved_monitoring_category_row [role="radiogroup"]',
            MONITORING_FINAL_CSS,
        )
        self.assertIn("border-radius: 999px !important;", MONITORING_FINAL_CSS)
        self.assertIn("gap: 8px !important;", MONITORING_FINAL_CSS)
        self.assertIn('button[aria-pressed="true"]', MONITORING_FINAL_CSS)
        self.assertIn(
            '[class*="st-key-approved_alert_action_"] .stButton > button',
            MONITORING_HOME_CSS,
        )
        self.assertIn("border: 1px solid #70a4ff !important;", MONITORING_HOME_CSS)

    def test_monitoring_alert_rows_use_matching_bounded_grid(self):
        self.assertIn(
            '[class*="st-key-approved_monitoring_alert_row_"] [data-testid="stHorizontalBlock"]',
            MONITORING_HOME_CSS,
        )
        self.assertIn(
            'grid-template-columns: .8fr 1.3fr 1.9fr 1.2fr 1.2fr .28fr !important;',
            MONITORING_HOME_CSS,
        )

    def test_monitoring_row_boundary_and_blue_action_are_applied_after_global_polish(self):
        polish = CORE_UI.index("inject_sprint71_polish()")
        final_style = CORE_UI.index('id="cadivor-monitoring-table-final"', polish)
        self.assertGreater(final_style, polish)
        self.assertIn("width: calc(100% - 44px) !important;", MONITORING_FINAL_CSS)
        self.assertIn("width: calc(100% - 28px) !important;", MONITORING_FINAL_CSS)
        self.assertIn("border: 1px solid #70a4ff !important;", MONITORING_FINAL_CSS)
        self.assertIn("color: #2563eb !important;", MONITORING_FINAL_CSS)

    def test_monitoring_filter_pills_wrap_before_the_period_control_can_overlap(self):
        self.assertIn(
            "grid-template-columns: 42px minmax(0, 1fr) 356px !important;",
            MONITORING_FINAL_CSS,
        )
        self.assertIn("grid-template-columns: 42px minmax(0, 1fr) !important;", MONITORING_FINAL_CSS)
        self.assertIn("flex-flow: row wrap !important;", MONITORING_FINAL_CSS)
        self.assertIn("max-width: 100% !important;", MONITORING_FINAL_CSS)
        self.assertIn("border-radius: 999px !important;", MONITORING_FINAL_CSS)
        self.assertIn("background: #edf5ff !important;", MONITORING_FINAL_CSS)
        self.assertIn("color: #2563eb !important;", MONITORING_FINAL_CSS)

    def test_app_marketing_fallback_uses_authenticated_student_limits(self):
        self.assertIn("5 BOM analyses/month", MARKETING_SITE)
        self.assertIn("50 components/BOM", MARKETING_SITE)
        self.assertNotIn("3 BOM analyses/month", MARKETING_SITE)
        self.assertNotIn("25 components/BOM", MARKETING_SITE)
        self.assertIn("Request access</a>", MARKETING_SITE)

    def test_monitoring_filter_has_no_seven_column_button_layout_left_behind(self):
        all_monitoring_styles = MONITORING_HOME_CSS + MONITORING_FINAL_CSS + APPROVED_PAGES
        self.assertNotIn("st-key-approved_monitoring_filter_", all_monitoring_styles)
        self.assertNotIn('key=f"approved_monitoring_category_', all_monitoring_styles)
        monitoring_renderer = APPROVED_PAGES.split("def render_monitoring(", 1)[1]
        self.assertNotIn("category_columns = st.columns", monitoring_renderer)

if __name__ == "__main__":
    unittest.main()
