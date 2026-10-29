"""Regression contract for slow-route transition ownership."""
from __future__ import annotations

import ast
import html
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, MutableMapping


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "ui" / "main_transition.py").read_text(encoding="utf-8")


class MainTransitionSlowRouteContractTests(unittest.TestCase):
    def test_opening_clips_the_complete_main_viewport(self):
        self.assertIn(
            "width:calc(100vw - var(--cv-foundation-rail,228px))!important",
            SOURCE,
        )
        self.assertIn("clip-path:inset(0)!important", SOURCE)
        self.assertIn("z-index:2147483000!important", SOURCE)
        self.assertIn("pointer-events:auto!important", SOURCE)
        self.assertIn('[data-stale="true"]:not(', SOURCE)

    def test_route_cover_is_painted_before_shell_role_lookup(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        cover = runtime.index(
            'mount_main_transition_loading(_shell_route, paint_markup=True)'
        )
        role_lookup = runtime.index("def _read_users_role_for_shell")
        self.assertLess(cover, role_lookup)

    def test_transition_cover_uses_synchronous_non_iframe_html(self):
        paint = SOURCE.split("def _paint_main_transition_markup", 1)[1].split(
            "def paint_prepared_main_transition", 1
        )[0]
        self.assertIn("st.html(route_loading_markup(route, gen))", paint)
        self.assertNotIn("components.html(", paint)
        self.assertNotIn("window.parent", paint)
        self.assertNotIn("with container(key=owner_key)", paint)

    def test_unarmed_route_change_infers_compact_navigation_kind(self):
        helper = next(
            node for node in ast.parse(SOURCE).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_infer_unarmed_transition_kind"
        )
        module = ast.Module(body=[helper], type_ignores=[])
        namespace = {}
        exec(compile(ast.fix_missing_locations(module), "<transition-kind>", "exec"), namespace)
        infer_kind = namespace["_infer_unarmed_transition_kind"]
        self.assertEqual(infer_kind("Monitoring", "Analysis Details"), "navigation")
        self.assertEqual(infer_kind("BOM Analyzer", ""), "")

        prepare = SOURCE.split("def prepare_main_transition", 1)[1].split(
            "def _paint_main_transition_markup", 1
        )[0]
        self.assertIn("if not state.get(MAIN_TRANSITION_ACTIVE_KEY):", prepare)
        self.assertIn("_infer_unarmed_transition_kind(route, previous_route)", prepare)
        self.assertIn("state[MAIN_TRANSITION_KIND_KEY] = inferred_kind", prepare)

    def test_navigation_cover_has_inline_first_paint_fallback(self):
        namespace = {
            "html": html,
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
            "MAIN_TRANSITION_KIND_KEY": "cadivor_main_transition_kind",
            "MAIN_TRANSITION_PREVIOUS_ROUTE_KEY": "cadivor_main_transition_previous_route",
            "st": SimpleNamespace(session_state={"cadivor_main_transition_kind": "navigation"}),
        }
        helper = next(
            node for node in ast.parse(SOURCE).body
            if isinstance(node, ast.FunctionDef) and node.name == "route_loading_markup"
        )
        module = ast.Module(body=[helper], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "<route-loading>", "exec"), namespace)
        markup = namespace["route_loading_markup"]("Monitoring", 22)

        self.assertIn("position:fixed", markup)
        self.assertIn("left:calc(var(--cv-foundation-rail,296px) + 28px)", markup)
        self.assertIn("background:transparent", markup)
        self.assertNotIn("background:#F5F7FB", markup)
        self.assertIn("z-index:2147483000", markup)
        self.assertIn('role="status" aria-label="Loading Monitoring" aria-live="polite"', markup)
        self.assertIn("box-sizing:border-box;width:184px", markup)

    def test_regular_navigation_covers_partial_render_until_destination_is_complete(self):
        namespace = {
            "html": html,
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
            "MAIN_TRANSITION_KIND_KEY": "cadivor_main_transition_kind",
            "MAIN_TRANSITION_PREVIOUS_ROUTE_KEY": "cadivor_main_transition_previous_route",
            "st": SimpleNamespace(session_state={
                "cadivor_main_transition_kind": "navigation",
                "cadivor_main_transition_previous_route": "Engineering Decisions",
            }),
        }
        helper = next(
            node for node in ast.parse(SOURCE).body
            if isinstance(node, ast.FunctionDef) and node.name == "route_loading_markup"
        )
        module = ast.Module(body=[helper], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "<route-loading>", "exec"), namespace)
        markup = namespace["route_loading_markup"]("Portfolio Intelligence", 21)
        self.assertIn('data-cadivor-transition-kind="navigation"', markup)
        self.assertIn("cv-main-transition-progress", markup)
        self.assertIn('class="cv-main-transition-mark"', markup)
        self.assertIn(">C</div>", markup)
        self.assertNotIn("Opening Portfolio Intelligence", markup)
        nav_css = SOURCE.split(
            '.cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"]{{',
            1,
        )[1].split("}}", 1)[0]
        self.assertIn("background:transparent!important", nav_css)
        self.assertIn("pointer-events:none!important", nav_css)
        self.assertNotIn("height:calc(100dvh - var(--cv-foundation-top,64px))!important", nav_css)
        self.assertNotIn(
            "visibility:hidden!important;opacity:0!important;pointer-events:none!important;\n          transition:none!important",
            SOURCE,
        )
        self.assertIn("does not paint an opaque", SOURCE)
        self.assertIn(
            ':not([data-cadivor-transition-kind="navigation"]) {{\n          pointer-events:auto!important',
            SOURCE,
        )

    def test_reveal_marker_hides_the_matching_transition_generation(self):
        reveal = SOURCE.split("def reveal_main_transition", 1)[1]
        self.assertIn("data-cadivor-page-body", reveal)
        self.assertIn("data-cadivor-page-body-release-gen", reveal)
        self.assertNotIn("_remove_transition_portal", reveal)

    def test_old_generation_css_cannot_hide_the_next_route_transition(self):
        # Streamlit can retain prior style blocks across reruns. Every rule that
        # hides an Opening layer must therefore be scoped to its own generation.
        self.assertNotIn(
            '[data-stale="true"] .cv-main-transition.cv-route-loading,',
            SOURCE,
        )
        self.assertIn(
            'body:has([data-cadivor-page-body-gen="{gen}"][data-cadivor-page-body-release-gen="{gen}"])\n'
            '          .cv-main-transition.cv-route-loading[data-cadivor-transition-gen="{gen}"]',
            SOURCE,
        )

    def test_transition_stylesheets_remain_generation_scoped_without_dom_cleanup(self):
        self.assertIn('id="cadivor-main-transition-css-{gen}"', SOURCE)
        self.assertIn("style[id^=\"cadivor-main-transition-css-\"]", SOURCE)
        core_css = (ROOT / "src" / "assets" / "css" / "core_premium_ui_final.css").read_text(
            encoding="utf-8"
        )
        core_ui = (ROOT / "src" / "ui" / "core_premium_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('style[id^="cadivor-main-transition-css-"]', core_css)
        self.assertIn('style[id^="cadivor-main-transition-css-"]', core_ui)
        self.assertNotIn("style#cadivor-main-transition-css,", core_css)
        self.assertNotIn("style#cadivor-main-transition-css,", core_ui)
        self.assertIn(
            '[data-stale="true"] .cv-main-transition.cv-route-loading:not([data-cadivor-transition-gen="{gen}"])',
            SOURCE,
        )
        self.assertIn(
            '[data-stale="true"][data-cadivor-main-transition="1"]:not([data-cadivor-transition-gen="{gen}"])',
            SOURCE,
        )

    def test_transition_injection_uses_scoped_css_without_mutating_streamlit_hosts(self):
        inject = SOURCE.split("def inject_main_transition_css", 1)[1].split(
            "def route_loading_markup", 1
        )[0]
        self.assertIn('id="cadivor-main-transition-css-{gen}"', inject)
        self.assertNotIn("style.disabled = true", inject)
        self.assertNotIn("unsafe_allow_javascript=True", inject)
        self.assertNotIn("host.remove()", inject)
        self.assertNotIn("style.remove()", inject)

    def test_alternative_finder_is_visible_before_synchronous_supplier_lookup(self):
        approved_pages = (ROOT / "src" / "ui" / "approved_pages.py").read_text(
            encoding="utf-8"
        )
        finder = approved_pages.split("def render_replacement_search()", 1)[1].split(
            "\ndef ", 1
        )[0]
        reveal_at = finder.index('reveal_authenticated_page_body("Alternative Finder")')
        supplier_lookup_at = finder.index(
            "run_alternative_finder_search(st.session_state, query)"
        )
        self.assertLess(reveal_at, supplier_lookup_at)

    def test_compare_form_releases_navigation_cover_before_supplier_and_datasheet_search(self):
        approved_pages = (ROOT / "src" / "ui" / "approved_pages.py").read_text(
            encoding="utf-8"
        )
        compare = approved_pages.split("def render_compare_live", 1)[1].split(
            "def render_datasheet_live", 1
        )[0]
        reveal_at = compare.index(
            'reveal_authenticated_page_body("Compare Parts", force=True)'
        )
        search_at = compare.index("run_compare_parts_many(requested_parts)")
        self.assertLess(reveal_at, search_at)

    def test_report_and_procurement_routes_release_after_the_full_page_renders(self):
        analysis_detail = (ROOT / "src" / "pages" / "analysis_detail.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(
            'reveal_authenticated_page_body("Analysis Details")',
            analysis_detail,
        )
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(
            encoding="utf-8"
        )
        procurement = runtime.split(
            'if app_mode == "Procurement Advisor":', 1
        )[1].split('if app_mode == "Cost Optimization":', 1)[0]
        self.assertNotIn('reveal_authenticated_page_body("Procurement Advisor")', procurement)
        self.assertIn("force=True", runtime.split("def stop_authenticated_page", 1)[1].split(
            "from src.ui.executive_workspace", 1
        )[0])
        self.assertIn("font-size:13px!important", procurement)
        self.assertIn("font-size:28px!important", procurement)
        self.assertIn("font-size:18px!important", procurement)

    def test_dashboard_cover_is_released_after_heading_before_workspace_reads(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        start = runtime.index("# ---------- Dashboard ----------")
        end = runtime.index('if app_mode == "Analysis Details":', start)
        dashboard = runtime[start:end]
        heading_at = dashboard.index(
            'render_dashboard_page_heading(\n            "Preparing your workspace"'
        )
        reveal_at = dashboard.index('reveal_authenticated_page_body("Dashboard")')
        data_read_at = dashboard.index("_workspace_commands_cache_fresh(")
        clear_at = dashboard.index("_dashboard_loading_placeholder.empty()")
        home_at = dashboard.index("render_home(")
        self.assertLess(heading_at, reveal_at)
        self.assertLess(reveal_at, data_read_at)
        self.assertLess(clear_at, home_at)
        self.assertIn("render_home(", dashboard)
        self.assertIn("stop_authenticated_page()", dashboard)

    def test_monitoring_cover_is_released_for_both_access_paths(self):
        runtime = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
        start = runtime.index('if app_mode == "Monitoring":')
        end = runtime.index('if app_mode == "Supply Risk Scenario":', start)
        monitoring = runtime[start:end]
        release = 'reveal_authenticated_page_body("Monitoring")'
        self.assertEqual(monitoring.count(release), 2)

        restricted = monitoring.split("if not monitoring_allowed:", 1)[1].split(
            "return_analysis_id", 1
        )[0]
        self.assertLess(restricted.index(release), restricted.index("stop_authenticated_page()"))

        header_start = monitoring.index("cadivor_section_header(")
        content_release = monitoring.index(release, header_start)
        self.assertLess(header_start, content_release)
        self.assertLess(content_release, monitoring.index("def _monitor_query"))
        self.assertLess(content_release, monitoring.index("active_queue =", header_start))
        self.assertIn("run_with_read_budget(", monitoring)
        self.assertIn('budget_seconds=6.0', monitoring)
        self.assertIn('key="monitoring_data_retry"', monitoring)
        self.assertIn("monitoring_cache_key = monitoring_route_cache_key(", monitoring)
        self.assertIn("monitoring_loaded_at_key", monitoring)

    def test_every_real_route_change_keeps_opening_owner_even_with_warm_cache(self):
        tree = ast.parse(SOURCE)
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "should_paint_opening_overlay"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations")],
                    level=0,
                ),
                helper,
            ],
            type_ignores=[],
        )
        namespace = {
            "Any": Any,
            "MutableMapping": MutableMapping,
            "st": SimpleNamespace(session_state={}),
            "MAIN_TRANSITION_ROUTE_KEY": "cadivor_main_transition_route",
            "MAIN_TRANSITION_ACTIVE_KEY": "cadivor_main_transition_active",
            "PRESENTED_ROUTE_KEY": "cadivor_presented_route",
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
        }
        exec(compile(ast.fix_missing_locations(module), "<transition>", "exec"), namespace)
        should_paint = namespace["should_paint_opening_overlay"]
        state = {
            "cadivor_foundation_shell_mounted": True,
            "cadivor_main_transition_active": True,
            "cadivor_presented_route": "Reports",
        }

        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="Dashboard",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="Analysis Details",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="Engineering Decisions",
                session_state=state,
            )
        )
        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="BOM Settings",
                session_state=state,
            )
        )

        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="Dashboard",
                session_state={"cadivor_foundation_shell_mounted": True},
            )
        )

        analysis_state = {
            "cadivor_foundation_shell_mounted": True,
            "cadivor_bom_analysis_transition": "start",
        }
        self.assertTrue(
            should_paint(
                needs_transition=True,
                target_route="BOM Analyzer",
                session_state=analysis_state,
            )
        )
        self.assertFalse(
            should_paint(
                needs_transition=False,
                target_route="Dashboard",
                session_state=state,
            )
        )

    def test_analysis_start_and_rerun_have_specific_loading_copy(self):
        tree = ast.parse(SOURCE)
        helper = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "route_loading_markup"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom(
                    module="__future__",
                    names=[ast.alias(name="annotations")],
                    level=0,
                ),
                helper,
            ],
            type_ignores=[],
        )
        namespace = {
            "html": html,
            "BOM_ANALYSIS_TRANSITION_KEY": "cadivor_bom_analysis_transition",
            "MAIN_TRANSITION_KIND_KEY": "cadivor_main_transition_kind",
            "MAIN_TRANSITION_PREVIOUS_ROUTE_KEY": "cadivor_main_transition_previous_route",
            "st": SimpleNamespace(session_state={}),
        }
        exec(compile(ast.fix_missing_locations(module), "<transition-copy>", "exec"), namespace)
        render = namespace["route_loading_markup"]

        namespace["st"].session_state["cadivor_main_transition_kind"] = "blocking"
        namespace["st"].session_state["cadivor_bom_analysis_transition"] = "start"
        start = render("BOM Analyzer", 1)
        self.assertNotIn("Starting BOM analysis…", start)
        self.assertNotIn("position:fixed", start)
        self.assertEqual(start, "")

        namespace["st"].session_state["cadivor_bom_analysis_transition"] = "rerun"
        rerun = render("BOM Analyzer", 2)
        self.assertNotIn("Rerunning BOM analysis…", rerun)
        self.assertNotIn("position:fixed", rerun)
        self.assertEqual(rerun, "")

        namespace["st"].session_state["cadivor_bom_analysis_transition"] = ""
        other = render("Dashboard", 3)
        self.assertIn("Opening Dashboard…", other)
        self.assertIn("position:fixed;left:var(--cv-foundation-rail,0px)", other)
        self.assertIn("display:flex;align-items:center;justify-content:center", other)
        self.assertIn("width:min(420px,calc(100% - 48px))", other)


if __name__ == "__main__":
    unittest.main()
