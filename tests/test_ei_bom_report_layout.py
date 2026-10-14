import unittest
from pathlib import Path

from src.ui.ei_bom_report import (
    EI_TABS,
    bom_catalog_html,
    detailed_risk_report_html,
    engineering_intelligence_html,
    _detailed_report_analyses,
    _detailed_report_analysis_label,
    _detailed_report_metadata_html,
    _format_detailed_report_date,
)


PARTS = [
    {
        "mpn": "MPN-001",
        "description": "32-bit Microcontroller",
        "manufacturer": "AlphaSemi",
        "risk_score": 92,
        "risk_level": "High",
        "stock_available": 0,
        "supplier_count": 1,
        "lifecycle_status": "Obsolete",
        "lead_time_weeks": 52,
        "best_source": "Digi-Key",
    },
    {
        "mpn": "MPN-002",
        "description": "Voltage Regulator",
        "manufacturer": "BetaChip",
        "risk_score": 28,
        "risk_level": "Medium",
        "stock_available": 40,
        "supplier_count": 2,
        "lifecycle_status": "Active",
        "best_source": "Mouser",
        "unit_price": "1.20",
    },
]
REPORT_SOURCE = (Path(__file__).resolve().parents[1] / "src" / "ui" / "ei_bom_report.py").read_text(encoding="utf-8")


class EngineeringIntelligenceLayoutTests(unittest.TestCase):
    def test_report_sections_use_one_stateful_selection_widget(self):
        self.assertIn("st.tabs(", REPORT_SOURCE)
        self.assertIn('key=tab_state_key', REPORT_SOURCE)
        self.assertIn('on_change="rerun"', REPORT_SOURCE)
        self.assertNotIn("st.segmented_control(", REPORT_SOURCE)
        self.assertNotIn('key=f"ei_tab_{slug}"', REPORT_SOURCE)

    def test_detailed_report_selector_lists_saved_boms_with_run_context(self):
        saved = [
            {
                "id": "analysis-1",
                "project_name": "Motor controller",
                "filename": "controller.csv",
                "created_at": "2026-10-13T09:30:00+00:00",
            },
            {
                "id": "analysis-2",
                "project_name": "Sensor board",
                "filename": "sensors.csv",
                "created_at": "2026-10-12T15:15:00+00:00",
            },
        ]
        options = _detailed_report_analyses(saved[1:], saved[0])

        self.assertEqual([row["id"] for row in options], ["analysis-2", "analysis-1"])
        self.assertEqual(_detailed_report_analysis_label(options[0]), "Sensor board")
        self.assertEqual(
            _detailed_report_analysis_label({
                "project_name": "Project_099 — Cadivor BOM Rev2",
                "filename": "Cadivor_BOM_Stress_Test.csv",
                "created_at": "2026-10-11T12:33:00+00:00",
            }),
            "Project_099 — Cadivor BOM Rev2",
        )
        self.assertEqual(
            _format_detailed_report_date("2026-10-11T12:33:00+00:00"),
            "October 11, 2026",
        )
        context = _detailed_report_metadata_html(
            bom_name="Project_099 — Cadivor BOM Rev2",
            source_filename="Cadivor_BOM_Stress_Test.csv",
            part_count=6,
            analyzed_on="2026-10-11T12:33:00+00:00",
        )
        self.assertIn("Cadivor_BOM_Stress_Test.csv", context)
        self.assertIn("October 11, 2026", context)
        self.assertNotIn("2026-10-11T12:33", context)

    def test_open_detailed_risk_report_is_a_visible_primary_button(self):
        self.assertIn('key=f"ei_open_detailed_risk_{analysis_id or \'saved\'}"', REPORT_SOURCE)
        self.assertIn('type="primary"', REPORT_SOURCE)
        self.assertIn(".st-key-cv_ei_detailed_report_action", REPORT_SOURCE)

    def test_report_renderer_has_saved_bom_selector_and_route_switch(self):
        renderer = REPORT_SOURCE.split("def render_engineering_intelligence_report", 1)[1]
        detailed = renderer.split(
            'if st.session_state.get("cadivor_show_detailed_risk"):',
            1,
        )[1]
        self.assertIn('st.selectbox(', detailed)
        self.assertIn('selector_col, _ = st.columns([1, 2]', detailed)
        self.assertIn('"Project / BOM"', detailed)
        self.assertIn('max-width:480px!important', REPORT_SOURCE)
        self.assertIn("on_change=_navigate_to_detailed_report_analysis", detailed)
        page_source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "pages"
            / "analysis_detail.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_load_saved_analysis_report_options(", page_source)
        self.assertIn("saved_analyses=saved_report_analyses", page_source)

    def test_bom_risk_uses_the_approved_review_structure(self):
        html = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="BOM Risk",
            parts=PARTS,
            health_score=72,
        )
        self.assertIn("Engineering Intelligence", html)
        self.assertIn("Engineering review required", html)
        self.assertIn("Review these components first", html)
        self.assertIn("MPN-001", html)
        self.assertIn("72/100", html)
        self.assertIn("cv-part-photo__image", html)
        self.assertNotIn("Supply & Availability", html)

    def test_supply_and_alternatives_keep_the_same_report_family(self):
        supply = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Supply & Availability",
            parts=PARTS,
        )
        alternatives = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Alternatives",
            parts=PARTS,
            alternatives=[{"original_mpn": "MPN-001", "alternative_mpn": "MPN-901"}],
        )
        self.assertIn("Supply and availability", supply)
        self.assertIn("Digi-Key", supply)
        self.assertIn("cv-part-photo__image", supply)
        self.assertIn("MPN-901", alternatives)
        self.assertIn("cv-part-photo", alternatives)
        empty = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Alternatives",
            parts=PARTS,
            alternatives=[],
        )
        self.assertIn(
            "No approved alternative is recorded for this BOM yet.",
            empty,
        )
        self.assertNotIn("cv-part-photo", empty)
        self.assertIn("BOM Risk", EI_TABS)
        self.assertIn("Supply & Availability", EI_TABS)
        self.assertIn("Alternatives", EI_TABS)

    def test_saved_approvals_are_visible_in_bom_risk_and_alternatives_tabs(self):
        approved = [{
            "original_part": "MPN-001",
            "alternative_part": "MPN-901",
            "decision": "Approved",
            "project_name": "Sample BOM",
            "engineer_name": "A. Engineer",
            "engineering_note": "Package and pinout reviewed",
            "source_snapshot": {
                "selected_alternative": {
                    "Manufacturer": "AlphaSemi",
                    "Description": "Replacement controller",
                }
            },
        }]
        risk = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="BOM Risk",
            parts=PARTS,
            approved_alternatives=approved,
        )
        self.assertIn("Approved alternative: MPN-901", risk)
        alternatives = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Alternatives",
            parts=PARTS,
            approved_alternatives=approved,
        )
        self.assertIn("Approved alternatives", alternatives)
        self.assertIn("MPN-901", alternatives)
        self.assertIn("A. Engineer", alternatives)

    def test_engineering_intelligence_page_explains_selected_tab_and_refresh_action(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "ei_bom_report.py").read_text()
        self.assertIn("st.tabs(", source)
        self.assertIn('on_change="rerun"', source)
        self.assertNotIn("st.segmented_control(", source)
        self.assertNotIn("cv-ei-tab-indicator-track", source)
        self.assertNotIn("_ei_tab_indicator_html", source)
        self.assertNotIn("cv-ei-selected-tab", source)
        self.assertIn("Open BOM to rerun", source)
        self.assertIn("saved_bom_action=\"open\"", source)

    def test_selected_tab_uses_native_indicator_and_right_aligned_tablist(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "ei_bom_report.py").read_text()
        self.assertIn("st.tabs(", source)
        self.assertIn('on_change="rerun"', source)
        self.assertIn('[role="tablist"]', source)
        self.assertIn("justify-content:flex-end!important", source)
        self.assertNotIn("st.segmented_control(", source)
        self.assertNotIn("cv-ei-tab-indicator-track", source)

    def test_tables_use_catalog_photos_and_the_same_placeholder(self):
        catalog = "https://media.digikey.com/Photos/Texas%20Instruments/LM358.jpg"
        parts = [dict(PARTS[0], image_url=catalog), PARTS[1]]
        html = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="Lifecycle",
            parts=parts,
        )
        self.assertIn(f'src="{catalog}"', html)
        self.assertIn("Product photo for MPN-001", html)
        self.assertIn("Representative component image; actual part may vary", html)
        self.assertNotIn("Product photo for MPN-002", html)
        self.assertIn('data-illustration="ic"', html)
        self.assertNotIn("https://example.test", html)

    def test_detailed_risk_report_expands_the_selected_part(self):
        html = detailed_risk_report_html(
            bom_name="Sample BOM",
            analyzed_on="Apr 26, 2025",
            parts=PARTS,
            expanded_mpn="MPN-001",
        )
        self.assertIn("Detailed Risk Report", html)
        self.assertIn("Risk drivers", html)
        self.assertIn("Recommended action", html)
        self.assertIn("MPN-001", html)

    def test_review_alternative_parts_action_is_a_prefilled_link(self):
        report = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="BOM Risk",
            parts=PARTS,
            analysis_id="analysis-1",
        )
        self.assertIn("Review alternative parts</a>", report)
        self.assertIn("page=Alternative%20Finder", report)
        self.assertIn("original_part=MPN-001", report)
        self.assertIn("analysis_id=analysis-1", report)
        self.assertRegex(report, r"prefill_id=[a-f0-9]{32}")
        again = engineering_intelligence_html(
            bom_name="Sample BOM",
            part_count=2,
            tab="BOM Risk",
            parts=PARTS,
            analysis_id="analysis-1",
        )
        first_token = __import__("re").search(r"prefill_id=([a-f0-9]{32})", report).group(1)
        next_token = __import__("re").search(r"prefill_id=([a-f0-9]{32})", again).group(1)
        self.assertNotEqual(first_token, next_token)

    def test_review_alternative_handoff_prefills_the_clicked_part(self):
        import streamlit as st
        from src.alternative_finder_state import (
            get_alternative_finder_original_part_input_config,
        )
        from src.ui.navigation import (
            apply_alternative_finder_prefill,
            consume_alternative_finder_context,
        )

        st.session_state.clear()
        st.session_state["alternative_finder_nav_consumed_token"] = "analysis-1::MPN001"
        query = {
            "original_part": "MPN-001",
            "analysis_id": "analysis-1",
            "prefill_id": "fresh-click-id",
            "manufacturer": "AlphaSemi",
        }
        context = consume_alternative_finder_context(
            lambda key, default="": query.get(key, default)
        )
        apply_alternative_finder_prefill(context or {})
        widget_key, initial_value = get_alternative_finder_original_part_input_config(
            st.session_state
        )
        self.assertNotEqual(widget_key, "alternative_original_part")
        self.assertEqual(initial_value, "MPN-001")
        self.assertEqual(st.session_state[widget_key], "MPN-001")
        self.assertTrue(st.session_state["alternative_prefill_search_pending"])
        self.assertEqual(st.session_state["alternative_original_manufacturer"], "AlphaSemi")
        runtime = Path("src/authenticated_runtime.py").read_text(encoding="utf-8")
        self.assertIn("key=original_part_widget_key", runtime)
        self.assertIn('st.session_state.pop("alternative_prefill_search_pending", False)', runtime)
        self.assertIn("st.session_state.get(original_part_widget_key)", runtime)

    def test_reclicking_same_part_gets_a_fresh_prefilled_input(self):
        import streamlit as st
        from src.alternative_finder_state import (
            get_alternative_finder_original_part_input_config,
            init_alternative_finder_state,
            rearm_alternative_finder_navigation,
        )
        from src.ui.navigation import (
            apply_alternative_finder_prefill,
            build_alternative_finder_context,
        )

        state = st.session_state
        state.clear()
        init_alternative_finder_state(state)
        first = build_alternative_finder_context(
            mpn="MCP2551-I/SN",
            manufacturer="Microchip",
            analysis_id="analysis-1",
            prefill_id="first-click",
        )
        apply_alternative_finder_prefill(first)
        first_key, first_value = get_alternative_finder_original_part_input_config(state)
        self.assertEqual(first_value, "MCP2551-I/SN")
        state[first_key] = "STALE-EDIT"
        state["alternative_finder_result"] = {
            "status": "completed",
            "entered_mpn": "MCP2551-I/SN",
        }

        rearm_alternative_finder_navigation(state)
        second = build_alternative_finder_context(
            mpn="MCP2551-I/SN",
            manufacturer="Microchip",
            analysis_id="analysis-1",
            prefill_id="second-click",
        )
        apply_alternative_finder_prefill(second)
        second_key, second_value = get_alternative_finder_original_part_input_config(state)

        self.assertNotEqual(first_key, second_key)
        self.assertEqual(second_value, "MCP2551-I/SN")
        self.assertEqual(state[second_key], "MCP2551-I/SN")
        self.assertEqual(state["alternative_finder_result"]["status"], "completed")
        self.assertNotIn("alternative_prefill_search_pending", state)

    def test_bom_risk_clear_state_does_not_show_engineering_review_warning(self):
        from src.ui.ei_bom_report import engineering_intelligence_html

        html = engineering_intelligence_html(
            bom_name="Healthy BOM",
            part_count=1,
            tab="BOM Risk",
            parts=[{"mpn": "R-1", "risk_level": "Low", "risk_score": 12}],
        )
        self.assertIn("No high-risk components found", html)
        self.assertNotIn("Engineering review required", html)

    def test_engineering_intelligence_tabs_commit_before_the_page_rerun(self):
        source = Path("src/ui/ei_bom_report.py").read_text(encoding="utf-8")
        renderer = source.split("def render_engineering_intelligence_report", 1)[1]
        tabs = renderer.split("if st.session_state.get(\"cadivor_show_detailed_risk\"):", 1)[0]
        self.assertIn("st.tabs(", tabs)
        self.assertIn("key=tab_state_key", tabs)
        self.assertIn('on_change="rerun"', tabs)
        self.assertNotIn("st.segmented_control(", tabs)
        self.assertIn("with tab_panels[EI_TABS.index(tab)]:", renderer)
        self.assertNotIn("st.rerun()", tabs)

    def test_detailed_risk_rows_keep_package_for_the_correct_fallback_photo(self):
        from src.part_images import part_image_markup, part_image_source
        from src.ui.ei_bom_report import _part_rows

        row = _part_rows(
            [{
                "mpn": "CAP-TH",
                "description": "Radial through-hole capacitor",
                "category": "Capacitor",
                "package": "Radial through-hole",
            }]
        )[0]
        self.assertEqual(row["package"], "Radial through-hole")
        expected = part_image_source(
            "",
            "CAP-TH",
            category="Capacitor",
            part={"category": "Capacitor", "package": "Radial through-hole"},
        )
        self.assertIn(f'src="{expected}"', part_image_markup("", "CAP-TH", part=row))

    def test_new_contextual_click_is_not_blocked_by_an_old_consumed_mpn(self):
        from src.alternative_finder_state import should_apply_alternative_finder_prefill

        state = {"alternative_finder_nav_consumed_token": "analysis-1::MPN001"}
        self.assertTrue(
            should_apply_alternative_finder_prefill(
                state,
                mpn="MPN-001",
                analysis_id="analysis-1",
                navigation_id="new-click-identifier",
            )
        )

    def test_saved_markup_is_not_shown_as_a_component_description(self):
        from src.ui.ei_bom_report import _description_text

        markup = (
            "<p>Manufacturer AlphaSemi</p><p>Best source Digi-Key</p>"
            "<p>Lifecycle Obsolete</p>"
        )
        escaped = markup.replace("<", "&lt;").replace(">", "&gt;")
        deeply_escaped = markup
        for _ in range(8):
            deeply_escaped = (
                deeply_escaped.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
        self.assertEqual(_description_text(deeply_escaped), "")
        descriptions = (markup, escaped, escaped.replace("&", "&amp;"), deeply_escaped)
        for description in descriptions:
            with self.subTest(description=description[:20]):
                report = detailed_risk_report_html(
                    bom_name="Sample BOM",
                    analyzed_on="Apr 26, 2025",
                    parts=[dict(PARTS[0], description=description)],
                    expanded_mpn="MPN-001",
                )
                self.assertNotIn("<p>Manufacturer AlphaSemi</p><p>Best source Digi-Key", report)
                self.assertNotIn("Manufacturer AlphaSemi Best source Digi-Key Lifecycle Obsolete", report)

    def test_expanded_detailed_risk_markup_is_dedented_html(self):
        from src.ui.ei_bom_report import _detailed_risk_expanded_markup, _part_rows

        row = _part_rows([PARTS[0]])[0]
        markup = _detailed_risk_expanded_markup(
            row,
            reasons="<li>No stock at approved suppliers</li>",
            alternative_link="<a href=\"/alternatives\">Review alternative parts</a>",
        )
        self.assertTrue(markup.startswith('<div class="cv-risk-detail"'))
        self.assertIn("<p><strong>Manufacturer</strong>", markup)
        self.assertNotRegex(markup, r"(?m)^ {4,}<p><strong>")

    def test_detailed_risk_image_and_open_row_styles_are_subtle(self):
        report_source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "ei_bom_report.py").read_text()
        core_source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "core_premium_ui.py").read_text()
        self.assertIn(".st-key-ei_report_workspace .cv-part-photo { border-radius:8px!important; }", report_source)
        self.assertIn('background:#f8fafc !important;border-left:0 !important;border-radius:12px !important', core_source)
        self.assertNotIn('border-left:3px solid #2563eb !important', core_source)

    def test_detailed_risk_starts_collapsed_until_a_part_is_selected(self):
        report = detailed_risk_report_html(
            bom_name="Sample BOM",
            analyzed_on="Apr 26, 2025",
            parts=PARTS,
        )
        self.assertNotIn("cv-risk-detail", report)
        selected = detailed_risk_report_html(
            bom_name="Sample BOM",
            analyzed_on="Apr 26, 2025",
            parts=PARTS,
            expanded_mpn="MPN-001",
        )
        self.assertIn("cv-risk-detail", selected)

    def test_cost_insights_does_not_treat_a_zero_price_as_money(self):
        parts = [
            {
                "mpn": "MAX32625ITK+",
                "manufacturer": "Analog Devices",
                "risk_level": "High",
                "risk_reasons": "Lifecycle and single-source exposure require a replacement review.",
                "unit_price": 0.0,
                "stock_available": 0,
            },
            {
                "mpn": "TPS54331D",
                "manufacturer": "Texas Instruments",
                "risk_level": "Medium",
                "risk_reasons": "Lead time is longer than the release window.",
                "unit_price": 1.2,
                "quantity": 10,
                "primary_supplier": "DigiKey",
                "stock_available": 1200,
                "product_url": "https://www.digikey.com/en/products/detail/ti/TPS54331D/1",
            },
        ]
        html = engineering_intelligence_html(
            bom_name="Industrial Controller BOM",
            part_count=2,
            tab="Cost Insights",
            parts=parts,
        )
        self.assertIn("Not recorded", html)
        self.assertNotIn("0.0", html)
        self.assertNotIn("$0.00", html)
        self.assertNotIn(">Best source<", html)
        self.assertIn("Recorded source", html)
        self.assertIn("DigiKey", html)
        self.assertIn("$1.2", html)
        self.assertIn("$12", html)
        self.assertIn("https://www.digikey.com/en/products/detail/ti/TPS54331D/1", html)
        self.assertIn("A distributor comparison is unavailable.", html)
        self.assertNotIn("Not labeled best", html)
        self.assertIn("Lifecycle and single-source exposure require a replacement review.", html)
        self.assertIn("Not calculated", html)
        self.assertIn("Re-run the BOM analysis", html)

    def test_bom_catalog_is_a_list_not_an_intelligence_report(self):
        html = bom_catalog_html(
            [
                {
                    "project_name": "Orion Controller",
                    "filename": "orion_controller_revB.xlsx",
                    "total_parts": 124,
                    "health_score": 90,
                    "high_risk_count": 2,
                    "updated_label": "Aug 26, 2024",
                }
            ]
        )
        self.assertIn("BOMs", html)
        self.assertIn("Orion Controller", html)
        self.assertIn("Healthy", html)
        self.assertNotIn("Engineering review required", html)


    def test_detailed_risk_table_header_is_attached_to_a_shared_table_frame(self):
        source = Path("src/ui/ei_bom_report.py").read_text(encoding="utf-8")
        self.assertIn('with st.container(key="cv_detailed_risk_table"):', source)
        self.assertIn('with st.container(key="cv_detailed_risk_table_header"):', source)
        self.assertIn("border:1px solid #cbd8e8", source)
        self.assertIn("background:#f7f9fc;border-bottom:1px solid #dce4ef", source)
        self.assertNotIn(
            ".cv-risk-grid-head { background:#f1f5f9;border:1px solid #e2e8f0",
            source,
        )

    def test_detailed_risk_row_separators_have_clear_contrast(self):
        source = Path("src/ui/ei_bom_report.py").read_text(encoding="utf-8")
        self.assertIn(".cv-risk-row { border-top:1px solid #e5ebf3", source)
        self.assertIn("border-bottom:1px solid #e5ebf3!important", source)
        self.assertIn("box-shadow:none!important", source)

if __name__ == "__main__":
    unittest.main()
