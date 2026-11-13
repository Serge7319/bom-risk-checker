#!/usr/bin/env python3
"""Browser smoke: workspace-level decision scope + multi-candidate manufacturers.

Synthetic fixture API only — no customer BOMs, no emails, no live distributors.

  CADIVOR_SMOKE_WEB=http://127.0.0.1:3019 \\
  python tests/harness_fr_compare_decision_scope_smoke.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".evidence_ui" / "fr_compare_decision_scope" / "browser_smoke"
WEB = os.environ.get("CADIVOR_SMOKE_WEB", "http://127.0.0.1:3000").rstrip("/")
EMAIL = os.environ.get("CADIVOR_SMOKE_EMAIL", "smoke@cadivor.test")
PASSWORD = os.environ.get("CADIVOR_SMOKE_PASSWORD", "SmokeTest!234")

CANDIDATES = [
    ("LM358AN/NOPB", "Texas Instruments"),
    ("LM358DT", "STMicroelectronics"),
    ("LM358DR2G", "onsemi"),
]

FIND_REPLACEMENT_FIXTURE = {
    "ok": True,
    "requested_mpn": "LM358N",
    "requested_manufacturer": "Texas Instruments",
    "search_outcome": "success",
    "search_outcome_label": "Supplier-listed candidates found — fit unverified",
    "original": {
        "mpn": "LM358N",
        "manufacturer": "Texas Instruments",
        "identity_verified": True,
    },
    "candidates": [
        {
            "mpn": mpn,
            "manufacturer": brand,
            "lifecycle_status": "Active",
            "fit": "supplier-listed candidate; qualification required",
            "classification": "Compatible",
            "rationale": f"Supplier-listed {brand} candidate.",
            "missing_evidence": ["datasheet-backed electrical review"],
            "evidence_class": "live-authorized-supplier",
        }
        for mpn, brand in CANDIDATES
    ],
    "discovery": {
        "catalog_raw_count": 12,
        "catalog_retained_count": 8,
        "explicit_count": 0,
        "explicit_retained_count": 0,
        "providers": {"Mouser": {"catalog": "ok"}},
    },
    "bom_context": None,
}


def _compare_fixture(part_b: str, manufacturer_b: str, analysis_id: str | None = None) -> dict:
    return {
        "ok": True,
        "status": "completed",
        "part_a": "LM358N",
        "part_b": part_b,
        "manufacturer_a": "Texas Instruments",
        "manufacturer_b": manufacturer_b,
        "finding": "Needs verification",
        "engineering_evidence_summary": (
            "Engineering evidence: incomplete — 0 verified matches, "
            "1 field need verification; 1 catalog agreement "
            "(Catalog values agree — fit unverified)"
        ),
        "engineering_evidence_status": "incomplete",
        "counts": {
            "compatible": 0,
            "listing_agreement": 1,
            "material_difference": 0,
            "needs_data": 1,
            "conflicting": 0,
            "breakdown": {"catalog_difference": 0},
        },
        "rows": [
            {
                "Attribute": "Package",
                "Part A": "PDIP-8",
                "Part B": "SOIC-8",
                "Assessment": "Catalog values agree — fit unverified",
                "Part A source": "DigiKey",
                "Part B source": "Mouser",
            }
        ],
        "analysis_id": analysis_id,
        "gap": "",
        "family": "Operational amplifier",
        "part_cards": {
            "a": {
                "mpn": "LM358N",
                "manufacturer": "Texas Instruments",
                "identity_verified": True,
                "found": True,
            },
            "b": {
                "mpn": part_b,
                "manufacturer": manufacturer_b,
                "identity_verified": True,
                "found": True,
            },
        },
        "source_a": "DigiKey",
        "source_b": "Mouser",
        "evidence_sources": {"part_a": [], "part_b": []},
    }


REPORTS_FIXTURE = {
    "ok": True,
    "reports": [
        {
            "id": "fixture-bom-analysis-1",
            "analysis_id": "fixture-bom-analysis-1",
            "bom_name": "Synthetic Fixture BOM",
            "project_name": "Decision Scope Smoke",
        },
        {
            "id": "fixture-bom-analysis-2",
            "analysis_id": "fixture-bom-analysis-2",
            "bom_name": "Other Saved BOM",
            "project_name": "Should Not Auto Select",
        },
    ],
}

_captured_decisions: list[dict] = []


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"web": WEB, "steps": [], "ok": False}
    _captured_decisions.clear()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"playwright_import:{exc}"
        (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        def on_route(route):
            url = route.request.url
            method = route.request.method.upper()
            if "/tools/find-replacement" in url and method == "POST":
                return _fulfill_json(route, FIND_REPLACEMENT_FIXTURE)
            if "/tools/compare-parts" in url and method == "POST":
                try:
                    body = route.request.post_data_json or {}
                except Exception:  # noqa: BLE001
                    body = {}
                part_b = str(body.get("part_b") or "").strip()
                manufacturer_b = str(body.get("manufacturer_b") or "").strip()
                analysis_id = str(body.get("analysis_id") or "").strip() or None
                brand_map = {mpn: brand for mpn, brand in CANDIDATES}
                echoed = _compare_fixture(
                    part_b or "LM358AN/NOPB",
                    manufacturer_b or brand_map.get(part_b, "Texas Instruments"),
                    analysis_id=analysis_id,
                )
                if body.get("manufacturer_a"):
                    echoed["manufacturer_a"] = body.get("manufacturer_a")
                return _fulfill_json(route, echoed)
            if "/decision-records" in url and method == "POST":
                try:
                    body = route.request.post_data_json or {}
                except Exception:  # noqa: BLE001
                    body = {}
                _captured_decisions.append(body)
                snap = body.get("comparison_snapshot") or {}
                record = {
                    "id": f"fixture-decision-{len(_captured_decisions)}",
                    "part_a": body.get("part_a"),
                    "part_b": body.get("part_b"),
                    "manufacturer_a": body.get("manufacturer_a"),
                    "manufacturer_b": body.get("manufacturer_b"),
                    "analysis_id": body.get("analysis_id"),
                    "decision": body.get("decision") or "hold_for_review",
                    "decision_label": "Hold for review",
                    "reviewer": body.get("reviewer") or EMAIL,
                    "rationale": body.get("rationale") or "",
                    "comparison_snapshot": snap,
                    "qualification_note": "",
                    "created_at": "2026-11-13T00:00:00Z",
                }
                return _fulfill_json(route, {"ok": True, "record": record}, status=201)
            if "/decision-records" in url and method == "GET":
                records = []
                for idx, body in enumerate(_captured_decisions, start=1):
                    records.append(
                        {
                            "id": f"fixture-decision-{idx}",
                            "part_a": body.get("part_a"),
                            "part_b": body.get("part_b"),
                            "manufacturer_a": body.get("manufacturer_a"),
                            "manufacturer_b": body.get("manufacturer_b"),
                            "analysis_id": body.get("analysis_id"),
                            "decision": body.get("decision") or "hold_for_review",
                            "decision_label": "Hold for review",
                            "reviewer": body.get("reviewer") or EMAIL,
                            "rationale": body.get("rationale") or "",
                            "comparison_snapshot": body.get("comparison_snapshot") or {},
                            "qualification_note": "",
                            "created_at": "2026-11-13T00:00:00Z",
                            "bom_name": (
                                "Synthetic Fixture BOM"
                                if body.get("analysis_id")
                                else None
                            ),
                            "project_name": (
                                "Decision Scope Smoke"
                                if body.get("analysis_id")
                                else "Workspace"
                            ),
                        }
                    )
                return _fulfill_json(route, {"ok": True, "records": records})
            if "/reports" in url and method == "GET":
                return _fulfill_json(route, REPORTS_FIXTURE)
            if "/auth/login" in url and method == "POST":
                return _fulfill_json(
                    route,
                    {
                        "ok": True,
                        "access_token": "fixture-access-token",
                        "refresh_token": "fixture-refresh-token",
                        "email": EMAIL,
                        "user": {"email": EMAIL, "id": "fixture-user"},
                    },
                )
            if "/auth/me" in url or "/session" in url:
                return _fulfill_json(
                    route,
                    {
                        "ok": True,
                        "email": EMAIL,
                        "user": {"email": EMAIL, "id": "fixture-user"},
                        "workspace_id": "fixture-workspace",
                    },
                )
            return route.continue_()

        page.route("**/tools/**", on_route)
        page.route("**/decision-records**", on_route)
        page.route("**/reports**", on_route)
        page.route("**/auth/**", on_route)
        page.route("http://127.0.0.1:9999/**", on_route)
        page.route("http://localhost:9999/**", on_route)

        session_json = json.dumps(
            {
                "access_token": "fixture-access-token",
                "email": EMAIL,
                "user_id": "fixture-user",
                "workspace_id": "fixture-workspace",
                "workspace": "Fixture workspace",
                "plan": "trial",
                "mode": "sandbox",
            }
        )

        def seed_session():
            page.evaluate(
                """(payload) => {
                  localStorage.setItem('cadivor_next_session', payload);
                  localStorage.removeItem('cadivor_next_sandbox_session');
                }""",
                session_json,
            )

        # --- Standalone multi-candidate FR → Compare → workspace decision ---
        page.goto(f"{WEB}/login", wait_until="domcontentloaded", timeout=60000)
        seed_session()
        page.goto(f"{WEB}/find-replacement", wait_until="domcontentloaded", timeout=60000)
        seed_session()
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#replacement-mpn", timeout=30000)
        page.locator("#replacement-mpn").fill("LM358N")
        page.locator("#replacement-mfr").fill("Texas Instruments")
        page.get_by_role("button", name=re.compile(r"Find candidates", re.I)).click()
        page.wait_for_selector("[data-testid='search-outcome-label']", timeout=30000)
        for mpn, brand in CANDIDATES:
            page.get_by_label(re.compile(rf"Select {re.escape(mpn)}", re.I)).check()
        href = page.locator("a", has_text=re.compile(r"Compare selected", re.I)).get_attribute(
            "href"
        )
        assert href and href != "#"
        query = parse_qs(urlparse(href).query)
        assert query.get("part_a", [""])[0] == "LM358N"
        assert "analysis_id" not in query
        assert len(query.get("part_b", [])) == 3
        assert len(query.get("manufacturer_b", [])) == 3
        assert "Texas" in " ".join(query.get("manufacturer_a", []))
        brands_joined = " ".join(query.get("manufacturer_b", []))
        assert "Texas" in brands_joined
        assert "ST" in brands_joined or "STMicroelectronics" in brands_joined
        assert "onsemi" in brands_joined.casefold()
        page.screenshot(path=str(OUT / "01_fr_three_candidates.png"), full_page=True)
        report["steps"].append("standalone_fr_select_three")

        page.goto(f"{WEB}{href}", wait_until="domcontentloaded")
        page.get_by_role("button", name=re.compile(r"Compare parts", re.I)).click()
        page.wait_for_selector(".cv-compare-multi-table", timeout=60000)
        body = page.locator("body").inner_text()
        body_fold = body.casefold()
        for mpn, brand in CANDIDATES:
            assert mpn in body
            assert brand.casefold() in body_fold
            heading = page.locator(f"[data-testid='multi-col-{mpn}']").inner_text()
            heading_fold = heading.casefold()
            assert mpn.casefold() in heading_fold
            assert brand.casefold() in heading_fold
        evidence = page.locator("[data-testid='multi-source-records']").inner_text()
        evidence_fold = evidence.casefold()
        for mpn, brand in CANDIDATES:
            assert mpn in evidence
            assert brand.casefold() in evidence_fold
        page.screenshot(path=str(OUT / "02_multi_compare_brands.png"), full_page=True)
        report["steps"].append("multi_compare_visible_brands")

        # Decision dialog must visibly select workspace-level, not first BOM.
        page.get_by_role("button", name=re.compile(r"Record a decision", re.I)).click()
        page.wait_for_selector("#decision-dialog-title", timeout=15000)
        scope = page.locator("#decision-bom-scope")
        assert scope.input_value() == ""
        selected_label = page.locator("#decision-bom-scope option:checked").inner_text()
        assert "No BOM" in selected_label
        assert "workspace-level" in selected_label.casefold()
        help_text = page.locator("#decision-bom-scope-help").inner_text()
        assert "Workspace-level" in help_text or "analysis_id unset" in help_text.casefold()
        page.get_by_label("Reviewer").fill(EMAIL)
        page.get_by_label("Rationale").fill(
            "Workspace-level multi TI/ST/onsemi decision — no BOM attached."
        )
        page.wait_for_function(
            """() => {
              const buttons = Array.from(document.querySelectorAll('button'));
              const target = buttons.find((b) => /^Record decision$/i.test((b.textContent || '').trim()));
              return Boolean(target && !target.disabled);
            }""",
            timeout=10000,
        )
        page.get_by_role("button", name=re.compile(r"^Record decision$", re.I)).click()
        page.wait_for_selector("text=Decision recorded", timeout=30000)
        assert _captured_decisions, "decision POST was not captured"
        first = _captured_decisions[-1]
        assert first.get("analysis_id") in {None, ""}
        snap = first.get("comparison_snapshot") or {}
        brands = snap.get("multi_candidate_manufacturers") or {}
        assert brands.get("LM358AN/NOPB") == "Texas Instruments"
        assert brands.get("LM358DT") == "STMicroelectronics"
        assert brands.get("LM358DR2G") == "onsemi"
        page.screenshot(path=str(OUT / "03_workspace_decision_saved.png"), full_page=True)
        report["steps"].append("workspace_decision_saved")

        page.goto(f"{WEB}/engineering-decisions", wait_until="domcontentloaded")
        page.reload(wait_until="domcontentloaded")
        decisions_body = page.locator("body").inner_text()
        assert "No BOM — workspace-level decision" in decisions_body
        assert "LM358AN/NOPB" in decisions_body
        assert "Texas Instruments" in decisions_body
        assert "STMicroelectronics" in decisions_body or "LM358DT" in decisions_body
        assert "onsemi" in decisions_body.casefold()
        page.screenshot(path=str(OUT / "04_workspace_decision_reload.png"), full_page=True)
        report["steps"].append("workspace_decision_reload")

        # --- BOM-scoped compare stays on the exact BOM ---
        page.goto(
            f"{WEB}/compare-parts?part_a=LM358N&part_b=LM358AN%2FNOPB"
            "&manufacturer_a=Texas%20Instruments&manufacturer_b=Texas%20Instruments"
            "&analysis_id=fixture-bom-analysis-1",
            wait_until="domcontentloaded",
        )
        assert page.locator("#compare-bom-context").input_value() == "fixture-bom-analysis-1"
        page.get_by_role("button", name=re.compile(r"Compare parts", re.I)).click()
        page.wait_for_selector(".cv-compare-screening", timeout=30000)
        assert "BOM context attached" in page.locator("#compare-bom-help").inner_text()
        assert "Other Saved BOM" not in page.locator("#compare-bom-help").inner_text()
        page.get_by_role("button", name=re.compile(r"Record a decision", re.I)).click()
        page.wait_for_selector("#decision-bom-scope", timeout=15000)
        assert page.locator("#decision-bom-scope").input_value() == "fixture-bom-analysis-1"
        page.get_by_label("Reviewer").fill(EMAIL)
        page.get_by_label("Rationale").fill(
            "BOM-scoped decision must stay on fixture-bom-analysis-1."
        )
        page.wait_for_function(
            """() => {
              const buttons = Array.from(document.querySelectorAll('button'));
              const target = buttons.find((b) => /^Record decision$/i.test((b.textContent || '').trim()));
              return Boolean(target && !target.disabled);
            }""",
            timeout=10000,
        )
        page.get_by_role("button", name=re.compile(r"^Record decision$", re.I)).click()
        page.wait_for_selector("text=Decision recorded", timeout=30000)
        bom_decision = _captured_decisions[-1]
        assert bom_decision.get("analysis_id") == "fixture-bom-analysis-1"
        page.screenshot(path=str(OUT / "05_bom_scoped_decision.png"), full_page=True)
        report["steps"].append("bom_scoped_exact_analysis")

        browser.close()

    report["ok"] = True
    report["captured_decisions"] = len(_captured_decisions)
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        OUT.mkdir(parents=True, exist_ok=True)
        failure = {"ok": False, "error": str(exc), "web": WEB}
        (OUT / "report.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        print(json.dumps(failure, indent=2), file=sys.stderr)
        raise
