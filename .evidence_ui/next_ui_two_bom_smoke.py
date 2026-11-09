#!/usr/bin/env python3
"""Drive both synthetic BOMs through the local Next.js UI (not API-only).

Requires:
  - API on http://127.0.0.1:8081 (sandbox JWT + synthetic-preview)
  - Next on http://127.0.0.1:3001 with NEXT_PUBLIC_API_BASE pointing at that API

Asserts real compare + decision save with comparison_snapshot reuse, distinct
project/BOM labels, and report / procurement / Design Impact / export contents.
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from openpyxl import load_workbook
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".evidence_ui" / "next_ui_two_bom_597"
OUT.mkdir(parents=True, exist_ok=True)

WEB = "http://127.0.0.1:3001"
API = "http://127.0.0.1:8081"
EMAIL = "sandbox-a@cadivor.test"
PASSWORD = "CadivorSandbox!a"

BOMS = [
    {
        "label": "flat",
        "path": ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv",
        "project": "PR597 Flat Smoke",
        "bom_name": "flat-synthetic-25",
        "revision": "F1",
        "part_a": "XC3S400-4PQG208C",
        "part_b": "EPF10K20RC240-4N",
        "expected_mpns": ("XC3S400", "EPF10K20", "CY7C199"),
        "min_parts": 20,
    },
    {
        "label": "nested",
        "path": ROOT / "tests" / "fixtures" / "nested_bom_product.csv",
        "project": "PR597 Nested Smoke",
        "bom_name": "nested-product-hierarchy",
        "revision": "N1",
        "part_a": "STM32F103",
        "part_b": "EPF10K20RC2404N",
        "expected_mpns": ("PROD-TOP", "PSU-ASM", "STM32F103"),
        "min_parts": 5,
    },
]


def _api_json(method: str, path: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def _session_token(page: Page) -> str:
    token = page.evaluate(
        """() => {
          try {
            const raw = localStorage.getItem('cadivor_next_session')
              || localStorage.getItem('cadivor_next_sandbox_session');
            if (!raw) return '';
            const parsed = JSON.parse(raw);
            return parsed.access_token || parsed.token || '';
          } catch (e) { return ''; }
        }"""
    )
    if token:
        return str(token)
    req = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return str(json.loads(resp.read().decode()).get("access_token") or "")


def _fill_labeled_input(page: Page, label: str, value: str) -> None:
    field = (
        page.locator("label.cv-field")
        .filter(has=page.locator("span", has_text=re.compile(rf"^{re.escape(label)}$", re.I)))
        .locator("input")
        .first
    )
    field.fill(value)


def _inspect_exports(
    prefix: str,
    analysis_id: str,
    token: str,
    *,
    project: str,
    bom_name: str,
    expected_mpns: tuple[str, ...],
    min_parts: int,
) -> dict:
    results: dict = {}
    for fmt in ("pdf", "xlsx", "csv"):
        req = urllib.request.Request(
            f"{API}/reports/{analysis_id}/export/{fmt}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        path = OUT / f"{prefix}_report.{fmt}"
        path.write_bytes(data)
        info: dict = {"bytes": len(data), "path": str(path)}
        if fmt == "pdf":
            info["starts_with_pdf"] = data[:4] == b"%PDF"
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(data))
                text = "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as exc:  # noqa: BLE001
                text = data.decode("latin-1", errors="ignore")
                info["pdf_extract_error"] = str(exc)
            (OUT / f"{prefix}_report_pdf.txt").write_text(text, encoding="utf-8")
            folded = text.casefold()
            info["has_project_label"] = project.casefold() in folded
            info["has_bom_label"] = bom_name.casefold() in folded
            info["has_expected_mpn"] = any(mpn.casefold() in folded for mpn in expected_mpns)
            info["ok"] = (
                info["starts_with_pdf"]
                and info["has_project_label"]
                and info["has_bom_label"]
                and info["has_expected_mpn"]
            )
        elif fmt == "csv":
            rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
            info["row_count"] = len(rows)
            info["header"] = rows[0] if rows else []
            blob = "\n".join(",".join(row) for row in rows).casefold()
            info["has_mpn_column"] = any("mpn" in str(cell).casefold() for cell in (rows[0] if rows else []))
            info["has_project_label"] = project.casefold() in blob
            info["has_bom_label"] = bom_name.casefold() in blob
            info["has_expected_mpn"] = any(mpn.casefold() in blob for mpn in expected_mpns)
            info["data_rows"] = max(0, len(rows) - 1)
            info["ok"] = (
                info["has_mpn_column"]
                and info["data_rows"] >= min_parts
                and info["has_project_label"]
                and info["has_bom_label"]
                and info["has_expected_mpn"]
            )
        elif fmt == "xlsx":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
            info["is_zip"] = True
            info["has_workbook"] = "xl/workbook.xml" in names
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            info["sheets"] = list(wb.sheetnames)
            texts: list[str] = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                for row in ws.iter_rows(values_only=True):
                    texts.append(" ".join("" if cell is None else str(cell) for cell in row))
            blob = "\n".join(texts).casefold()
            info["has_project_label"] = project.casefold() in blob
            info["has_bom_label"] = bom_name.casefold() in blob
            info["has_expected_mpn"] = any(mpn.casefold() in blob for mpn in expected_mpns)
            info["ok"] = (
                info["has_workbook"]
                and "Summary" in info["sheets"]
                and "Components" in info["sheets"]
                and info["has_project_label"]
                and info["has_bom_label"]
                and info["has_expected_mpn"]
            )
        results[fmt] = info
    return results


def _run_bom(page: Page, cfg: dict) -> dict:
    label = cfg["label"]
    report: dict = {
        "bom": label,
        "file": str(cfg["path"]),
        "project": cfg["project"],
        "bom_name": cfg["bom_name"],
        "steps": {},
        "failed_step": None,
    }
    decision_post_bodies: list[dict] = []

    def _on_request(request) -> None:
        if request.method != "POST" or "/decision-records" not in request.url:
            return
        try:
            payload = request.post_data_json
        except Exception:  # noqa: BLE001
            raw = request.post_data or ""
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:  # noqa: BLE001
                payload = {"_raw": raw[:500]}
        if isinstance(payload, dict):
            decision_post_bodies.append(payload)

    page.on("request", _on_request)

    try:
        page.goto(f"{WEB}/bom-analyzer", wait_until="networkidle", timeout=60000)
        page.wait_for_selector('input[type="file"]', timeout=30000)
        _fill_labeled_input(page, "Project", cfg["project"])
        _fill_labeled_input(page, "BOM name", cfg["bom_name"])
        _fill_labeled_input(page, "Revision", cfg["revision"])
        page.set_input_files('input[type="file"]', str(cfg["path"]))
        page.wait_for_timeout(2500)
        page.get_by_text(re.compile(r"Ready to Analyze", re.I)).first.wait_for(timeout=60000)
        analyze = page.get_by_role("button", name=re.compile(r"^Analyze BOM$|Retry analysis", re.I))
        if analyze.count() == 0:
            analyze = page.locator("button").filter(has_text=re.compile(r"Analyze BOM", re.I))
        analyze.first.click(timeout=30000)
        open_review = page.get_by_role("link", name=re.compile(r"Open risk review", re.I))
        open_review.first.wait_for(timeout=180000)
        href = open_review.first.get_attribute("href") or ""
        match = re.search(r"analysis_id=([^&]+)", href)
        if match:
            analysis_id = match.group(1)
        else:
            stored = page.evaluate(
                """() => {
                  for (const key of Object.keys(localStorage)) {
                    if (key.includes('cadivor_next_last_analysis')) {
                      try { return JSON.parse(localStorage.getItem(key) || '{}'); }
                      catch (e) { return null; }
                    }
                  }
                  return null;
                }"""
            )
            analysis_id = str((stored or {}).get("analysis_id") or "")
        if not analysis_id:
            raise RuntimeError("Analyze finished but analysis_id was not found")
        report["analysis_id"] = analysis_id
        banner = page.locator("body").inner_text()
        report["steps"]["analyze"] = {
            "ok": cfg["project"] in banner or cfg["bom_name"] in banner,
            "url": page.url,
            "review_href": href,
            "banner_has_project": cfg["project"] in banner,
            "banner_has_bom": cfg["bom_name"] in banner,
        }
        page.screenshot(path=str(OUT / f"{label}_bom_analyzer.png"), full_page=True)
        open_review.first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / f"{label}_risk_review.png"), full_page=True)

        # Compare Parts — actually run a comparison.
        page.goto(
            f"{WEB}/compare-parts?analysis_id={analysis_id}",
            wait_until="networkidle",
            timeout=60000,
        )
        page.locator("#part-a").fill(cfg["part_a"])
        page.locator("#part-b").fill(cfg["part_b"])
        page.get_by_role("button", name=re.compile(r"^Compare parts$", re.I)).click()
        page.get_by_text(re.compile(r"No compatibility conclusion|Compatible|difference|Needs verification|Material", re.I)).first.wait_for(
            timeout=180000
        )
        compare_body = page.locator("body").inner_text()
        finding_el = page.locator(".cv-compare-screening, [role='status']").first
        finding_text = finding_el.inner_text() if finding_el.count() else compare_body[:400]
        compare_ok = (
            cfg["part_a"].casefold() in compare_body.casefold()
            and cfg["part_b"].casefold() in compare_body.casefold()
            and ("Attribute" in compare_body or "finding" in compare_body.casefold() or "evidence" in compare_body.casefold())
        )
        report["steps"]["compare"] = {
            "ok": compare_ok,
            "url": page.url,
            "part_a": cfg["part_a"],
            "part_b": cfg["part_b"],
            "finding_snippet": finding_text[:400],
        }
        page.screenshot(path=str(OUT / f"{label}_compare.png"), full_page=True)

        # Record decision with on-screen snapshot reuse (snapshot trust).
        page.get_by_role("button", name=re.compile(r"Record a decision", re.I)).click()
        page.get_by_role("dialog").wait_for(timeout=15000)
        dialog = page.get_by_role("dialog")
        dialog.locator("label.cv-field").filter(has_text=re.compile(r"^Decision|Decision", re.I)).locator(
            "select"
        ).first.select_option("hold_for_review")
        dialog.locator("label.cv-field").filter(has_text=re.compile(r"Reviewer", re.I)).locator("input").fill(
            f"Smoke Reviewer {label}"
        )
        dialog.locator("textarea").fill(
            f"PR597 smoke decision for {cfg['project']} / {cfg['bom_name']}: "
            f"compared {cfg['part_a']} vs {cfg['part_b']} and held for review."
        )
        dialog.get_by_role("button", name=re.compile(r"Save decision|Record decision|^Save$", re.I)).click()
        page.get_by_text(re.compile(r"Decision recorded", re.I)).first.wait_for(timeout=120000)
        success = page.get_by_text(re.compile(r"Decision recorded", re.I)).first.inner_text()
        snapshot_posted = False
        snapshot_parts_match = False
        for body in decision_post_bodies:
            snap = body.get("comparison_snapshot")
            if isinstance(snap, dict) and snap:
                snapshot_posted = True
                snapshot_parts_match = (
                    str(snap.get("part_a") or "").strip().casefold() == cfg["part_a"].casefold()
                    and str(snap.get("part_b") or "").strip().casefold() == cfg["part_b"].casefold()
                )
                break
        report["steps"]["decision_save"] = {
            "ok": "Decision recorded" in success and snapshot_posted and snapshot_parts_match,
            "success_text": success,
            "snapshot_posted": snapshot_posted,
            "snapshot_parts_match": snapshot_parts_match,
            "post_count": len(decision_post_bodies),
        }
        page.screenshot(path=str(OUT / f"{label}_decision.png"), full_page=True)

        # Engineering Decisions page should show the saved record + snapshot.
        page.goto(
            f"{WEB}/engineering-decisions?analysis_id={analysis_id}",
            wait_until="networkidle",
            timeout=60000,
        )
        page.wait_for_timeout(2000)
        decisions_body = page.locator("body").inner_text()
        report["steps"]["decision"] = {
            "ok": (
                cfg["part_a"] in decisions_body
                and cfg["part_b"] in decisions_body
                and ("Hold for review" in decisions_body or "hold for review" in decisions_body.casefold())
            ),
            "url": page.url,
            "snippet": decisions_body[:500],
        }

        # Replacement — still exercise, but not the primary gate.
        page.goto(
            f"{WEB}/find-replacement?analysis_id={analysis_id}&mpn={cfg['part_a']}",
            wait_until="networkidle",
            timeout=60000,
        )
        if page.locator("#replacement-mpn").count():
            page.locator("#replacement-mpn").fill(cfg["part_a"])
            page.get_by_role("button", name=re.compile(r"find candidates|search", re.I)).click()
            page.wait_for_timeout(4000)
        repl = page.locator("body").inner_text()
        report["steps"]["replacement"] = {
            "ok": any(
                marker in repl
                for marker in (
                    "Relevant candidates",
                    "Unclassified leads",
                    "Unfiltered leads",
                    "Unable to confirm",
                )
            ),
            "url": page.url,
            "has_unclassified_section": "Unclassified leads" in repl,
            "snippet": repl[:400],
        }
        page.screenshot(path=str(OUT / f"{label}_replacement.png"), full_page=True)

        # Reports page data.
        page.goto(f"{WEB}/reports/{analysis_id}", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)
        reports_body = page.locator("body").inner_text()
        report["steps"]["reports"] = {
            "ok": (
                analysis_id in page.url
                and (cfg["project"] in reports_body or cfg["bom_name"] in reports_body)
                and any(mpn in reports_body for mpn in cfg["expected_mpns"])
                and bool(re.search(r"pdf|csv|xlsx|download|export", reports_body, re.I))
            ),
            "url": page.url,
            "has_project_or_bom_label": cfg["project"] in reports_body or cfg["bom_name"] in reports_body,
            "has_expected_mpn": any(mpn in reports_body for mpn in cfg["expected_mpns"]),
            "snippet": reports_body[:500],
        }
        page.screenshot(path=str(OUT / f"{label}_reports.png"), full_page=True)

        # Procurement data for last analysis.
        page.goto(f"{WEB}/procurement", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2500)
        proc_body = page.locator("body").inner_text()
        report["steps"]["procurement"] = {
            "ok": (
                "Supplier evidence" in proc_body or "procurement" in proc_body.casefold()
            )
            and any(mpn in proc_body for mpn in cfg["expected_mpns"])
            and ("synthetic" in proc_body.casefold() or "Live:" in proc_body),
            "url": page.url,
            "has_expected_mpn": any(mpn in proc_body for mpn in cfg["expected_mpns"]),
            "snippet": proc_body[:500],
        }
        page.screenshot(path=str(OUT / f"{label}_procurement.png"), full_page=True)

        # Design Impact data for last analysis / focus MPN.
        page.goto(f"{WEB}/design-impact", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)
        focus = cfg["expected_mpns"][0]
        if page.locator("#mpn").count():
            page.locator("#mpn").fill(focus)
            page.get_by_role("button", name=re.compile(r"Refresh impact", re.I)).click()
            page.wait_for_timeout(3000)
        di_body = page.locator("body").inner_text()
        report["steps"]["design_impact"] = {
            "ok": (
                "Component catalog" in di_body
                and any(mpn in di_body for mpn in cfg["expected_mpns"])
                and ("Affected BOM" in di_body or "impact" in di_body.casefold())
            ),
            "url": page.url,
            "focus_mpn": focus,
            "has_expected_mpn": any(mpn in di_body for mpn in cfg["expected_mpns"]),
            "snippet": di_body[:500],
        }
        page.screenshot(path=str(OUT / f"{label}_design_impact.png"), full_page=True)

        token = _session_token(page)
        # API confirmation that the decision snapshot was persisted.
        decisions = _api_json("GET", f"/decision-records?analysis_id={analysis_id}", token)
        records = decisions.get("records") if isinstance(decisions, dict) else []
        matching = [
            row
            for row in (records or [])
            if isinstance(row, dict)
            and str(row.get("part_a") or "").casefold() == cfg["part_a"].casefold()
            and str(row.get("part_b") or "").casefold() == cfg["part_b"].casefold()
        ]
        snap = (matching[0].get("comparison_snapshot") if matching else {}) or {}
        report["steps"]["decision_snapshot_api"] = {
            "ok": bool(matching)
            and isinstance(snap, dict)
            and bool(snap.get("finding") or snap.get("rows") or snap.get("counts")),
            "record_count": len(matching),
            "has_finding": bool(snap.get("finding")),
            "has_rows": bool(snap.get("rows")),
            "has_counts": bool(snap.get("counts")),
            "decision_label": matching[0].get("decision_label") if matching else None,
        }

        report["exports"] = _inspect_exports(
            label,
            analysis_id,
            token,
            project=cfg["project"],
            bom_name=cfg["bom_name"],
            expected_mpns=cfg["expected_mpns"],
            min_parts=cfg["min_parts"],
        )
        report["steps"]["exports"] = {
            "ok": all(report["exports"][fmt].get("ok") for fmt in ("pdf", "xlsx", "csv")),
            "detail": {
                fmt: {
                    key: value
                    for key, value in info.items()
                    if key != "header"
                }
                for fmt, info in report["exports"].items()
            },
        }
    except Exception as exc:  # noqa: BLE001 — collect evidence, don't hide failures
        report["failed_step"] = str(exc)
        report["ok"] = False
        try:
            page.screenshot(path=str(OUT / f"{label}_failure.png"), full_page=True)
        except Exception:
            pass
        try:
            page.remove_listener("request", _on_request)
        except Exception:
            pass
        return report

    try:
        page.remove_listener("request", _on_request)
    except Exception:
        pass

    failed = [
        name
        for name, step in report["steps"].items()
        if isinstance(step, dict) and not step.get("ok")
    ]
    report["failed_steps"] = failed
    report["ok"] = not failed and not report.get("failed_step")
    return report


def main() -> int:
    results = {"web": WEB, "api": API, "boms": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 1100},
        )
        page = context.new_page()
        page.goto(f"{WEB}/login", wait_until="networkidle")
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name=re.compile(r"continue|sign in", re.I)).click()
        page.wait_for_function(
            "() => !window.location.pathname.includes('/login')",
            timeout=60000,
        )
        page.wait_for_timeout(1500)
        results["signed_in_url"] = page.url
        page.screenshot(path=str(OUT / "signed_in_home.png"), full_page=True)

        for cfg in BOMS:
            results["boms"].append(_run_bom(page, cfg))

        browser.close()

    results["ok"] = all(row.get("ok") for row in results["boms"])
    # Distinct-label cross-check across both BOM runs.
    labels = {(row.get("project"), row.get("bom_name")) for row in results["boms"]}
    results["distinct_labels"] = len(labels) == len(results["boms"])
    if not results["distinct_labels"]:
        results["ok"] = False

    out_path = OUT / "report.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    md = OUT / "REPORT.md"
    lines = [
        "# Next.js UI two-BOM smoke (PR #597 follow-up)",
        "",
        f"- Web: `{WEB}`",
        f"- API: `{API}`",
        f"- Overall: `{'PASS' if results['ok'] else 'FAIL'}`",
        f"- Distinct project/BOM labels: `{results['distinct_labels']}`",
        "",
    ]
    for row in results["boms"]:
        lines.append(f"## {row['bom']}")
        lines.append(f"- ok: `{row.get('ok')}`")
        lines.append(f"- analysis_id: `{row.get('analysis_id')}`")
        lines.append(f"- project: `{row.get('project')}`")
        lines.append(f"- bom_name: `{row.get('bom_name')}`")
        if row.get("failed_step"):
            lines.append(f"- exception: `{row['failed_step']}`")
        if row.get("failed_steps"):
            lines.append(f"- failed_steps: `{', '.join(row['failed_steps'])}`")
        for name, step in (row.get("steps") or {}).items():
            if isinstance(step, dict):
                lines.append(
                    f"- {name}: `{'ok' if step.get('ok') else 'FAIL'}`"
                    + (f" — {step.get('url')}" if step.get("url") else "")
                )
        lines.append("")
    lines.extend(
        [
            "## Checks covered",
            "- Analyze with distinct project/BOM/revision labels",
            "- Compare Parts performed for a real part pair",
            "- Decision saved with comparison_snapshot reuse (snapshot trust)",
            "- Engineering Decisions shows the saved pair + Hold for review",
            "- Reports / Procurement / Design Impact show BOM-linked data",
            "- PDF / XLSX / CSV contents include distinct labels and expected MPNs",
            "",
        ]
    )
    md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"ok": results["ok"], "report": str(out_path), "md": str(md)}, indent=2))
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
