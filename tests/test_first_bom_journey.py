"""Sprint 74 — first BOM customer journey harness and tests."""
from __future__ import annotations

import io
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from src.bom_parser import clean_bom_data, normalize_bom_columns, validate_bom
from src.plans import get_plan, validate_bom_against_plan
from src.services.user_provisioning import build_default_user_row


def run_first_bom_journey(
    *,
    bom_rows: list[dict],
    user_id: str = "user-1",
    monthly_upload_count: int = 0,
    plan_name: str = "Trial",
    supplier_lookup=None,
):
    """Deterministic first-BOM path without real supplier APIs or DB writes."""
    df = pd.DataFrame(bom_rows)
    df = normalize_bom_columns(df)
    df = validate_bom(df)
    df = clean_bom_data(df)

    plan = get_plan(plan_name)
    allowed, message = validate_bom_against_plan(
        df,
        plan,
        monthly_upload_count,
        is_admin=False,
    )
    if not allowed:
        return {"ok": False, "stage": "plan_validation", "message": message}

    lookup = supplier_lookup or (lambda part: {
        "manufacturer_part_number": part,
        "stock_total": 100,
        "supplier_count": 2,
        "lifecycle_status": "Active",
        "supplier_data_verified": True,
        "source": "Mouser",
    })

    results = []
    for _, row in df.iterrows():
        part_data = lookup(row["mpn_normalized"])
        results.append(
            {
                "user_id": user_id,
                "mpn": row["mpn"],
                "analysis_part": part_data["manufacturer_part_number"],
                "supplier_data_verified": part_data.get("supplier_data_verified", True),
            }
        )

    analysis_record = {
        "user_id": user_id,
        "project_name": "First BOM",
        "total_parts": len(results),
    }
    return {
        "ok": True,
        "stage": "complete",
        "analysis": analysis_record,
        "parts": results,
        "message": message,
    }


class FirstBomJourneyTests(unittest.TestCase):
    def test_newly_provisioned_user_defaults_to_trial(self):
        auth_user = types.SimpleNamespace(
            id="user-1",
            email="new@example.com",
            user_metadata={},
        )
        row = build_default_user_row(auth_user)
        self.assertEqual(row["plan"], "Trial")
        self.assertEqual(row["monthly_upload_count"], 0)

    def test_valid_csv_path_completes(self):
        result = run_first_bom_journey(
            bom_rows=[{"mpn": "LM358", "quantity": 10}],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["analysis"]["total_parts"], 1)
        self.assertEqual(result["parts"][0]["user_id"], "user-1")

    def test_valid_xlsx_path_completes(self):
        buffer = io.BytesIO()
        pd.DataFrame([{"Part Number": "LM358", "Qty": 5}]).to_excel(buffer, index=False)
        buffer.seek(0)
        df = pd.read_excel(buffer)
        df = normalize_bom_columns(df)
        df = validate_bom(df)
        df = clean_bom_data(df)
        result = run_first_bom_journey(
            bom_rows=df.to_dict(orient="records"),
        )
        self.assertTrue(result["ok"])

    def test_empty_bom_rejected(self):
        with self.assertRaises(ValueError):
            run_first_bom_journey(bom_rows=[])

    def test_missing_required_column_rejected(self):
        df = pd.DataFrame([{"quantity": 1}])
        df = normalize_bom_columns(df)
        with self.assertRaises(ValueError):
            validate_bom(df)

    def test_plan_limit_behavior(self):
        plan = get_plan("Starter")
        bom_df = pd.DataFrame([{"mpn": f"P{i}", "quantity": 1} for i in range(101)])
        bom_df["mpn_normalized"] = bom_df["mpn"]
        allowed, message = validate_bom_against_plan(bom_df, plan, 0, is_admin=False)
        self.assertFalse(allowed)
        self.assertIn("plan limit", message.lower())

    def test_analysis_persistence_belongs_to_same_user(self):
        result = run_first_bom_journey(
            bom_rows=[{"mpn": "LM358", "quantity": 1}],
            user_id="user-abc",
        )
        self.assertEqual(result["analysis"]["user_id"], "user-abc")
        self.assertTrue(all(part["user_id"] == "user-abc" for part in result["parts"]))

    def test_cross_user_isolation_in_harness(self):
        user_a = run_first_bom_journey(
            bom_rows=[{"mpn": "LM358", "quantity": 1}],
            user_id="user-a",
        )
        user_b = run_first_bom_journey(
            bom_rows=[{"mpn": "LM358", "quantity": 1}],
            user_id="user-b",
        )
        self.assertNotEqual(user_a["analysis"]["user_id"], user_b["analysis"]["user_id"])


if __name__ == "__main__":
    unittest.main()
