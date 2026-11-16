from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

import apps.api.main as api_main
from apps.api import monitoring_scheduler, monitoring_store
from apps.api.main import app
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.team_store import reset_team_store_for_tests
from apps.api.workspace_store import get_store, reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS, SMOKE_EMAIL, SMOKE_PASSWORD


class MonitoringLiveSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ.update({
            "CADIVOR_SANDBOX_AUTH_SECRET": "test-sandbox-auth-secret-key",
            "CADIVOR_ALLOW_EPHEMERAL_FILE_STORE": "1",
            "CADIVOR_ALLOW_SANDBOX_JWT": "1",
        })
        for name in (
            "CADIVOR_MIGRATION_DATABASE_URL", "RAILWAY_ENVIRONMENT",
            "CADIVOR_FORCE_PRODUCTION_AUTH", "CADIVOR_MONITORING_EMAIL_ENABLED",
            "CADIVOR_MONITORING_SCHEDULER_ENABLED", "CADIVOR_MONITORING_CRON_TOKEN",
            "CADIVOR_MONITORING_SCHEDULE_ATTACHED",
            "CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED",
        ):
            os.environ.pop(name, None)
        root = Path(self.temp.name)
        reset_store_for_tests(root / "workspace.json")
        reset_auth_store_for_tests(root / "auth.json", accounts=SANDBOX_SEED_USERS)
        reset_team_store_for_tests(root / "team.json")
        monitoring_store.reset_monitoring_store_for_tests()
        monitoring_store.reset_email_sink_for_tests()
        api_main._THROTTLE.clear()
        self.client = TestClient(app)
        login = self.client.post("/auth/login", json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)
        self.token = login.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        me = self.client.get("/auth/me", headers=self.headers)
        self.assertEqual(me.status_code, 200, me.text)
        self.workspace_id = me.json()["workspace_id"]
        self.user_id = me.json()["user_id"]

    def tearDown(self):
        self.client.close()
        os.environ.clear()
        os.environ.update(self.env)
        self.temp.cleanup()

    def _analysis(self, *, mpn="ABC123", manufacturer="", stock=100, price=1.0):
        report = {
            "id": "analysis-monitor-test",
            "mode": "synthetic-preview",
            "parts": [{
                "MPN": mpn,
                "Manufacturer": manufacturer,
                "Stock": stock,
                "Unit Price": price,
                "Lifecycle": "Active",
            }],
        }
        get_store().upsert_analysis_report(report, workspace_id=self.workspace_id)
        return report["id"]

    def test_email_and_scheduler_flags_accept_true_as_well_as_one(self):
        with patch.dict(os.environ, {
            "CADIVOR_MONITORING_EMAIL_ENABLED": "true",
            "CADIVOR_MONITORING_SCHEDULER_ENABLED": "true",
            "CADIVOR_MONITORING_SCHEDULE_ATTACHED": "true",
            "CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED": "true",
        }):
            self.assertTrue(monitoring_store.email_delivery_enabled())
            self.assertTrue(monitoring_scheduler.scheduler_enabled())
            self.assertTrue(monitoring_scheduler.schedule_attached())
            self.assertTrue(monitoring_scheduler.live_supplier_refresh_enabled())

    def test_email_readiness_lists_flag_and_transport_blockers_together(self):
        with patch.dict(os.environ, {"CADIVOR_MONITORING_EMAIL_ENABLED": "0"}):
            with patch.object(monitoring_store, "_configured_email_transport", return_value=False):
                readiness = monitoring_store.monitoring_email_readiness()
        self.assertEqual(readiness["status"], "not_connected")
        self.assertFalse(readiness["enabled"])
        self.assertIn("CADIVOR_MONITORING_EMAIL_ENABLED", readiness["missing_requirements"][0])
        self.assertIn("RESEND_API_KEY", readiness["missing_requirements"][1])
        self.assertIn("TRANSACTIONAL_FROM_EMAIL", readiness["missing_requirements"][1])

    def test_member_preferences_bind_email_to_verified_auth_context(self):
        result = self.client.put(
            "/tools/monitoring/preferences",
            headers=self.headers,
            json={"email_alerts": True, "supplier_checks": True, "email": "attacker@example.com"},
        )
        self.assertEqual(result.status_code, 200, result.text)
        prefs = result.json()["preferences"]
        self.assertEqual(prefs["email"], SMOKE_EMAIL.lower())
        self.assertTrue(prefs["email_alerts"])
        self.assertTrue(prefs["supplier_checks"])
        rows = monitoring_store.list_user_preferences(self.workspace_id, email_alerts=True)
        self.assertEqual(rows[0]["email"], SMOKE_EMAIL.lower())
        self.assertEqual(rows[0]["user_id"], self.user_id)

    def test_live_refresh_persists_only_exact_identity_and_detects_changes(self):
        analysis_id = self._analysis()
        os.environ["CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED"] = "1"
        fresh = {
            "supplier_data_verified": True,
            "manufacturer_part_number": "ABC123",
            "source": "Mock Distributor",
            "stock_total": 20,
            "unit_price": 2.0,
            "lifecycle_status": "NRND",
            "product_detail_url": "https://supplier.example/ABC123",
        }
        result = monitoring_scheduler.run_live_analysis_refresh(
            self.workspace_id,
            analysis_id,
            supplier_lookup=lambda _mpn: fresh,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated_parts"], 1)
        self.assertEqual(result["alert_count"], 3)
        snapshot = monitoring_store.get_live_snapshot(self.workspace_id, analysis_id, "ABC123")
        self.assertEqual(snapshot["manufacturer_part_number"], "ABC123")
        self.assertEqual(snapshot["stock"], 20)
        self.assertEqual(snapshot["evidence_source"], "live-authorized-supplier")
        self.assertTrue(snapshot["retrieved_at"])

    def test_wrong_identity_or_supplier_failure_never_replaces_snapshot(self):
        analysis_id = self._analysis()
        os.environ["CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED"] = "1"
        result = monitoring_scheduler.run_live_analysis_refresh(
            self.workspace_id,
            analysis_id,
            supplier_lookup=lambda _mpn: {
                "supplier_data_verified": True,
                "manufacturer_part_number": "ABC124",
                "stock_total": 0,
            },
        )
        self.assertEqual(result["updated_parts"], 0)
        self.assertEqual(result["failed_parts"][0]["status"], "exact_supplier_match_unavailable")
        self.assertIsNone(monitoring_store.get_live_snapshot(self.workspace_id, analysis_id, "ABC123"))

    def test_refresh_passes_bom_manufacturer_and_rejects_supplier_maker_mismatch(self):
        analysis_id = self._analysis(manufacturer="Texas Instruments")
        os.environ["CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED"] = "1"
        calls = []
        result = monitoring_scheduler.run_live_analysis_refresh(
            self.workspace_id,
            analysis_id,
            supplier_lookup=lambda mpn, manufacturer="": calls.append((mpn, manufacturer)) or {
                "supplier_data_verified": True,
                "manufacturer_part_number": mpn,
                "manufacturer": "onsemi",
                "stock_total": 25,
                "source": "Synthetic Distributor",
            },
        )
        self.assertEqual(calls, [("ABC123", "Texas Instruments")])
        self.assertEqual(result["updated_parts"], 0)
        self.assertEqual(result["failed_parts"][0]["status"], "manufacturer_identity_mismatch")
        self.assertIsNone(monitoring_store.get_live_snapshot(self.workspace_id, analysis_id, "ABC123"))

    def test_live_dry_run_never_calls_supplier_or_persists(self):
        analysis_id = self._analysis()
        os.environ["CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED"] = "1"
        calls = []
        result = monitoring_scheduler.run_live_analysis_refresh(
            self.workspace_id,
            analysis_id,
            supplier_lookup=lambda mpn: calls.append(mpn) or {},
            dry_run=True,
        )
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["candidate_parts"], 1)
        self.assertEqual(calls, [])
        self.assertIsNone(monitoring_store.get_live_snapshot(self.workspace_id, analysis_id, "ABC123"))
        self.assertEqual(monitoring_store.list_refresh_history(self.workspace_id), [])

    def test_scheduled_run_requires_cron_auth_and_dry_run_has_no_side_effects(self):
        analysis_id = self._analysis()
        self.client.put(
            "/tools/monitoring/preferences",
            headers=self.headers,
            json={"supplier_checks": True},
        )
        os.environ["CADIVOR_MONITORING_CRON_TOKEN"] = "local-cron-secret"
        denied = self.client.post("/tools/monitoring/scheduled-run", json={"dry_run": True})
        self.assertEqual(denied.status_code, 401)
        dry = self.client.post(
            "/tools/monitoring/scheduled-run",
            headers={"x-cadivor-cron-token": "local-cron-secret"},
            json={"dry_run": True},
        )
        self.assertEqual(dry.status_code, 200, dry.text)
        self.assertEqual(dry.json()["status"], "dry_run")
        self.assertEqual(dry.json()["analysis_count"], 1)
        self.assertEqual(dry.json()["supplier_calls"], 0)
        self.assertTrue(dry.json()["persisted"] is False)
        self.assertIsNone(monitoring_store.get_live_snapshot(self.workspace_id, analysis_id, "ABC123"))
        self.assertEqual(monitoring_store.list_refresh_history(self.workspace_id), [])

    def test_email_delivery_uses_verified_member_address(self):
        analysis_id = self._analysis()
        self.client.put(
            "/tools/monitoring/preferences",
            headers=self.headers,
            json={"email_alerts": True, "email": "attacker@example.com"},
        )
        os.environ["CADIVOR_MONITORING_EMAIL_ENABLED"] = "1"
        alert = {
            "id": "alert-1", "analysis_id": analysis_id, "part_number": "ABC123",
            "alert_type": "Stock Drop", "alert_message": "Stock dropped",
        }
        sent = {}
        with patch.object(monitoring_store, "_configured_email_transport", return_value=True), patch(
            "src.email_delivery.send_transactional_email",
            side_effect=lambda **kwargs: sent.update(kwargs),
        ):
            result = monitoring_store.deliver_alert_email(
                self.workspace_id,
                alert,
                user_id=self.user_id,
                recipient_email=SMOKE_EMAIL,
            )
        self.assertTrue(result["delivered"])
        self.assertEqual(sent["to_email"], SMOKE_EMAIL.lower())

    def test_scheduled_alert_email_retries_failure_dedupes_success_and_reopens_after_resolution(self):
        analysis_id = self._analysis()
        monitoring_store.update_user_preferences(
            self.workspace_id,
            self.user_id,
            SMOKE_EMAIL,
            {"supplier_checks": True, "email_alerts": True},
        )
        alert = monitoring_store.persist_alerts(self.workspace_id, [{
            "id": "alert-scheduled-1",
            "analysis_id": analysis_id,
            "part_number": "ABC123",
            "alert_type": "Stock Drop",
            "alert_message": "Stock dropped",
            "evidence_source": "live-authorized-supplier",
            "active": True,
            "status": "active",
        }])[0]
        alert["id"] = "alert-scheduled-1"
        first_response = {
            "ok": True,
            "supplier_calls": 1,
            "updated_parts": 1,
            "alert_count": 1,
            "alerts": [alert],
        }
        later_response = {
            "ok": True,
            "supplier_calls": 1,
            "updated_parts": 1,
            "alert_count": 0,
            "alerts": [],
        }
        deliveries = [
            {"ok": False, "delivered": False},
            {"ok": True, "delivered": True},
            {"ok": True, "delivered": True},
        ]
        os.environ["CADIVOR_MONITORING_SCHEDULER_ENABLED"] = "1"
        os.environ["CADIVOR_MONITORING_LIVE_SUPPLIER_REFRESH_ENABLED"] = "1"
        os.environ["CADIVOR_MONITORING_EMAIL_ENABLED"] = "1"
        with patch.object(monitoring_scheduler, "configured_supplier_count", return_value=1), patch.object(
            monitoring_scheduler, "run_live_analysis_refresh",
            side_effect=[first_response, later_response, later_response, first_response],
        ), patch.object(
            monitoring_store, "deliver_alert_email", side_effect=lambda *args, **kwargs: deliveries.pop(0)
        ) as send:
            failed_attempt = monitoring_scheduler.run_scheduled_cycle()
            first_success = monitoring_scheduler.run_scheduled_cycle()
            duplicate_cycle = monitoring_scheduler.run_scheduled_cycle()
            self.assertEqual(failed_attempt["email_sent"], 0)
            self.assertEqual(first_success["email_sent"], 1)
            self.assertEqual(duplicate_cycle["email_sent"], 0)
            self.assertEqual(send.call_count, 2)

            monitoring_store.reconcile_alerts(
                self.workspace_id,
                analysis_id=analysis_id,
                active_alerts=[],
            )
            after_resolution = monitoring_scheduler.run_scheduled_cycle()

        self.assertEqual(after_resolution["email_sent"], 1)
        self.assertEqual(send.call_count, 3)


if __name__ == "__main__":
    unittest.main()
