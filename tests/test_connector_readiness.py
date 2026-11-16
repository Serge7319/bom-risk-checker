from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from apps.api import connectors


class ConnectorReadinessTests(unittest.TestCase):
    def test_supplier_credentials_are_reported_as_unverified_not_live_ready(self):
        clean_environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("MOUSER_", "DIGIKEY_", "NEWARK_", "NEXAR_", "OCTOPART_"))
        }
        with patch.dict(os.environ, clean_environment, clear=True):
            os.environ["DIGIKEY_CLIENT_ID"] = "test-id-value"
            os.environ["DIGIKEY_CLIENT_SECRET"] = "test-secret-value"
            payload = connectors.connector_status_payload()

        rows = {row["id"]: row for row in payload["connectors"]}
        self.assertEqual(rows["supplier.digikey"]["status"], "configured_unverified")
        self.assertEqual(rows["supplier.mouser"]["status"], "blocked")
        self.assertEqual(payload["live_ready_count"], 0)
        self.assertEqual(payload["status"] if "status" in payload else payload["live_status"], "partial")
        self.assertEqual(payload["configured_unverified_count"], 1)
        self.assertNotIn("test-secret-value", str(payload))
        self.assertIn("API acceptance has not been verified", rows["supplier.digikey"]["notes"])
        blocked_sync = connectors.sync_generic_bom_csv(
            [{"MPN": "ABC123"}], connector_id="supplier.digikey"
        )
        self.assertFalse(blocked_sync.ok)
        self.assertEqual(blocked_sync.mode, "blocked")

    def test_design_tool_file_workflow_does_not_claim_a_live_connection(self):
        payload = connectors.connector_status_payload()
        rows = {row["id"]: row for row in payload["connectors"]}
        cad = rows["cad.altium_or_solidworks"]
        self.assertEqual(cad["status"], "file_workflow")
        self.assertEqual(payload["live_ready_count"], 0)
        self.assertIn("Direct PLM, ERP, and CAD integrations", payload["gap"])


if __name__ == "__main__":
    unittest.main()
