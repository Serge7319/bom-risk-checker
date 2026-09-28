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
    partition_decision_queue,
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
        self.assertEqual(decision["queue_title"], "Resolve 3 high-risk components")
        self.assertEqual(
            decision["title"],
            "Resolve high-risk components in Project Alpha — Motor Controller BOM",
        )

    def test_medium_risk_bom_review_has_a_short_action_without_losing_its_title(self):
        decision = _analysis_decisions({
            "id": "analysis-2", "project_name": "Power Board Rev B",
            "medium_risk_count": 1,
        })[0]
        self.assertEqual(decision["queue_title"], "Review 1 medium-risk component")
        self.assertEqual(decision["title"], "Complete focused review for Power Board Rev B")

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
        self.assertEqual(decision_target_cell(decision), "LM358N")
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

    def test_project_title_already_includes_bom_name_without_repeating_it(self):
        project = "Radar Control Unit — Cadivor 10-Part Sample BOM"
        bom = "Cadivor 10-Part Sample BOM"
        self.assertEqual(
            decision_target_label({
                "target_type": "bom", "project_name": project, "bom_name": bom,
            }),
            project,
        )
        self.assertEqual(
            decision_target_context({
                "target_type": "component", "mpn": "LM358N",
                "project_name": project, "bom_name": bom,
            }),
            f"Component · {project}",
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
            "LM358N",
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
        self.assertEqual(decision_target_cell(component), "LM358N")

    def test_component_and_saved_bom_reviews_keep_separate_targets_and_all_ids(self):
        center = build_decision_center(
            alert_df=self._legacy_alert(),
            analyses=[
                {"id": "a1", "project_name": "Control Board", "bom_name": "Rev A",
                 "high_risk_count": 2, "health_score": 52},
            ],
            part_links=[{"analysis_id": "a1", "mpn": "LM358N"}],
        )
        components, saved_boms = partition_decision_queue(iter(center["decisions"]))
        self.assertEqual(len(components), 1)
        self.assertEqual(len(saved_boms), 1)
        self.assertEqual(
            {item["decision_id"] for item in components + saved_boms},
            {item["decision_id"] for item in center["decisions"]},
        )
        self.assertEqual(decision_target_cell(components[0]), "LM358N")
        self.assertTrue(decision_target_cell(saved_boms[0]).startswith("Control Board · Rev A\n"))


if __name__ == "__main__":
    unittest.main()
