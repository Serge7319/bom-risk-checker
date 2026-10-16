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
        self.assertIn(
            '> [data-testid="stElementContainer"][data-stale="true"]:not(',
            SOURCE,
        )

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
            "st": SimpleNamespace(session_state={}),
        }
        exec(compile(ast.fix_missing_locations(module), "<transition-copy>", "exec"), namespace)
        render = namespace["route_loading_markup"]

        namespace["st"].session_state["cadivor_bom_analysis_transition"] = "start"
        start = render("BOM Analyzer", 1)
        self.assertIn("Starting BOM analysis…", start)

        namespace["st"].session_state["cadivor_bom_analysis_transition"] = "rerun"
        rerun = render("BOM Analyzer", 2)
        self.assertIn("Rerunning BOM analysis…", rerun)
        self.assertIn("Refreshing supplier, lifecycle, lead-time, and pricing evidence", rerun)


if __name__ == "__main__":
    unittest.main()
