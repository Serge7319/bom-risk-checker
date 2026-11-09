#!/usr/bin/env python3
"""Drive both synthetic BOMs through the local Next.js UI (not API-only).

Requires:
  - API on http://127.0.0.1:8081 (sandbox JWT + synthetic-preview)
  - Next on http://127.0.0.1:3001 with NEXT_PUBLIC_API_BASE pointing at that API
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".evidence_ui" / "next_ui_two_bom_597"
OUT.mkdir(parents=True, exist_ok=True)

WEB = "http://127.0.0.1:3001"
API = "http://127.0.0.1:8081"
EMAIL = "sandbox-a@cadivor.test"
PASSWORD = "CadivorSandbox!a"

BOMS = [
    ("flat", ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv"),
    ("nested", ROOT / "tests" / "fixtures" / "nested_bom_product.csv"),
]


def _inspect_exports(prefix: str, analysis_id: str, token: str) -> dict:
    import urllib.request

    results = {}
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
            text = data.decode("latin-1", errors="ignore")
            info["mentions_analysis"] = analysis_id[:8] in text or "Cadivor" in text
            info["page_markers"] = text.count("/Type /Page")
        elif fmt == "csv":
            rows = list(csv.reader(io.StringIO(data.decode("utf-8", errors="replace"))))
            info["row_count"] = len(rows)
            info["header"] = rows[0] if rows else []
            info["has_mpn_column"] = any(
                "mpn" in str(cell).casefold() for cell in (rows[0] if rows else [])
            )
        elif fmt == "xlsx":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
            info["is_zip"] = True
            info["has_workbook"] = "xl/workbook.xml" in names
            info["entry_count"] = len(names)
        results[fmt] = info
    return results


def _run_bom(page, label: str, bom_path: Path) -> dict:
    report: dict = {"bom": label, "file": str(bom_path), "steps": {}, "failed_step": None}
    try:
        page.goto(f"{WEB}/bom-analyzer", wait_until="networkidle", timeout=60000)
        page.wait_for_selector('input[type="file"]', timeout=30000)
        page.set_input_files('input[type="file"]', str(bom_path))
        page.wait_for_timeout(2500)
        # Wait until validation says Ready to Analyze.
        page.get_by_text(re.compile(r"Ready to Analyze", re.I)).first.wait_for(timeout=60000)
        analyze = page.get_by_role("button", name=re.compile(r"^Analyze BOM$|Retry analysis", re.I))
        if analyze.count() == 0:
            analyze = page.locator("button").filter(has_text=re.compile(r"Analyze BOM", re.I))
        analyze.first.click(timeout=30000)
        # Analysis completes in-place on /bom-analyzer (no auto-route to /reports).
        open_review = page.get_by_role("link", name=re.compile(r"Open risk review", re.I))
        open_review.first.wait_for(timeout=180000)
        href = open_review.first.get_attribute("href") or ""
        match = re.search(r"analysis_id=([^&]+)", href)
        if not match:
            # Fall back to localStorage last-analysis record.
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
        else:
            analysis_id = match.group(1)
        if not analysis_id:
            raise RuntimeError("Analyze finished but analysis_id was not found")
        report["analysis_id"] = analysis_id
        report["steps"]["analyze"] = {"ok": True, "url": page.url, "review_href": href}
        page.screenshot(path=str(OUT / f"{label}_bom_analyzer.png"), full_page=True)
        open_review.first.click()
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / f"{label}_risk_review.png"), full_page=True)

        # Compare Parts
        page.goto(f"{WEB}/compare-parts?analysis_id={analysis_id}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text()
        report["steps"]["compare"] = {
            "ok": "compare" in body.casefold() or "part" in body.casefold(),
            "url": page.url,
            "snippet": body[:240],
        }
        page.screenshot(path=str(OUT / f"{label}_compare.png"), full_page=True)

        # Find replacement — use a part from the BOM if present on report, else RES10K-like
        page.goto(f"{WEB}/find-replacement?analysis_id={analysis_id}", wait_until="networkidle")
        mpn_box = page.locator("#replacement-mpn")
        if mpn_box.count():
            # Prefer a known synthetic resistor when flat BOM; nested uses first available later.
            seed_mpn = "RC0603FR-0710KL" if label == "flat" else "LM358DR"
            mpn_box.fill(seed_mpn)
            page.get_by_role("button", name=re.compile(r"find candidates|search", re.I)).click()
            page.wait_for_timeout(4000)
        body = page.locator("body").inner_text()
        has_relevant = "Relevant candidates" in body
        has_unclassified = "Unclassified leads" in body
        has_unfiltered = "Unfiltered leads" in body
        report["steps"]["replacement"] = {
            "ok": has_relevant or "Unable to confirm" in body or has_unclassified or has_unfiltered,
            "url": page.url,
            "has_relevant_section": has_relevant,
            "has_unclassified_section": has_unclassified,
            "has_unfiltered_section": has_unfiltered,
            "snippet": body[:400],
        }
        page.screenshot(path=str(OUT / f"{label}_replacement.png"), full_page=True)

        # Engineering decisions
        page.goto(f"{WEB}/engineering-decisions", wait_until="networkidle")
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text()
        report["steps"]["decision"] = {
            "ok": "decision" in body.casefold() or analysis_id in body or "engineering" in body.casefold(),
            "url": page.url,
            "snippet": body[:240],
        }
        page.screenshot(path=str(OUT / f"{label}_decision.png"), full_page=True)

        # Reports / exports page
        page.goto(f"{WEB}/reports/{analysis_id}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        body = page.locator("body").inner_text()
        report["steps"]["reports"] = {
            "ok": analysis_id in page.url,
            "url": page.url,
            "has_download_controls": bool(
                re.search(r"pdf|csv|xlsx|download|export", body, re.I)
            ),
            "snippet": body[:240],
        }
        page.screenshot(path=str(OUT / f"{label}_reports.png"), full_page=True)

        # Procurement
        page.goto(f"{WEB}/procurement", wait_until="networkidle")
        page.wait_for_timeout(2000)
        body = page.locator("body").inner_text()
        report["steps"]["procurement"] = {
            "ok": "procurement" in body.casefold() or "supplier" in body.casefold(),
            "url": page.url,
            "snippet": body[:240],
        }
        page.screenshot(path=str(OUT / f"{label}_procurement.png"), full_page=True)

        # Design Impact
        page.goto(f"{WEB}/design-impact", wait_until="networkidle")
        page.wait_for_timeout(2000)
        body = page.locator("body").inner_text()
        report["steps"]["design_impact"] = {
            "ok": "design impact" in body.casefold() or "impact" in body.casefold(),
            "url": page.url,
            "snippet": body[:240],
        }
        page.screenshot(path=str(OUT / f"{label}_design_impact.png"), full_page=True)

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
        if not token:
            # Fallback: login via API for export inspection only (UI steps already exercised).
            import urllib.request

            req = urllib.request.Request(
                f"{API}/auth/login",
                data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                token = json.loads(resp.read().decode()).get("access_token") or ""
        report["exports"] = _inspect_exports(label, analysis_id, token)
        report["steps"]["exports"] = {
            "ok": all(
                report["exports"][fmt].get("bytes", 0) > 100 for fmt in ("pdf", "xlsx", "csv")
            )
            and report["exports"]["pdf"].get("starts_with_pdf")
            and report["exports"]["xlsx"].get("has_workbook")
            and report["exports"]["csv"].get("has_mpn_column"),
            "detail": report["exports"],
        }
    except Exception as exc:  # noqa: BLE001 — collect evidence, don't hide failures
        report["failed_step"] = str(exc)
        report["ok"] = False
        try:
            page.screenshot(path=str(OUT / f"{label}_failure.png"), full_page=True)
        except Exception:
            pass
        return report

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
        context = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 1100})
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

        for label, bom in BOMS:
            results["boms"].append(_run_bom(page, label, bom))

        browser.close()

    results["ok"] = all(row.get("ok") for row in results["boms"])
    out_path = OUT / "report.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    md = OUT / "REPORT.md"
    lines = [
        "# Next.js UI two-BOM smoke (PR #597 follow-up)",
        "",
        f"- Web: `{WEB}`",
        f"- API: `{API}`",
        f"- Overall: `{'PASS' if results['ok'] else 'FAIL'}`",
        "",
    ]
    for row in results["boms"]:
        lines.append(f"## {row['bom']}")
        lines.append(f"- ok: `{row.get('ok')}`")
        lines.append(f"- analysis_id: `{row.get('analysis_id')}`")
        if row.get("failed_step"):
            lines.append(f"- exception: `{row['failed_step']}`")
        if row.get("failed_steps"):
            lines.append(f"- failed_steps: `{', '.join(row['failed_steps'])}`")
        for name, step in (row.get("steps") or {}).items():
            if isinstance(step, dict):
                lines.append(f"- {name}: `{'ok' if step.get('ok') else 'FAIL'}` — {step.get('url', '')}")
        lines.append("")
    md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"ok": results["ok"], "report": str(out_path), "md": str(md)}, indent=2))
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
