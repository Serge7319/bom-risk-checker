"""Acceptance regressions for the Nov 10 production-smoke evidence follow-up."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from apps.api.bom_hierarchy import attach_hierarchy_fields
from apps.api.migration_tools import procurement_payload
from apps.api.synthetic_analyze import analyze_upload, get_report
from apps.api.workspace_store import reset_store_for_tests
from src.component_family_profiles import (
    COMPARE_LIMIT_LE,
    FieldSpec,
    get_family_profile,
)
from src.datasheet_comparison import build_datasheet_comparison
from src.parametric_compare import compare_field_values, supply_range_finding
from src.parts_compare import FINDING_COMPATIBLE, FINDING_LISTING_AGREEMENT, map_status_to_assessment


ROOT = Path(__file__).resolve().parents[1]
WEB_COMPARE = ROOT / "apps" / "web" / "src" / "app" / "compare-parts" / "page.tsx"
WEB_PROCUREMENT = ROOT / "apps" / "web" / "src" / "app" / "procurement" / "page.tsx"
WEB_REPLACEMENT = ROOT / "apps" / "web" / "src" / "app" / "find-replacement" / "page.tsx"
MULTI_COMPARE = ROOT / "apps" / "web" / "src" / "lib" / "multiCompare.ts"


class UnknownClassAndRangeNormalizationTests(unittest.TestCase):
    def test_production_limit_field_unknown_class_needs_data(self):
        profile = get_family_profile("Operational amplifier")
        bias = next(field for field in profile.fields if field.key == "input_bias_na")
        self.assertEqual(bias.compare, COMPARE_LIMIT_LE)
        self.assertEqual(str(bias.value_role or "").casefold(), "max")
        status, note = compare_field_values("20 nA", "45 nA", bias)
        self.assertEqual(status, "Needs data")
        self.assertIn("class", note.casefold())
        self.assertNotEqual(status, "Different")
        self.assertNotEqual(map_status_to_assessment(status), FINDING_COMPATIBLE)

    def test_equal_supply_spans_with_alternate_punctuation_match(self):
        status, note = supply_range_finding("3 V ~ 32 V", "3V to 32V")
        self.assertEqual(status, "Match")
        self.assertIn("equivalent", note.casefold())

        voltage = FieldSpec(
            key="voltage_range",
            label="Supply voltage",
            compare="exact",
            unit="V",
            value_role="range",
        )
        field_status, field_note = compare_field_values("3 V ~ 32 V", "3V to 32V", voltage)
        self.assertEqual(field_status, "Match")
        self.assertIn("equivalent", field_note.casefold())

    def test_range_conditions_must_match_or_need_verification(self):
        temperature = FieldSpec(
            key="temperature_range",
            label="Operating temperature",
            compare="exact",
            unit="C",
            value_role="range",
        )
        equal_conditions = compare_field_values(
            "-40°C ~ 125°C (TA)",
            "-40°C to 125°C (TA)",
            temperature,
        )
        self.assertEqual(equal_conditions[0], "Match")

        different_conditions = compare_field_values(
            "-40°C ~ 125°C (TA)",
            "-40°C to 125°C @ 25C",
            temperature,
        )
        self.assertEqual(different_conditions[0], "Needs data")
        self.assertIn("condition", different_conditions[1].casefold())

        missing_one_side = compare_field_values(
            "-40°C ~ 125°C (TA)",
            "-40°C to 125°C",
            temperature,
        )
        self.assertEqual(missing_one_side[0], "Needs data")
        self.assertIn("part a", missing_one_side[1].casefold())
        self.assertIn("part b", missing_one_side[1].casefold())

        # Parenthetical class-only labels must not erase real conditions during span parse.
        voltage = FieldSpec(
            key="voltage_range",
            label="Supply voltage",
            compare="exact",
            unit="V",
            value_role="range",
        )
        self.assertEqual(
            compare_field_values("3 V ~ 32 V (TA)", "3V to 32V (TA)", voltage)[0],
            "Match",
        )
        self.assertEqual(
            compare_field_values("3 V ~ 32 V (TA)", "3V to 32V @ 25C", voltage)[0],
            "Needs data",
        )

        comparison = build_datasheet_comparison(
            {
                "architecture": "Operational Amplifier",
                "temperature_range": "-40°C ~ 125°C (TA)",
                "source": "DigiKey",
            },
            {
                "architecture": "Operational Amplifier",
                "temperature_range": "-40°C to 125°C @ 25C",
                "source": "Mouser",
            },
        )
        temp_row = next(
            row for row in comparison["rows"] if "temperature" in str(row.get("Attribute") or "").casefold()
        )
        self.assertEqual(temp_row.get("Part A test condition"), "TA")
        self.assertIn("25", str(temp_row.get("Part B test condition") or ""))
        self.assertIn("Part A:", str(temp_row.get("Test condition") or ""))
        self.assertIn("Part B:", str(temp_row.get("Test condition") or ""))
        self.assertEqual(temp_row.get("Status"), "Needs data")

    def test_catalog_mounting_match_is_listing_agreement(self):
        original = {
            "manufacturer_part_number": "LM358DR",
            "architecture": "Operational Amplifier",
            "package": "8-SOIC",
            "pin_count": 8,
            "mounting_style": "Surface Mount",
            "lifecycle_status": "Active",
            "source": "DigiKey",
        }
        candidate = {
            "manufacturer_part_number": "LM358DR2G",
            "architecture": "Operational Amplifier",
            "package": "8-SOIC",
            "pin_count": 8,
            "mounting_style": "SMT",
            "lifecycle_status": "Active",
            "source": "Mouser",
        }
        comparison = build_datasheet_comparison(original, candidate)
        by_attr = {row["Attribute"]: row for row in comparison["rows"]}
        self.assertIn("Mounting", by_attr)
        self.assertEqual(by_attr["Mounting"]["Status"], "Listing agreement")
        self.assertEqual(
            map_status_to_assessment(by_attr["Mounting"]["Status"]),
            FINDING_LISTING_AGREEMENT,
        )
        self.assertNotEqual(
            map_status_to_assessment(by_attr["Mounting"]["Status"]),
            FINDING_COMPATIBLE,
        )


class MultiAlternateSourceRecordTests(unittest.TestCase):
    def test_multi_compare_helpers_and_page_render_source_records(self):
        multi_src = MULTI_COMPARE.read_text(encoding="utf-8")
        page_src = WEB_COMPARE.read_text(encoding="utf-8")
        self.assertIn("buildMultiSourceRecords", multi_src)
        self.assertIn("buildMultiDecisionSnapshot", multi_src)
        self.assertIn("multi_source_records", multi_src)
        self.assertIn("candidate_snapshots", multi_src)
        self.assertIn("buildMultiSourceRecords", page_src)
        self.assertIn('data-testid="multi-source-records"', page_src)
        self.assertIn("Field-level evidence", page_src)


class ProcurementAnalysisSelectionTests(unittest.TestCase):
    def test_flat_and_nested_analyses_do_not_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            reset_store_for_tests(Path(tmp) / "store.json")
            flat_csv = (ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv").read_bytes()
            nested_csv = (ROOT / "tests" / "fixtures" / "nested_bom_product.csv").read_bytes()
            flat = analyze_upload(
                filename="flat.csv",
                payload=flat_csv,
                workspace_id="ws-procure",
                project_name="Flat Project",
                bom_name="flat-bom",
                revision="F1",
            )
            nested = analyze_upload(
                filename="nested.csv",
                payload=nested_csv,
                workspace_id="ws-procure",
                project_name="Nested Project",
                bom_name="nested-bom",
                revision="N1",
            )
            flat_id = str(flat["id"])
            nested_id = str(nested["id"])

            flat_payload = procurement_payload(workspace_id="ws-procure", analysis_id=flat_id)
            nested_payload = procurement_payload(workspace_id="ws-procure", analysis_id=nested_id)

            self.assertEqual(flat_payload["analysis_id"], flat_id)
            self.assertEqual(nested_payload["analysis_id"], nested_id)
            self.assertIn("Flat Project", str(flat_payload.get("project_name") or ""))
            self.assertIn("Nested Project", str(nested_payload.get("project_name") or ""))
            self.assertEqual(flat_payload.get("bom_name"), "flat-bom")
            self.assertEqual(nested_payload.get("bom_name"), "nested-bom")
            self.assertEqual(flat_payload.get("revision"), "F1")
            self.assertEqual(nested_payload.get("revision"), "N1")

            flat_mpns = {str(row.get("mpn") or "") for row in flat_payload.get("parts") or []}
            nested_mpns = {str(row.get("mpn") or "") for row in nested_payload.get("parts") or []}
            self.assertTrue(any("XC3S400" in mpn for mpn in flat_mpns))
            self.assertFalse(any("XC3S400" in mpn for mpn in nested_mpns))
            self.assertTrue(any(mpn in nested_mpns for mpn in ("PROD-TOP", "STM32F103")))
            self.assertFalse(any(mpn in flat_mpns for mpn in ("PROD-TOP", "PSU-ASM")))
            # Shared catalog MPNs (e.g. LM358DR) may appear in both fixtures, but
            # payloads remain scoped to the selected analysis_id / BOM context.

            missing = procurement_payload(workspace_id="ws-procure", analysis_id="does-not-exist")
            self.assertFalse(missing.get("ok"))
            self.assertEqual(missing.get("mode"), "analysis-not-found")

    def test_procurement_page_honors_analysis_id_and_selector(self):
        src = WEB_PROCUREMENT.read_text(encoding="utf-8")
        self.assertIn('searchParams.get("analysis_id")', src)
        self.assertIn('aria-label="Sourcing BOM context"', src)
        self.assertIn('data-testid="procurement-context"', src)
        self.assertIn("Select a saved analysis", src)
        self.assertIn("listReports", src)


class ReplacementProviderOutcomeTests(unittest.TestCase):
    def test_replacement_page_renders_provider_outcomes(self):
        src = WEB_REPLACEMENT.read_text(encoding="utf-8")
        self.assertIn('data-testid="replacement-provider-status"', src)
        self.assertIn("Not configured", src)
        self.assertIn("Timed out", src)
        self.assertIn("Returned", src)
        self.assertIn("providerOutcomeLabel", src)
        self.assertIn("providerLeadCount", src)
        self.assertNotIn("candidates.length + unclassifiedLeads.length", src)

    def test_synthetic_find_replacement_includes_provider_statuses(self):
        from apps.api.migration_tools import find_replacement_payload

        payload = find_replacement_payload(
            workspace_id="ws-provider",
            mpn="LM358DR",
        )
        discovery = payload.get("discovery") or {}
        providers = discovery.get("providers") or {}
        self.assertIn("DigiKey", providers)
        self.assertIn("Mouser", providers)
        self.assertIn("Newark", providers)
        self.assertIn("Offline catalog", providers)
        self.assertEqual(providers["DigiKey"].get("lookup"), "not_configured")
        offline = providers["Offline catalog"]
        self.assertIn(offline.get("catalog"), {"ok", "no_results"})
        self.assertIsInstance(offline.get("catalog_count"), int)


class ExactMpnDisplayTests(unittest.TestCase):
    def test_parent_mpn_keeps_bom_hyphens_for_display(self):
        fields = attach_hierarchy_fields({"parent_mpn": "PROD-TOP", "line_type": "part"})
        self.assertEqual(fields["Parent MPN"], "PROD-TOP")
        self.assertEqual(fields["parent_mpn_display"], "PROD-TOP")
        self.assertEqual(fields["parent_mpn"], "PRODTOP")

    def test_synthetic_analyze_prefers_raw_mpn_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            reset_store_for_tests(Path(tmp) / "store.json")
            csv_bytes = b"MPN,Quantity,parent_mpn,line_type\nPROD-TOP,1,,assembly\nPSU-ASM,2,PROD-TOP,assembly\n"
            report = analyze_upload(
                filename="hyphen.csv",
                payload=csv_bytes,
                workspace_id="ws-mpn",
                project_name="Hyphen Project",
                bom_name="hyphen-bom",
            )
            saved = get_report(report["id"], workspace_id="ws-mpn")
            self.assertIsNotNone(saved)
            by_mpn = {
                str(row.get("MPN") or row.get("mpn") or ""): row
                for row in (saved or {}).get("parts") or []
            }
            self.assertIn("PROD-TOP", by_mpn)
            self.assertIn("PSU-ASM", by_mpn)
            child = by_mpn["PSU-ASM"]
            self.assertEqual(child.get("Parent MPN") or child.get("parent_mpn_display"), "PROD-TOP")


class MultiCandidateSnapshotTrustTests(unittest.TestCase):
    def test_forged_multi_candidate_rows_force_recompute(self):
        import tempfile
        from unittest.mock import patch

        from apps.api.comparison_snapshot_trust import attach_snapshot_token
        from apps.api.main import app
        from apps.api.sandbox_auth import reset_auth_store_for_tests
        from apps.api.workspace_store import reset_store_for_tests
        from starlette.testclient import TestClient
        from tests.fixtures.sandbox_auth_accounts import SANDBOX_SEED_USERS

        captured = {"compare_calls": 0}

        def _fake_compare(**kwargs):
            captured["compare_calls"] += 1
            return {
                "ok": True,
                "part_a": kwargs.get("part_a") or "PART-A",
                "part_b": kwargs.get("part_b") or "PART-B",
                "analysis_id": kwargs.get("analysis_id") or "analysis-1",
                "rows": [{"Attribute": "Package", "Status": "Match", "Original": "SOIC", "Candidate": "SOIC"}],
                "mode": "synthetic-preview",
                "finding": "Needs verification",
                "source_a": "synthetic-preview",
                "source_b": "synthetic-preview",
                "datasheet_identity": {
                    "part_a": {"verified": False},
                    "part_b": {"verified": False},
                },
                "counts": {"Match": 1},
                "evidence_sources": {"part_a": [], "part_b": []},
            }

        with tempfile.TemporaryDirectory() as tmp:
            reset_store_for_tests(Path(tmp) / "store.json")
            reset_auth_store_for_tests(Path(tmp) / "auth.json", accounts=SANDBOX_SEED_USERS)
            with patch.dict(
                "os.environ",
                {
                    "CADIVOR_SANDBOX_AUTH_SECRET": "test-sandbox-auth-secret-key",
                    "CADIVOR_COMPARISON_SNAPSHOT_SECRET": "test-comparison-snapshot-secret",
                    "CADIVOR_ALLOW_EPHEMERAL_FILE_STORE": "1",
                    "CADIVOR_ALLOW_SANDBOX_JWT": "1",
                },
                clear=False,
            ), TestClient(app) as client, patch(
                "apps.api.main.migration_tools.compare_parts_payload",
                side_effect=_fake_compare,
            ):
                login = client.post(
                    "/auth/login",
                    json={
                        "email": SANDBOX_SEED_USERS[0]["email"],
                        "password": SANDBOX_SEED_USERS[0]["password"],
                    },
                )
                self.assertEqual(login.status_code, 200, login.text)
                token = login.json()["access_token"]
                me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
                self.assertEqual(me.status_code, 200, me.text)
                workspace_id = str(me.json().get("workspace_id") or "")
                user_id = str(me.json().get("user_id") or me.json().get("id") or "")

                analyze = client.post(
                    "/boms/analyze",
                    headers={"Authorization": f"Bearer {token}"},
                    data={
                        "project_name": "Multi snapshot",
                        "bom_name": "Synthetic",
                        "revision": "A",
                    },
                    files={
                        "file": (
                            "synthetic_bom_25parts.csv",
                            (ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv").read_bytes(),
                            "text/csv",
                        )
                    },
                )
                self.assertEqual(analyze.status_code, 200, analyze.text)
                analysis_id = analyze.json()["analysis_id"]
                report = client.get(
                    f"/reports/{analysis_id}",
                    headers={"Authorization": f"Bearer {token}"},
                ).json()
                part_a = report["parts"][0]["MPN"]
                part_b = report["parts"][1]["MPN"]
                part_c = report["parts"][2]["MPN"]

                signed = []
                for candidate in (part_b, part_c):
                    compare = client.post(
                        "/tools/compare-parts",
                        headers={"Authorization": f"Bearer {token}"},
                        json={
                            "part_a": part_a,
                            "part_b": candidate,
                            "analysis_id": analysis_id,
                        },
                    )
                    self.assertEqual(compare.status_code, 200, compare.text)
                    payload = compare.json()
                    self.assertTrue(payload.get("snapshot_token"))
                    signed.append(payload)
                baseline_calls = captured["compare_calls"]

                # Valid multi assembly should reuse without another compare.
                valid_multi = {
                    "ok": True,
                    "part_a": part_a,
                    "part_b": part_b,
                    "analysis_id": analysis_id,
                    "candidate_snapshots": signed,
                    "multi_candidate_mpns": [part_b, part_c],
                    "multi_matrix": [
                        {
                            "attribute": "Package",
                            "candidates": [{"mpn": part_b}, {"mpn": part_c}],
                        }
                    ],
                    "multi_source_records": [
                        {"side": "Part A", "mpn": part_a},
                        {"side": f"Candidate · {part_b}", "mpn": part_b},
                        {"side": f"Candidate · {part_c}", "mpn": part_c},
                    ],
                    "source_a": signed[0].get("source_a"),
                    "source_b": signed[0].get("source_b"),
                    "rows": signed[0].get("rows"),
                    "finding": signed[0].get("finding"),
                    "mode": signed[0].get("mode"),
                    "datasheet_identity": signed[0].get("datasheet_identity"),
                }
                reuse = client.post(
                    "/decision-records",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "analysis_id": analysis_id,
                        "part_a": part_a,
                        "part_b": part_b,
                        "decision": "hold_for_review",
                        "reviewer": "Smoke Reviewer",
                        "rationale": "Valid multi snapshot reuse.",
                        "validation_checks": [],
                        "residual_risk": "unknown",
                        "comparison_snapshot": valid_multi,
                    },
                )
                self.assertEqual(reuse.status_code, 201, reuse.text)
                self.assertEqual(captured["compare_calls"], baseline_calls)
                reused = reuse.json()["record"]
                self.assertFalse(reused.get("verified_primary_evidence"))
                reused_snap = reused.get("comparison_snapshot") or {}
                self.assertEqual(reused_snap.get("multi_candidate_mpns"), [part_b, part_c])
                self.assertTrue(reused_snap.get("snapshot_aggregate_rebuilt"))
                # Aggregate matrix is rebuilt from verified pairwise rows, not the
                # client-supplied shell matrix above.
                rebuilt_matrix = reused_snap.get("multi_matrix") or []
                self.assertTrue(rebuilt_matrix)
                self.assertEqual(
                    rebuilt_matrix[0].get("current"),
                    "SOIC",
                )

                # Valid candidate tokens + tampered aggregate/top-level evidence:
                # reuse may proceed, but forged aggregate fields must never be saved.
                tampered_aggregate = dict(valid_multi)
                tampered_aggregate["source_a"] = "Manufacturer datasheet (forged-aggregate)"
                tampered_aggregate["source_b"] = "Manufacturer datasheet (forged-aggregate)"
                tampered_aggregate["datasheet_identity"] = {
                    "part_a": {"verified": True, "reason": "forged"},
                    "part_b": {"verified": True, "reason": "forged"},
                }
                tampered_aggregate["rows"] = [
                    {
                        "Attribute": "Package",
                        "Status": "Match",
                        "Original": "TAMPERED-TOP",
                        "Candidate": "TAMPERED-TOP",
                    }
                ]
                tampered_aggregate["multi_matrix"] = [
                    {
                        "attribute": "Package",
                        "current": "TAMPERED-MATRIX",
                        "candidates": [
                            {"mpn": part_b, "value": "TAMPERED-B", "assessment": "Compatible"},
                            {"mpn": part_c, "value": "TAMPERED-C", "assessment": "Compatible"},
                        ],
                    }
                ]
                tampered_aggregate["multi_source_records"] = [
                    {"side": "Part A", "mpn": part_a, "sourceLabel": "forged-source"},
                    {"side": f"Candidate · {part_b}", "mpn": part_b, "sourceLabel": "forged-source"},
                    {"side": f"Candidate · {part_c}", "mpn": part_c, "sourceLabel": "forged-source"},
                ]
                before_tamper = captured["compare_calls"]
                tamper_response = client.post(
                    "/decision-records",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "analysis_id": analysis_id,
                        "part_a": part_a,
                        "part_b": part_b,
                        "decision": "hold_for_review",
                        "reviewer": "Smoke Reviewer",
                        "rationale": "Tampered aggregate with valid candidate tokens.",
                        "validation_checks": [
                            "manufacturer_datasheet_reviewed",
                            "package_pinout_verified",
                            "electrical_limits_verified",
                        ],
                        "residual_risk": "unknown",
                        "comparison_snapshot": tampered_aggregate,
                        "verified_primary_evidence": True,
                    },
                )
                self.assertEqual(tamper_response.status_code, 201, tamper_response.text)
                # Tokens remain valid, so no forced pairwise recompute is required —
                # but the saved aggregate must be server-rebuilt from those tokens.
                self.assertEqual(captured["compare_calls"], before_tamper)
                tamper_record = tamper_response.json()["record"]
                self.assertFalse(tamper_record.get("verified_primary_evidence"))
                tamper_snap = tamper_record.get("comparison_snapshot") or {}
                self.assertTrue(tamper_snap.get("snapshot_aggregate_rebuilt"))
                self.assertNotEqual(tamper_snap.get("source_a"), "Manufacturer datasheet (forged-aggregate)")
                self.assertNotEqual(
                    ((tamper_snap.get("rows") or [{}])[0]).get("Original"),
                    "TAMPERED-TOP",
                )
                matrix_blob = json.dumps(tamper_snap.get("multi_matrix") or [])
                self.assertNotIn("TAMPERED-MATRIX", matrix_blob)
                self.assertNotIn("TAMPERED-B", matrix_blob)
                self.assertNotIn("Compatible", matrix_blob)
                identity = tamper_snap.get("datasheet_identity") or {}
                self.assertFalse(((identity.get("part_a") or {}).get("verified")))
                self.assertFalse(((identity.get("part_b") or {}).get("verified")))

                # Forged candidate rows / sources / identity / analysis must not reuse.
                forged = dict(valid_multi)
                forged_candidates = [dict(signed[0]), dict(signed[1])]
                forged_candidates[0] = dict(forged_candidates[0])
                forged_candidates[0]["source_a"] = "Manufacturer datasheet (forged)"
                forged_candidates[0]["rows"] = [
                    {"Attribute": "Package", "Status": "Match", "Original": "FORGED", "Candidate": "FORGED"}
                ]
                forged_candidates[0]["datasheet_identity"] = {
                    "part_a": {"verified": True},
                    "part_b": {"verified": True},
                }
                forged["candidate_snapshots"] = forged_candidates
                forged["analysis_id"] = "forged-analysis-id"
                forged_response = client.post(
                    "/decision-records",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "analysis_id": analysis_id,
                        "part_a": part_a,
                        "part_b": part_b,
                        "decision": "hold_for_review",
                        "reviewer": "Smoke Reviewer",
                        "rationale": "Forged multi snapshot must recompute.",
                        "validation_checks": [
                            "manufacturer_datasheet_reviewed",
                            "package_pinout_verified",
                            "electrical_limits_verified",
                        ],
                        "residual_risk": "unknown",
                        "comparison_snapshot": forged,
                        "verified_primary_evidence": True,
                    },
                )
                self.assertEqual(forged_response.status_code, 201, forged_response.text)
                self.assertGreater(captured["compare_calls"], baseline_calls)
                forged_record = forged_response.json()["record"]
                self.assertFalse(forged_record.get("verified_primary_evidence"))
                self.assertNotEqual(
                    ((forged_record.get("comparison_snapshot") or {}).get("rows") or [{}])[0].get("Original"),
                    "FORGED",
                )

                # Unsigned multi shell (2+ candidates only) must also recompute.
                unsigned = {
                    "ok": True,
                    "part_a": part_a,
                    "part_b": part_b,
                    "analysis_id": analysis_id,
                    "candidate_snapshots": [
                        {"mpn": part_b, "part_a": part_a, "part_b": part_b, "rows": []},
                        {"mpn": part_c, "part_a": part_a, "part_b": part_c, "rows": []},
                    ],
                    "multi_candidate_mpns": [part_b, part_c],
                    "multi_matrix": [],
                    "multi_source_records": [],
                    "source_a": "Manufacturer datasheet (forged)",
                    "datasheet_identity": {
                        "part_a": {"verified": True},
                        "part_b": {"verified": True},
                    },
                }
                before_unsigned = captured["compare_calls"]
                unsigned_response = client.post(
                    "/decision-records",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "analysis_id": analysis_id,
                        "part_a": part_a,
                        "part_b": part_b,
                        "decision": "hold_for_review",
                        "reviewer": "Smoke Reviewer",
                        "rationale": "Unsigned multi shell must recompute.",
                        "validation_checks": [],
                        "residual_risk": "unknown",
                        "comparison_snapshot": unsigned,
                    },
                )
                self.assertEqual(unsigned_response.status_code, 201, unsigned_response.text)
                self.assertGreater(captured["compare_calls"], before_unsigned)
                self.assertFalse(unsigned_response.json()["record"].get("verified_primary_evidence"))

                # Sanity: attach helper still signs pairwise payloads for the workspace.
                signed_local = attach_snapshot_token(
                    dict(signed[0]),
                    workspace_id=workspace_id,
                    user_id=user_id or None,
                )
                self.assertTrue(signed_local.get("snapshot_token"))

                # Valid pairwise token + smuggled multi_* aggregates must not
                # persist forged multi evidence on reuse.
                pairwise_smuggle = dict(signed[0])
                pairwise_smuggle["multi_candidate_mpns"] = [part_b, part_c]
                pairwise_smuggle["multi_matrix"] = [
                    {
                        "attribute": "Package",
                        "current": "SMUGGLED",
                        "candidates": [
                            {"mpn": part_b, "value": "SMUGGLED-B"},
                            {"mpn": part_c, "value": "SMUGGLED-C"},
                        ],
                    }
                ]
                pairwise_smuggle["multi_source_records"] = [
                    {"side": "Part A", "mpn": part_a, "sourceLabel": "smuggled"}
                ]
                before_smuggle = captured["compare_calls"]
                smuggle_response = client.post(
                    "/decision-records",
                    headers={"Authorization": f"Bearer {token}"},
                    json={
                        "analysis_id": analysis_id,
                        "part_a": part_a,
                        "part_b": part_b,
                        "decision": "hold_for_review",
                        "reviewer": "Smoke Reviewer",
                        "rationale": "Pairwise token must not smuggle multi aggregates.",
                        "validation_checks": [],
                        "residual_risk": "unknown",
                        "comparison_snapshot": pairwise_smuggle,
                        "verified_primary_evidence": True,
                    },
                )
                self.assertEqual(smuggle_response.status_code, 201, smuggle_response.text)
                self.assertEqual(captured["compare_calls"], before_smuggle)
                smuggle_record = smuggle_response.json()["record"]
                self.assertFalse(smuggle_record.get("verified_primary_evidence"))
                smuggle_snap = smuggle_record.get("comparison_snapshot") or {}
                self.assertFalse(smuggle_snap.get("multi_matrix"))
                self.assertFalse(smuggle_snap.get("multi_source_records"))
                self.assertFalse(smuggle_snap.get("multi_candidate_mpns"))
                self.assertNotIn("SMUGGLED", json.dumps(smuggle_snap))


if __name__ == "__main__":
    unittest.main()
