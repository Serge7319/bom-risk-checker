"""Behavioral contracts for consistent component/BOM decision targets."""
from __future__ import annotations

import unittest

import pandas as pd

from src.decision_engine import (
    _analysis_decisions,
    build_decision_center,
    decision_target_cell,
    decision_target_context,
    decision_target_label,
    decision_target_type,
)


class DecisionTargetConsistencyTests(unittest.TestCase):
    @staticmethod
    def _legacy_alert(analysis_id=None):
        return pd.DataFrame([{
            "analysis_id": analysis_id,
            "part_number": "LM358N",
            "alert_type": "Lifecycle change",
            "alert_message": "Lifecycle changed from obsolete to active",
            "severity": "High",
            "created_at": "2026-09-01T00:00:00Z",
        }])

    @staticmethod
    def _saved_boms():
        return [
            {"id": "a1", "project_name": "Control Board", "bom_name": "Rev A"},
            {"id": "a2", "project_name": "Power Board", "bom_name": "Rev B"},
        ]

    def test_analysis_decisions_are_explicit_bom_targets(self):
        decisions = _analysis_decisions(
            {
                "id": "analysis-1",
                "project_name": "Project Alpha — Motor Controller BOM",
                "filename": "motor-controller.csv",
                "health_score": 54,
                "high_risk_count": 3,
                "medium_risk_count": 1,
                "created_at": "2026-09-01T00:00:00Z",
            }
        )

        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        self.assertEqual(decision_target_type(decision), "bom")
        self.assertEqual(
            decision_target_label(decision),
            "Project Alpha — Motor Controller BOM",
        )
        self.assertEqual(
            decision_target_context(decision),
            "BOM review · 3 high-risk components",
        )
        self.assertEqual(
            decision_target_cell(decision),
            "Project Alpha — Motor Controller BOM\nBOM review · 3 high-risk components",
        )

    def test_alert_decisions_keep_mpn_and_gain_bom_context(self):
        alert_df = pd.DataFrame(
            [
                {
                    "analysis_id": "analysis-1",
                    "part_number": "LM358N",
                    "alert_type": "Lifecycle change",
                    "alert_message": "Lifecycle changed from obsolete to active",
                    "severity": "High",
                    "created_at": "2026-09-01T00:00:00Z",
                }
            ]
        )
        center = build_decision_center(
            alert_df=alert_df,
            analyses=[
                {
                    "id": "analysis-1",
                    "project_name": "Project Alpha — Motor Controller BOM",
                    "filename": "motor-controller.csv",
                }
            ],
        )

        decision = center["decisions"][0]
        self.assertEqual(decision_target_type(decision), "component")
        self.assertEqual(decision_target_label(decision), "LM358N")
        self.assertEqual(
            decision_target_context(decision),
            "Component · Project Alpha — Motor Controller BOM",
        )
        self.assertEqual(decision.get("mpn"), "LM358N")

    def test_legacy_records_are_classified_without_breaking_display(self):
        bom = {
            "source": "BOM Analysis",
            "part_number": "Legacy BOM title",
            "title": "Review the BOM",
        }
        component = {
            "source": "Monitoring",
            "part_number": "MCP2551-I/SN",
            "title": "Review the component",
        }

        self.assertEqual(decision_target_type(bom), "bom")
        self.assertEqual(decision_target_label(bom), "Legacy BOM title")
        self.assertEqual(decision_target_type(component), "component")
        self.assertEqual(decision_target_label(component), "MCP2551-I/SN")

    def test_component_context_can_show_project_and_bom_without_losing_mpn(self):
        decision = {
            "source": "Monitoring",
            "part_number": "TPS5430DDAR",
            "mpn": "TPS5430DDAR",
            "project_name": "Power Board",
            "bom_name": "Rev B BOM",
        }

        self.assertEqual(decision_target_label(decision), "TPS5430DDAR")
        self.assertEqual(
            decision_target_context(decision),
            "Component · Power Board · Rev B BOM",
        )

    def test_unlinked_alert_in_one_saved_bom_shows_inferred_context(self):
        center = build_decision_center(
            alert_df=self._legacy_alert(),
            analyses=self._saved_boms(),
            part_links=[{"analysis_id": "a1", "mpn": "lm358n"}],
        )
        component = next(d for d in center["decisions"] if d["source"] == "Monitoring")
        self.assertEqual(component["analysis_id"], "")
        self.assertEqual(component["context_analysis_id"], "a1")
        self.assertEqual(
            decision_target_cell(component),
            "LM358N\nComponent · Appears in Control Board · Rev A",
        )

    def test_shared_part_lists_boms_without_claiming_one_as_alert_source(self):
        center = build_decision_center(
            alert_df=self._legacy_alert(),
            analyses=self._saved_boms(),
            part_links=[
                {"analysis_id": "a2", "mpn": "LM358N"},
                {"analysis_id": "a1", "mpn": "LM358N"},
                {"analysis_id": "a1", "mpn": "LM358N"},
            ],
        )
        component = next(d for d in center["decisions"] if d["source"] == "Monitoring")
        self.assertEqual(component["analysis_id"], "")
        self.assertNotIn("context_analysis_id", component)
        self.assertEqual(decision_target_context(component), "Component · In 2 saved BOMs")
        self.assertEqual(
            [bom["name"] for bom in component["related_boms"]],
            ["Control Board · Rev A", "Power Board · Rev B"],
        )

    def test_direct_link_wins_over_shared_part_matches(self):
        center = build_decision_center(
            alert_df=self._legacy_alert("a1"),
            analyses=self._saved_boms(),
            part_links=[{"analysis_id": "a2", "mpn": "LM358N"}],
        )
        component = next(d for d in center["decisions"] if d["source"] == "Monitoring")
        self.assertEqual(component["analysis_id"], "a1")
        self.assertNotIn("related_boms", component)
        self.assertEqual(decision_target_context(component), "Component · Control Board · Rev A")

    def test_missing_part_match_does_not_guess_saved_bom(self):
        center = build_decision_center(
            alert_df=self._legacy_alert(float("nan")),
            analyses=self._saved_boms(),
            part_links=[
                {"analysis_id": "a1", "mpn": "ANOTHER-PART"},
                {"analysis_id": "another-workspace", "mpn": "LM358N"},
            ],
        )
        component = next(d for d in center["decisions"] if d["source"] == "Monitoring")
        self.assertEqual(component["analysis_id"], "")
        self.assertEqual(decision_target_context(component), "Component · No saved BOM linked")


if __name__ == "__main__":
    unittest.main()
