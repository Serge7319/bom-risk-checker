from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

import apps.api.main as api_main
from apps.api.main import app
from apps.api.postgres_store import PostgresWorkspaceStore
from apps.api.sandbox_auth import reset_auth_store_for_tests
from apps.api.team_store import reset_team_store_for_tests
from apps.api.workspace_store import get_store, reset_store_for_tests
from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS, SMOKE_EMAIL, SMOKE_PASSWORD


class ProcurementQuoteGroupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ)
        os.environ.update({
            "CADIVOR_SANDBOX_AUTH_SECRET": "test-sandbox-auth-secret-key",
            "CADIVOR_ALLOW_EPHEMERAL_FILE_STORE": "1",
            "CADIVOR_ALLOW_SANDBOX_JWT": "1",
        })
        for name in (
            "CADIVOR_MIGRATION_DATABASE_URL",
            "RAILWAY_ENVIRONMENT",
            "CADIVOR_FORCE_PRODUCTION_AUTH",
        ):
            os.environ.pop(name, None)
        root = Path(self.temp.name)
        reset_store_for_tests(root / "workspace.json")
        reset_auth_store_for_tests(root / "auth.json", accounts=SANDBOX_SEED_USERS)
        reset_team_store_for_tests(root / "team.json")
        api_main._THROTTLE.clear()
        self.client = TestClient(app)
        login = self.client.post(
            "/auth/login",
            json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        self.workspace_id = login.json()["workspace_id"]
        self.analysis_id = "analysis-grouped-quote-test"
        get_store().upsert_analysis_report(
            {
                "id": self.analysis_id,
                "filename": "radar-controller.csv",
                "project_name": "Radar Controller",
                "parts": [
                    {"MPN": "TPS54331D", "Manufacturer": "Texas Instruments"},
                    {"MPN": "LM358DR", "Manufacturer": "Texas Instruments"},
                ],
            },
            workspace_id=self.workspace_id,
        )

    def tearDown(self):
        self.client.close()
        os.environ.clear()
        os.environ.update(self.env)
        self.temp.cleanup()

    def _payload(self):
        return {
            "analysis_id": self.analysis_id,
            "supplier": "Example Components",
            "quote_reference": "Q-4821",
            "currency": "USD",
            "valid_until": "2027-01-31",
            "source_url": "https://supplier.example/quotes/Q-4821",
            "notes": "Freight excluded.",
            "lines": [
                {
                    "requested_mpn": "TPS54331D",
                    "requested_manufacturer": "Texas Instruments",
                    "offered_mpn": "TPS54331D",
                    "offered_manufacturer": "Texas Instruments",
                    "price_breaks": [
                        {"quantity": 1, "unit_price": 1.24},
                        {"quantity": 100, "unit_price": 0.91},
                    ],
                    "minimum_order_quantity": 1,
                    "pack_quantity": 1,
                    "lead_time_weeks": 2,
                    "stock": 800,
                },
                {
                    "requested_mpn": "LM358DR",
                    "requested_manufacturer": "Texas Instruments",
                    "offered_mpn": "LM358DR",
                    "offered_manufacturer": "Texas Instruments",
                    "price_breaks": [
                        {"quantity": 1, "unit_price": 0.38},
                        {"quantity": 100, "unit_price": 0.21},
                    ],
                    "minimum_order_quantity": 10,
                    "pack_quantity": 5,
                    "lead_time_weeks": 3,
                    "stock": 1200,
                },
            ],
        }

    def test_saves_and_lists_two_quote_lines_as_one_supplier_document(self):
        response = self.client.post(
            "/tools/procurement/quote-groups",
            headers=self.headers,
            json=self._payload(),
        )
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["line_count"], 2)
        self.assertEqual(len(result["quotes"]), 2)
        self.assertEqual(
            {row["quote_group_id"] for row in result["quotes"]},
            {result["quote_group_id"]},
        )
        self.assertEqual(
            [row["quote_group_line_index"] for row in result["quotes"]],
            [1, 2],
        )
        self.assertEqual(
            {row["quote_group_line_count"] for row in result["quotes"]},
            {2},
        )
        self.assertEqual(
            {row["quote_reference"] for row in result["quotes"]},
            {"Q-4821"},
        )
        by_mpn = {row["requested_mpn"]: row for row in result["quotes"]}
        self.assertEqual(by_mpn["TPS54331D"]["price_breaks"][1]["unit_price"], 0.91)
        self.assertEqual(by_mpn["LM358DR"]["minimum_order_quantity"], 10)
        self.assertEqual(by_mpn["LM358DR"]["pack_quantity"], 5)
        self.assertTrue(all(row["identity_status"] == "exact_part" for row in result["quotes"]))

        listed = self.client.get(
            "/tools/procurement/quotes?analysis_id=" + self.analysis_id,
            headers=self.headers,
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["quotes"]), 2)

        one_line = self.client.get(
            "/tools/procurement/quotes?analysis_id=" + self.analysis_id
            + "&mpn=LM358DR&manufacturer=Texas%20Instruments",
            headers=self.headers,
        )
        self.assertEqual(one_line.status_code, 200, one_line.text)
        self.assertEqual(len(one_line.json()["quotes"]), 1)
        self.assertEqual(
            one_line.json()["quotes"][0]["quote_group_id"],
            result["quote_group_id"],
        )
        self.assertEqual(one_line.json()["quotes"][0]["quote_group_line_count"], 2)

    def test_rejects_duplicate_component_without_saving_a_partial_group(self):
        payload = self._payload()
        payload["lines"][1]["requested_mpn"] = "TPS54331D"
        payload["lines"][1]["requested_manufacturer"] = "Texas Instruments"
        response = self.client.post(
            "/tools/procurement/quote-groups",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("only once", response.json()["detail"])
        saved = get_store().list_procurement_quotes(
            workspace_id=self.workspace_id,
            analysis_id=self.analysis_id,
        )
        self.assertEqual(saved, [])

    def test_rejects_a_line_not_in_this_bom_revision_without_saving(self):
        payload = self._payload()
        payload["lines"][1]["requested_mpn"] = "NOT-IN-BOM"
        response = self.client.post(
            "/tools/procurement/quote-groups",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(response.status_code, 400, response.text)
        saved = get_store().list_procurement_quotes(
            workspace_id=self.workspace_id,
            analysis_id=self.analysis_id,
        )
        self.assertEqual(saved, [])

    def test_postgres_group_uses_one_transaction_for_all_lines(self):
        store = object.__new__(PostgresWorkspaceStore)
        connection = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = connection
        context.__exit__.return_value = False
        records = [
            {
                "analysis_id": "analysis-postgres-group",
                "requested_mpn": "TPS54331D",
                "requested_manufacturer": "Texas Instruments",
                "quote_group_id": "group-postgres-1",
            },
            {
                "analysis_id": "analysis-postgres-group",
                "requested_mpn": "LM358DR",
                "requested_manufacturer": "Texas Instruments",
                "quote_group_id": "group-postgres-1",
            },
        ]
        with patch.object(store, "get_report", return_value={"id": "analysis-postgres-group"}):
            with patch.object(store, "_connect", return_value=context):
                saved = store.create_procurement_quote_group(
                    records, workspace_id="workspace-postgres-test"
                )
        self.assertEqual(len(saved), 2)
        self.assertEqual({row["quote_group_id"] for row in saved}, {"group-postgres-1"})
        self.assertEqual(connection.execute.call_count, 2)
        connection.commit.assert_called_once()

    def test_postgres_group_does_not_commit_if_a_line_insert_fails(self):
        store = object.__new__(PostgresWorkspaceStore)
        connection = MagicMock()
        connection.execute.side_effect = [None, RuntimeError("injected insert failure")]
        context = MagicMock()
        context.__enter__.return_value = connection
        context.__exit__.return_value = False
        records = [
            {
                "analysis_id": "analysis-postgres-group",
                "requested_mpn": "TPS54331D",
                "quote_group_id": "group-postgres-1",
            },
            {
                "analysis_id": "analysis-postgres-group",
                "requested_mpn": "LM358DR",
                "quote_group_id": "group-postgres-1",
            },
        ]
        with patch.object(store, "get_report", return_value={"id": "analysis-postgres-group"}):
            with patch.object(store, "_connect", return_value=context):
                with self.assertRaisesRegex(RuntimeError, "injected insert failure"):
                    store.create_procurement_quote_group(
                        records, workspace_id="workspace-postgres-test"
                    )
        connection.commit.assert_not_called()
        context.__exit__.assert_called_once()
        self.assertIs(context.__exit__.call_args.args[0], RuntimeError)

    def test_marks_a_different_offered_mpn_as_an_alternate_candidate(self):
        payload = self._payload()
        payload["lines"][1]["offered_mpn"] = "LM358DR-ALT"
        response = self.client.post(
            "/tools/procurement/quote-groups",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(response.status_code, 201, response.text)
        alternate = next(
            row for row in response.json()["quotes"]
            if row["requested_mpn"] == "LM358DR"
        )
        self.assertEqual(alternate["identity_status"], "alternate_candidate")
        self.assertTrue(alternate["requires_engineering_review"])


if __name__ == "__main__":
    unittest.main()
