#!/usr/bin/env python3
"""Browser smoke for FR → Compare → Decision honesty with fixture API responses.

Uses the production Next build (same commit as the PR) and fulfills supplier/API
routes with fixtures — no live distributor calls.

  CADIVOR_SMOKE_WEB=http://127.0.0.1:3000 \\
  CADIVOR_SMOKE_EMAIL=... CADIVOR_SMOKE_PASSWORD=... \\
  python tests/harness_fr_compare_decision_browser_smoke.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".evidence_ui" / "fr_compare_decision_honesty" / "browser_smoke"
WEB = os.environ.get("CADIVOR_SMOKE_WEB", "http://127.0.0.1:3000").rstrip("/")
EMAIL = os.environ.get("CADIVOR_SMOKE_EMAIL", "smoke@cadivor.test")
PASSWORD = os.environ.get("CADIVOR_SMOKE_PASSWORD", "SmokeTest!234")

FIND_REPLACEMENT_FIXTURE = {
    "ok": True,
    "requested_mpn": "LM358DR",
    "search_outcome": "success",
    "search_outcome_label": "Supplier-listed candidates found — fit unverified",
    "candidates": [
        {
            "mpn": "LM358ADR2G",
            "manufacturer": "onsemi",
            "lifecycle_status": "Active",
            "fit": "supplier-listed candidate; qualification required",
            "classification": "Compatible",
            "rationale": "Supplier-listed candidate only.",
            "missing_evidence": ["datasheet-backed electrical review"],
            "evidence_class": "live-authorized-supplier",
        }
    ],
    "discovery": {
        "catalog_raw_count": 39,
        "catalog_retained_count": 24,
        "explicit_count": 2,
        "explicit_retained_count": 0,
        "catalog_filter_summary": (
            "39 raw catalog matches → 24 retained after manufacturer, family, "
            "and deduplication filters"
        ),
        "providers": {
            "Mouser": {
                "catalog": "ok",
                "catalog_raw_count": 39,
                "catalog_retained_count": 24,
            },
            "DigiKey": {
                "substitutions": "ok",
                "explicit_count": 2,
                "explicit_retained_count": 0,
            },
        },
    },
    "bom_context": None,
}

COMPARE_STANDALONE_FIXTURE = {
    "ok": True,
    "status": "completed",
    "part_a": "LM358DR",
    "part_b": "LM358ADR2G",
    "finding": "Needs verification",
    "engineering_evidence_summary": (
        "Engineering evidence: incomplete — 0 verified matches, "
        "3 fields need verification; 2 catalog agreements "
        "(Catalog values agree — fit unverified)"
    ),
    "counts": {
        "compatible": 0,
        "listing_agreement": 2,
        "material_difference": 0,
        "needs_data": 3,
        "conflicting": 0,
        "catalog_difference": 1,
    },
    "internal_status_counts": {
        "Match": 2,
        "Listing agreement": 0,
        "Different": 1,
        "Needs data": 3,
        "Conflicting": 0,
    },
    "rows": [
        {
            "Attribute": "Input offset",
            "Part A": "3 mV",
            "Part B": "2 mV",
            "Assessment": "Catalog values differ — fit unverified",
            "Part A source": "DigiKey",
            "Part B source": "Mouser",
        },
        {
            "Attribute": "Package",
            "Part A": "SOIC-8",
            "Part B": "SOIC-8",
            "Assessment": "Catalog values agree — fit unverified",
            "Part A source": "DigiKey",
            "Part B source": "Mouser",
        },
    ],
    "analysis_id": None,
    "gap": "",
    "family": "Operational amplifier",
    "part_cards": {
        "a": {"mpn": "LM358DR", "manufacturer": "Texas Instruments"},
        "b": {"mpn": "LM358ADR2G", "manufacturer": "onsemi"},
    },
}

COMPARE_SCOPED_FIXTURE = {
    **COMPARE_STANDALONE_FIXTURE,
    "analysis_id": "fixture-bom-analysis-1",
}

DECISION_RECORD = {
    "ok": True,
    "record": {
        "id": "fixture-decision-1",
        "part_a": "LM358DR",
        "part_b": "LM358ADR2G",
        "decision": "hold_for_review",
        "analysis_id": None,
        "comparison_snapshot": {
            "finding": "Needs verification",
            "engineering_evidence_summary": COMPARE_STANDALONE_FIXTURE[
                "engineering_evidence_summary"
            ],
            "counts": COMPARE_STANDALONE_FIXTURE["counts"],
        },
    },
}

REPORTS_FIXTURE = {
    "ok": True,
    "reports": [
        {
            "id": "fixture-bom-analysis-1",
            "analysis_id": "fixture-bom-analysis-1",
            "bom_name": "Fixture BOM",
            "project_name": "Honesty Smoke",
        }
    ],
}


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {"web": WEB, "steps": [], "ok": False}

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"playwright_import:{exc}"
        (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
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
                analysis_id = str(body.get("analysis_id") or "").strip()
                payload = (
                    COMPARE_SCOPED_FIXTURE if analysis_id else COMPARE_STANDALONE_FIXTURE
                )
                return _fulfill_json(route, payload)
            if "/decision-records" in url and method == "POST":
                return _fulfill_json(route, DECISION_RECORD, status=201)
            if "/decision-records" in url and method == "GET":
                return _fulfill_json(
                    route,
                    {"ok": True, "records": [DECISION_RECORD["record"]]},
                )
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

        # 1) Standalone Find Replacement
        page.goto(f"{WEB}/login", wait_until="domcontentloaded", timeout=60000)
        seed_session()
        page.goto(f"{WEB}/find-replacement", wait_until="domcontentloaded", timeout=60000)
        seed_session()
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#replacement-mpn", timeout=30000)

        page.locator("#replacement-mpn").fill("LM358DR")
        page.get_by_role("button", name=re.compile(r"Find candidates", re.I)).click()
        page.wait_for_selector("[data-testid='search-outcome-label']", timeout=30000)
        body = page.locator("body").inner_text()
        assert "Supplier-listed candidates found — fit unverified" in body
        assert "Verified replacements found" not in body
        assert "Qualified alternatives" not in body
        assert "Supplier-listed candidates" in body
        assert "0 retained supplier substitutions" in body
        assert "39 raw catalog matches" in body and "24 retained" in body
        page.screenshot(path=str(OUT / "01_find_replacement.png"), full_page=True)
        report["steps"].append("standalone_find_replacement")

        # 2) Candidate → Compare handoff (no analysis_id)
        page.locator(
            '.cv-table-replacement--candidates input[type="checkbox"]'
        ).first.check()
        href = page.locator("a", has_text=re.compile(r"Compare selected", re.I)).get_attribute(
            "href"
        )
        assert href and "part_a=LM358DR" in href and "part_b=LM358ADR2G" in href
        assert "analysis_id=" not in href
        page.goto(f"{WEB}{href}", wait_until="domcontentloaded")
        report["steps"].append("candidate_to_compare_handoff")

        # 3) Standalone Compare
        page.get_by_role("button", name=re.compile(r"Compare parts", re.I)).click()
        page.wait_for_selector(".cv-compare-screening", timeout=30000)
        compare_body = page.locator("body").inner_text()
        assert "Needs verification" in compare_body
        assert "Catalog values agree — fit unverified" in compare_body or "fit unverified" in compare_body.casefold()
        assert "confirmed matches" not in compare_body.casefold()
        # BOM select should be clearable / default standalone
        bom_select = page.locator("#compare-bom-context")
        assert bom_select.count() == 1
        assert bom_select.input_value() == ""
        page.screenshot(path=str(OUT / "02_compare_standalone.png"), full_page=True)
        report["steps"].append("standalone_compare")

        # 4) BOM-scoped Compare
        bom_select.select_option(value="fixture-bom-analysis-1")
        page.get_by_role("button", name=re.compile(r"Compare parts", re.I)).click()
        page.wait_for_selector(".cv-compare-screening", timeout=30000)
        scoped_text = page.locator("#compare-bom-help").inner_text()
        assert "BOM context attached" in scoped_text
        page.screenshot(path=str(OUT / "03_compare_bom_scoped.png"), full_page=True)
        report["steps"].append("bom_scoped_compare")

        # Clear BOM and confirm standalone again
        page.get_by_role("button", name=re.compile(r"Clear BOM", re.I)).click()
        assert bom_select.input_value() == ""
        report["steps"].append("clear_bom_context")

        # 5) Decision save + reload
        page.get_by_role("button", name=re.compile(r"Record a decision", re.I)).click()
        page.wait_for_selector("#decision-dialog-title", timeout=15000)
        page.get_by_label("Reviewer").fill(EMAIL)
        page.get_by_label("Rationale").fill(
            "Fixture browser smoke: hold pending datasheet verification."
        )
        submit = page.get_by_role("button", name=re.compile(r"^Record decision$", re.I))
        page.wait_for_function(
            """() => {
              const buttons = Array.from(document.querySelectorAll('button'));
              const target = buttons.find((b) => /^Record decision$/i.test((b.textContent || '').trim()));
              return Boolean(target && !target.disabled);
            }""",
            timeout=10000,
        )
        submit.click()
        page.wait_for_selector("text=Decision recorded", timeout=30000)
        page.screenshot(path=str(OUT / "04_decision_saved.png"), full_page=True)
        page.goto(f"{WEB}/engineering-decisions", wait_until="domcontentloaded")
        page.reload(wait_until="domcontentloaded")
        decisions_body = page.locator("body").inner_text()
        page.screenshot(path=str(OUT / "05_decision_reload.png"), full_page=True)
        report["steps"].append("decision_save_reload")
        report["decision_page_loaded"] = bool(decisions_body.strip())
        # Fixture listing should surface the saved pair after reload.
        report["decision_pair_visible"] = (
            "LM358DR" in decisions_body and "LM358ADR2G" in decisions_body
        )

        browser.close()

    report["ok"] = True
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
