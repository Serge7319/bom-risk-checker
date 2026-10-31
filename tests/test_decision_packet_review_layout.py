"""Contracts for the evidence-first monitoring decision packet."""
from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from src.decision_dashboard import packet_header_html
from src.decision_engine import build_decision_center, monitoring_decision_id


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = (ROOT / "src" / "authenticated_runtime.py").read_text(encoding="utf-8")
NAV_RECOVERY = (
    ROOT / "src" / "assets" / "css" / "navigation_recovery.css"
).read_text(encoding="utf-8")
NAVIGATION = (ROOT / "src" / "ui" / "navigation.py").read_text(encoding="utf-8")
CORE_PREMIUM = (ROOT / "src" / "ui" / "core_premium_ui.py").read_text(encoding="utf-8")


class DecisionPacketHeaderTests(unittest.TestCase):
    def test_header_matches_the_approved_three_step_review_flow(self):
        alert = {
            "alert_type": "Lifecycle Change",
            "alert_message": "Lifecycle changed from Obsolete to Active",
            "previous_value": "Obsolete",
            "current_value": "Active",
        }
        decision = {
            "mpn": "MPU6050",
            "priority": "High",
            "priority_score": 82,
            "status": "New",
            "source": "Monitoring",
        }

        rendered = packet_header_html(
            decision,
            alert=alert,
            saved_bom_label="Not linked",
            saved_bom_linked=False,
        )

        for expected in (
            "Review lifecycle alert",
            "MPU6050",
            "Lifecycle changed",
            "Obsolete",
            "Active",
            "Not linked",
            "HIGH RISK",
            "Review evidence",
            "Choose mitigation",
            "Record outcome",
        ):
            self.assertIn(expected, rendered)
        for removed in ("Review target", "Confidence", "Estimated Effort", "Priority matrix"):
            self.assertNotIn(removed, rendered)

    def test_header_escapes_part_and_supplier_supplied_text(self):
        rendered = packet_header_html(
            {"mpn": "<script>alert(1)</script>", "priority": "High"},
            alert={"alert_type": "Lifecycle", "previous_value": "<bad>"},
        )
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&lt;bad&gt;", rendered)


class DecisionPacketWorkflowTests(unittest.TestCase):
    def test_monitoring_approvals_use_project_and_exact_bom_contexts(self):
        lookup = RUNTIME.split(
            'selected_decision_context_id = ""', 1
        )[1].split("decision_load_error =", 1)[0]

        self.assertIn("project_decision_context_key", lookup)
        self.assertIn("approved_records_for_part", lookup)
        self.assertIn("project_name=decision_project_name", lookup)
        self.assertIn("decision_mpn_key = _normalize_decision_mpn(decision_mpn)", lookup)
        self.assertIn('options=["", *bom_by_id]', lookup)
        self.assertIn("_ed_scoped_approved_alts_v2_", lookup)
        self.assertNotIn("next(iter(bom_by_id)", lookup)
        self.assertLess(
            RUNTIME.index(
                "from src.normalizer import normalize_part_number as _normalize_decision_mpn"
            ),
            RUNTIME.index("decision_mpn_key = _normalize_decision_mpn(decision_mpn)"),
        )

    def test_decision_packet_styles_are_loaded_before_route_body_paints(self):
        css_loader = CORE_PREMIUM.split("def inject_core_premium_ui()", 1)[1].split(
            "def inject_core_premium_ui_auth", 1
        )[0]
        route_body_at = RUNTIME.find("claim_authenticated_route_body(app_mode)")
        shell_css_at = RUNTIME.find("inject_core_premium_ui()")

        self.assertIn('st.session_state.get("cadivor_route")', css_loader)
        self.assertIn('route == "Engineering Decisions"', css_loader)
        self.assertIn("inject_navigation_recovery_css(prepaint=True)", css_loader)
        self.assertGreater(route_body_at, shell_css_at)

    def test_saved_packet_actions_update_local_state_without_three_read_reload(self):
        packet = RUNTIME.split(
            "if selected_decision and monitoring_component_decision:", 1
        )[1].split("if selected_decision:", 1)[0]
        inventory_save = packet.split("if save_inventory:", 1)[1].split(
            "with packet_right:", 1
        )[0]
        mitigation_save = packet.split(
            '"Record mitigation and close alert"', 1
        )[1].split('st.caption(\n                                "The alert stays open', 1)[0]
        note_save = packet.split('"Save note"', 1)[1].split(
            'note_flash = st.session_state.pop("cadivor_ed_note_flash"', 1
        )[0]

        for action in (inventory_save, mitigation_save, note_save):
            self.assertNotIn("load_decision_state(", action)
            self.assertIn("fallback_state[decision_id]", action)
        self.assertIn('"history": inventory_history', inventory_save)
        self.assertIn('"history": resolution_history', mitigation_save)
        self.assertIn('"notes": note_rows', note_save)

    def test_packet_releases_route_cover_after_review_content_is_mounted(self):
        packet = RUNTIME.split(
            "if selected_decision and monitoring_component_decision:", 1
        )[1].split("if selected_decision:", 1)[0]
        panel_at = packet.find('key="cadivor_decision_packet_shell"')
        reveal_at = packet.rfind(
            'reveal_authenticated_page_body("Engineering Decisions", force=True)'
        )
        stop_at = packet.rfind("stop_authenticated_page()")

        self.assertGreater(panel_at, 0)
        self.assertGreater(reveal_at, panel_at)
        self.assertGreater(stop_at, reveal_at)

    def test_inventory_verification_survives_decision_center_rebuild(self):
        alert = {
            "part_number": "MPU6050",
            "alert_type": "Lifecycle Change",
            "alert_message": "Lifecycle changed from NRND to EOL",
            "previous_value": "NRND",
            "current_value": "EOL",
            "created_at": "2026-10-17T10:00:00Z",
            "severity": "High",
        }
        inventory = {
            "supplier": "Authorized distributor",
            "quantity": 240,
            "source_reference": "Quote Q-42",
            "verified_by": "Engineer",
            "verified_at": "2026-10-17T14:00:00Z",
        }
        saved_state = {
            monitoring_decision_id(alert): {
                "status": "Engineering Review",
                "owner": "Component Engineering",
                "decision_payload": {"inventory_evidence": inventory},
            }
        }

        center = build_decision_center(
            alert_df=pd.DataFrame([alert]),
            analyses=[],
            saved_state=saved_state,
            part_links=[],
        )

        self.assertEqual(
            center["decisions"][0]["inventory_evidence"],
            inventory,
        )

    def test_packet_uses_home_width_and_keeps_actions_in_the_packet(self):
        packet = RUNTIME.split(
            "if selected_decision and monitoring_component_decision:", 1
        )[1].split("if selected_decision:", 1)[0]
        self.assertIn('key="cadivor_decision_packet_shell"', packet)
        self.assertIn('key=f"decision_packet_evidence_{decision_id}"', packet)
        self.assertIn('key=f"decision_packet_gate_{decision_id}"', packet)
        self.assertIn('"Record verified inventory"', packet)
        self.assertIn('"Record mitigation and close alert"', packet)
        self.assertIn('"Review saved comparison and datasheet evidence"', packet)
        self.assertIn('"Search current supplier evidence"', packet)
        self.assertIn('"Search public datasheets"', packet)
        self.assertIn("public_datasheet_search_url(decision_mpn)", packet)
        self.assertIn("exact_supplier_evidence", packet)
        self.assertIn("get_first_exact_supplier_result", packet)
        self.assertIn("on_click=_refresh_decision_packet_supplier_evidence", packet)
        self.assertIn("manufacturer datasheet is available.", packet)
        self.assertIn("Exact part verified at", packet)
        self.assertIn("Refresh supplier evidence", packet)
        self.assertIn("No saved BOM is currently linked to this alert.", packet)
        self.assertIn('return_page="Engineering Decisions"', packet)
        self.assertIn("return_decision_id=decision_id", packet)
        self.assertNotIn('"Decision Summary", "Evidence", "Engineering Notes"', packet)
        self.assertNotIn('label="Confidence"', packet)
        self.assertNotIn('label="Estimated Effort"', packet)
        refresh = packet.split(
            "def _refresh_decision_packet_supplier_evidence", 1
        )[1].split("if selected_decision_context_id:", 1)[0]
        self.assertNotIn("st.rerun()", refresh)
        self.assertIn("max-width: 1440px !important", NAV_RECOVERY)
        self.assertIn(".st-key-cadivor_decision_packet_shell", NAV_RECOVERY)
        self.assertIn("width: 100% !important", NAV_RECOVERY)
        self.assertIn('class="cv-dp-layout-spacer"', packet)
        steps_css = NAV_RECOVERY.split(".st-key-cadivor_decision_packet_shell .cv-dp-steps {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100% !important", steps_css)
        self.assertIn("max-width: 100% !important", steps_css)
        self.assertIn(".cv-dp-layout-spacer", NAV_RECOVERY)
        self.assertIn("height: 20px !important", NAV_RECOVERY)
        self.assertIn("margin: 0 0 14px !important", steps_css)
        step_connector_css = NAV_RECOVERY.split(
            ".st-key-cadivor_decision_packet_shell .cv-dp-steps li::after {", 1
        )[1].split("}", 1)[0]
        self.assertIn("display: none !important", step_connector_css)
        self.assertIn("content: none !important", step_connector_css)
        self.assertIn(".cv-dp-steps li::before", NAV_RECOVERY)
        self.assertNotIn("right: -14px", NAV_RECOVERY)
        self.assertIn('"Datasheet URL": (', RUNTIME)
        self.assertIn('part_data.get("datasheet_url")', RUNTIME)
        self.assertIn('"datasheet_url": cost_fields["datasheet_url"]', RUNTIME)
        self.assertIn("save_decision_source_evidence", RUNTIME)
        migration = ROOT / "supabase" / "migrations" / "20261017_analysis_part_datasheet_url.sql"
        self.assertTrue(migration.exists())
        self.assertIn("add column if not exists datasheet_url text", migration.read_text(encoding="utf-8"))
        self.assertIn("alter table if exists public.monitor_alerts", migration.read_text(encoding="utf-8"))
        self.assertIn("alter table if exists public.part_monitor_history", migration.read_text(encoding="utf-8"))

    def test_alternative_finder_returns_to_the_exact_open_decision(self):
        self.assertIn("ALT_FINDER_RETURN_DECISION_ID_KEY", NAVIGATION)
        self.assertIn('"return_decision_id"', NAVIGATION)
        self.assertIn('return_page == "Engineering Decisions"', RUNTIME)
        self.assertIn('key="alternative_back_to_decision_packet"', RUNTIME)


if __name__ == "__main__":
    unittest.main()
