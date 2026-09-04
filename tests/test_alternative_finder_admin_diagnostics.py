"""Admin-only diagnostics and BJT architecture-suppression regressions."""

from pathlib import Path
import unittest

from src.alternative_classification import build_recommendation_score_drivers
from src.alternative_engine import get_drop_in_reasons
from src.alternative_reasoning import build_alternative_reasoning
from src.component_family_profiles import FAMILY_PROFILES, get_family_profile
from src.datasheet_comparison import (
    INTERNAL_COMPARISON_METADATA_COLUMNS,
    build_datasheet_comparison,
    build_pdf_field_evidence,
    user_facing_comparison_rows,
    user_facing_pdf_evidence_rows,
    user_may_view_comparison_diagnostics,
)


RUNTIME_SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
).read_text(encoding="utf-8")

_NON_ADMIN_ROLES = (
    "user",
    "engineer",
    "viewer",
    "member",
    "manager",
    "owner",
    "operator",
    "analyst",
    "",
    None,
)


def _sparse_bjt_pair():
    original = {
        "description": "Transistor NPN 40V SOT-23 MMBT3904",
        "device_type": "NPN",
        "package": "SOT-23",
        "mounting_style": "Surface Mount",
        "collector_emitter_voltage": "40V",
        "collector_base_voltage": "",
        "collector_current": "0.2A",
        "dc_current_gain": "",
        "power_dissipation": "",
        "transition_frequency": "",
        "vce_saturation": "",
        "collector_cutoff_current": "",
        "pin_count": "3",
        "pinout": "",
    }
    candidate = dict(original)
    candidate["dc_current_gain"] = ""
    candidate["pinout"] = ""
    return original, candidate


class DeveloperDiagnosticsAdminOnlyTests(unittest.TestCase):
    def test_admin_may_view_diagnostics(self):
        self.assertTrue(user_may_view_comparison_diagnostics(role="admin"))
        self.assertTrue(user_may_view_comparison_diagnostics(role="Admin"))
        self.assertTrue(user_may_view_comparison_diagnostics(role="user", is_admin=True))

    def test_non_admin_roles_cannot_view_diagnostics(self):
        for role in _NON_ADMIN_ROLES:
            with self.subTest(role=role):
                self.assertFalse(
                    user_may_view_comparison_diagnostics(role=role, is_admin=False)
                )

    def test_runtime_gates_diagnostics_with_server_side_helper(self):
        self.assertIn("user_may_view_comparison_diagnostics(", RUNTIME_SOURCE)
        self.assertIn("show_developer_diagnostics = user_may_view_comparison_diagnostics(", RUNTIME_SOURCE)
        self.assertIn("if show_developer_diagnostics:", RUNTIME_SOURCE)
        # Must not render the expander for non-admins via CSS alone.
        diagnostics_block = RUNTIME_SOURCE.split("Developer comparison diagnostics", 1)[0][-500:]
        self.assertIn("show_developer_diagnostics", diagnostics_block)
        self.assertNotIn("display:none", diagnostics_block.casefold())


class BjtArchitectureSuppressionTests(unittest.TestCase):
    def test_bjt_profile_does_not_treat_architecture_as_meaningful(self):
        profile = get_family_profile("Bipolar transistor")
        self.assertFalse(profile.architecture_meaningful)
        for family in (
            "MOSFET",
            "Diode / protection",
            "Capacitor",
            "Resistor",
            "Connector / electromechanical",
            "Relay",
            "Sensor",
            "Oscillator / crystal",
            "Transformer",
        ):
            with self.subTest(family=family):
                self.assertFalse(get_family_profile(family).architecture_meaningful)

    def test_bjt_drop_in_reasons_omit_architecture(self):
        original, candidate = _sparse_bjt_pair()
        comparison = build_datasheet_comparison(original, candidate)
        reasons = get_drop_in_reasons(
            original,
            {
                "Comparison Family": comparison["family"],
                "Comparison Rows": comparison["rows"],
                "Package": "SOT-23",
            },
        )
        self.assertNotIn("architecture", reasons.casefold())
        self.assertTrue(
            any(token in reasons for token in ("Pinout", "hFE", "VCBO", "Leakage", "VCE(sat)", "Power"))
            or "needs verification" in reasons.casefold()
        )

    def test_bjt_score_drivers_and_decision_omit_architecture(self):
        original, candidate = _sparse_bjt_pair()
        comparison = build_datasheet_comparison(original, candidate)
        drivers = build_recommendation_score_drivers(
            comparison_rows=comparison["rows"],
            warnings=["⚠ Original architecture could not be verified"],
            tradeoffs=[],
            engineering_confidence=40,
            recommendation_score=50,
            comparison_family=comparison["family"],
        )
        joined_drivers = " ".join(drivers).casefold()
        self.assertNotIn("architecture", joined_drivers)
        self.assertTrue(
            any(
                token in joined_drivers
                for token in ("pinout", "hfe", "vcbo", "leakage", "vce(sat)", "power", "vceo")
            )
        )

        reasoning = build_alternative_reasoning(
            original_part="MMBT3904",
            original_data=original,
            candidate={
                "Alternative Part": "MMBT3904-7-F",
                "Comparison Family": comparison["family"],
                "Comparison Rows": comparison["rows"],
                "Comparison Counts": comparison["counts"],
                "Lifecycle": "Active",
                "Estimated Risk": "Medium",
                "Stock": 1000,
                "Unit Price": 0.05,
                "Classification": "Verified direct substitute",
            },
            recommendation_score=50,
            compatibility_confidence=40,
            engineering_matches=[],
            warnings=["⚠ Original architecture could not be verified"],
            stock_delta="N/A",
            price_delta="N/A",
            comparison_family=comparison["family"],
            classification="Verified direct substitute",
            comparison_rows=comparison["rows"],
            comparison_counts=comparison["counts"],
        )
        decision_text = " ".join(
            [
                reasoning.get("disposition", ""),
                reasoning.get("approval_guidance", ""),
                *reasoning.get("confirmed_matches", []),
                *reasoning.get("verification_required", []),
                *reasoning.get("blockers", []),
                *reasoning.get("expected_work", []),
            ]
        ).casefold()
        self.assertNotIn("architecture", decision_text)

    def test_bjt_user_tables_and_pdfs_omit_architecture_and_schema_metadata(self):
        original, candidate = _sparse_bjt_pair()
        comparison = build_datasheet_comparison(original, candidate)
        user_rows = user_facing_comparison_rows(comparison["rows"])
        table_text = " ".join(
            " ".join(str(value) for value in row.values()) for row in user_rows
        ).casefold()
        self.assertNotIn("architecture", table_text)
        for row in user_rows:
            for meta in INTERNAL_COMPARISON_METADATA_COLUMNS:
                self.assertNotIn(meta, row)

        pdf_rows = build_pdf_field_evidence(
            {"pages": [{"page": 1, "text": "VCEO 40V NPN"}]},
            {"pages": [{"page": 1, "text": "VCEO 40V NPN"}]},
            "Bipolar transistor",
        )
        user_pdf = user_facing_pdf_evidence_rows(pdf_rows)
        pdf_text = " ".join(
            " ".join(str(value) for value in row.values()) for row in user_pdf
        ).casefold()
        self.assertNotIn("architecture", pdf_text)
        for row in user_pdf:
            for meta in ("Key", "Required", "CompareMode", "ValueRole"):
                self.assertNotIn(meta, row)

    def test_mcu_still_allows_architecture_checks(self):
        profile = FAMILY_PROFILES["MCU / processor"]
        self.assertTrue(profile.architecture_meaningful)


if __name__ == "__main__":
    unittest.main()
