"""Route-state marker used to recover a missed browser Back/Forward rerun."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from src.browser_navigation import serialize_browser_route_state


ROOT = Path(__file__).resolve().parents[1]


class BrowserRouteStateTests(unittest.TestCase):
    def test_route_state_serialization_matches_normalized_browser_query(self):
        serialized = serialize_browser_route_state(
            {
                "return_analysis_id": "synthetic-analysis-1",
                "auth": "discard-me",
                "analysis_tab": "Engineering Decisions",
                "page": "Compare Parts",
                "source": "discard-me-too",
                "empty": " ",
            },
            route="Analysis Details",
        )

        self.assertEqual(
            json.loads(serialized),
            [
                ["analysis_tab", "Engineering Decisions"],
                ["page", "Analysis Details"],
                ["return_analysis_id", "synthetic-analysis-1"],
            ],
        )

    def test_page_marker_and_popstate_watchdog_share_route_state(self):
        auth_gate = (ROOT / "src" / "auth_gate.py").read_text(encoding="utf-8")
        bridge = (
            ROOT / "src" / "components" / "browser_navigation" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn('data-cadivor-route-state="{route_state}"', auth_gate)
        self.assertIn('if (reason === "popstate") scheduleRouteRecovery(href);', bridge)
        self.assertIn('marker.getAttribute("data-cadivor-route-state")', bridge)
        self.assertIn("w.location.reload()", bridge)
