"""Regression contract for slow-route transition ownership."""
from __future__ import annotations

import ast
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

    def test_warm_analysis_details_keeps_opening_owner(self):
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
            "SLOW_ROUTE_OPENING_TARGETS": frozenset({"Analysis Details"}),
            "FAST_CACHED_NAV_OPENING_MS": 300,
            "warm_session_nav_ready": lambda _state: True,
        }
        exec(compile(ast.fix_missing_locations(module), "<transition>", "exec"), namespace)
        should_paint = namespace["should_paint_opening_overlay"]
        state = {"cadivor_foundation_shell_mounted": True}

        self.assertFalse(
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


if __name__ == "__main__":
    unittest.main()
