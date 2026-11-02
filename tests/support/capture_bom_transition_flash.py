"""E2E: New BOM open, CSV upload rerun, Analyze→Saving→report without blank flashes."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(
    os.environ.get(
        "CADIVOR_FLASH_EVIDENCE_DIR",
        str(ROOT / ".evidence" / "progress_handoff" / "flash_after"),
    )
)
CSV = ROOT / ".evidence" / "fixtures" / "synthetic_bom_5parts.csv"
BASE = os.environ.get(
    "CADIVOR_FLASH_BASE_URL", "http://127.0.0.1:8515/?page=BOM%20Analyzer"
)
MAX_DRIFT_PX = 8

MEASURE = r"""() => {
  const visible = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.height > 2 && r.width > 2;
  };
  const cardCandidates = Array.from(document.querySelectorAll(
    '.st-key-bom8_analysis_progress_card, .st-key-bom8_analysis_preparing_card'
  ));
  const card = cardCandidates.find(visible) || null;
  const sidebar = document.querySelector(
    '.cv-foundation-sidebar, [class*="st-key-cv_foundation_navigation"], [data-testid="stSidebar"]'
  );
  const sidebarByChrome = (() => {
    const nodes = Array.from(document.querySelectorAll('section, nav, div'));
    for (const el of nodes) {
      const t = el.innerText || '';
      if (!t.includes('ENGINEERING INTELLIGENCE') || !t.includes('BOM Analyzer')) continue;
      if (!t.includes('WORKSPACE') && !t.includes('Home')) continue;
      const r = el.getBoundingClientRect();
      if (r.left < 120 && r.width > 40 && r.height > 120) return el;
    }
    return null;
  })();
  const bodyText = document.body.innerText || '';
  const url = location.href || '';
  const opening = Boolean(document.querySelector(
    '.cv-main-transition.cv-route-loading, [data-cadivor-main-transition="1"]'
  ));
  const openingCover = document.querySelector(
    '.cv-main-transition.cv-route-loading[data-cadivor-transition-kind="navigation"], [data-cadivor-transition-kind="navigation"]'
  );
  let openingCoversSidebar = false;
  if (openingCover && visible(openingCover)) {
    const r = openingCover.getBoundingClientRect();
    openingCoversSidebar = r.left < 40;
  }
  const formVisible = Boolean(
    document.querySelector('.st-key-approved_bom_upload_form, .st-key-bom_file_uploader, input[type="file"]')
  ) && (bodyText.includes('New BOM analysis') || bodyText.includes('Upload your BOM'));
  const receiving = bodyText.includes('Receiving file');
  const emptyMain = (() => {
    const main = document.querySelector('section[data-testid="stMain"]');
    if (!main) return true;
    const r = main.getBoundingClientRect();
    const text = (main.innerText || '').replace(/\s+/g, ' ').trim();
    return text.length < 40 && r.height > 200;
  })();
  const sectionNav = Array.from(document.querySelectorAll(
    '[class*="st-key-cv_analysis_section_nav"]'
  )).find(visible);
  let sectionNavClippedRight = false;
  if (sectionNav) {
    const r = sectionNav.getBoundingClientRect();
    sectionNavClippedRight = r.left > (window.innerWidth * 0.55) || r.width < 120;
  }
  const onDetails = url.includes('Analysis') && url.includes('Details');
  const hasReportCanvas = Boolean(document.querySelector(
    '.st-key-approved_page_canvas_standard_analysis_detail, .cv-ei-report'
  ));
  const hasReportBody = (
    bodyText.includes('Engineering Intelligence')
    && (bodyText.includes('BOM Risk') || bodyText.includes('Review these components first')
        || bodyText.includes('Supplier evidence') || bodyText.includes('Risk coverage'))
  );
  const report = hasReportCanvas || (onDetails && hasReportBody);
  const text = card ? (card.innerText || '') : bodyText;
  const m = text.match(/(\d+)\s+of\s+(\d+)/);
  const preparing = Boolean(card) && bodyText.includes('Preparing your BOM analysis');
  const saving = Boolean(card) && text.includes('Saving the analysis');
  const kind = preparing ? 'preparing'
    : (saving ? 'saving'
    : ((card && text.includes('Analyzing BOM')) ? 'progress'
    : (report ? 'report'
    : (receiving ? 'receiving'
    : (formVisible ? 'form'
    : (opening ? 'opening' : 'other'))))));
  return {
    kind,
    hasCard: !!card,
    cardTop: card ? Math.round(card.getBoundingClientRect().top) : null,
    completed: m ? parseInt(m[1], 10) : null,
    total: m ? parseInt(m[2], 10) : null,
    sidebarVisible: visible(sidebar) || visible(sidebarByChrome),
    openingVisible: opening,
    openingCoversSidebar,
    formVisible,
    receivingVisible: receiving,
    emptyMain,
    sectionNavVisible: Boolean(sectionNav),
    sectionNavClippedRight,
    savingVisible: saving,
    reportVisible: report,
    analysisId: (url.match(/analysis_id=([^&]+)/) || [])[1] || null,
    text: text.slice(0, 220),
    url,
  };
}"""


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    labeled: dict = {}
    samples = []
    defects: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1363, "height": 936})
        page.goto(BASE, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(2500)

        # --- New BOM open: sidebar must stay; cover must not full-bleed over rail ---
        if page.locator('button:has-text("New BOM analysis")').count():
            page.locator('button:has-text("New BOM analysis")').first.click()
            for _ in range(25):
                page.wait_for_timeout(80)
                m = page.evaluate(MEASURE)
                samples.append({"phase": "new_bom", **m})
                if m.get("openingVisible") and "new_bom_opening" not in labeled:
                    labeled["new_bom_opening"] = m
                    page.screenshot(path=str(OUT / "01_new_bom_opening.png"), full_page=True)
                if m.get("formVisible") and not m.get("openingVisible"):
                    labeled["new_bom_form"] = m
                    page.screenshot(path=str(OUT / "02_new_bom_form.png"), full_page=True)
                    break
            else:
                labeled.setdefault("new_bom_form", page.evaluate(MEASURE))
        else:
            labeled["new_bom_form"] = page.evaluate(MEASURE)
            page.screenshot(path=str(OUT / "02_new_bom_form.png"), full_page=True)

        page.wait_for_selector('input[type="file"]', timeout=30000)
        inputs = page.locator(".stTextInput input")
        if inputs.count() >= 1:
            inputs.nth(0).fill("Flash QA")
        if inputs.count() >= 2:
            inputs.nth(1).fill("Synthetic 5-part flash")

        # --- CSV upload rerun: form or Receiving must stay; not empty+skeleton only ---
        page.locator('input[type="file"]').first.set_input_files(str(CSV))
        upload_flash_samples = []
        for _ in range(40):
            page.wait_for_timeout(100)
            m = page.evaluate(MEASURE)
            upload_flash_samples.append(m)
            samples.append({"phase": "upload_rerun", **m})
            if m.get("receivingVisible") and "upload_receiving" not in labeled:
                labeled["upload_receiving"] = m
                page.screenshot(path=str(OUT / "03_upload_receiving.png"), full_page=True)
            analyze = page.locator('button:has-text("Analyze BOM")')
            if analyze.count() and analyze.last.is_enabled():
                labeled["upload_ready"] = m
                page.screenshot(path=str(OUT / "04_upload_ready.png"), full_page=True)
                break
        else:
            labeled["upload_ready"] = page.evaluate(MEASURE)

        empty_upload_frames = [
            s for s in upload_flash_samples
            if s.get("emptyMain") and not s.get("formVisible") and not s.get("receivingVisible")
        ]
        defects["upload_empty_workspace_flash"] = len(empty_upload_frames) > 2

        t0 = time.perf_counter()
        page.locator('button:has-text("Analyze BOM")').last.click(force=True)

        deadline = time.time() + 140
        last_sig = None
        blank_handoff_frames = []
        while time.time() < deadline:
            page.wait_for_timeout(80)
            m = page.evaluate(MEASURE)
            elapsed = round((time.perf_counter() - t0) * 1000)
            sample = {"t_ms": elapsed, "phase": "analyze", **m}
            sig = (
                m.get("kind"),
                m.get("completed"),
                m.get("cardTop"),
                m.get("sidebarVisible"),
                m.get("reportVisible"),
                m.get("sectionNavClippedRight"),
            )
            if sig != last_sig:
                samples.append(sample)
                print("SAMPLE", sample)
                last_sig = sig

            def snap(key: str, name: str) -> None:
                if key in labeled:
                    return
                labeled[key] = {"t_ms": elapsed, **m}
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)

            if m.get("kind") == "progress" and m.get("completed") == 0:
                snap("progress_0", "05_progress_0")
            if m.get("kind") == "progress" and m.get("completed") in (2, 3):
                snap("progress_mid", "06_progress_mid")
            if m.get("kind") == "progress" and m.get("completed") == 4:
                snap("progress_4", "07_progress_4")
            if m.get("kind") == "saving":
                snap("saving", "08_saving")

            on_details = "Analysis" in page.url and "Details" in page.url
            if on_details and not m.get("reportVisible"):
                if m.get("emptyMain") or (
                    not m.get("hasCard") and m.get("sectionNavClippedRight")
                ):
                    blank_handoff_frames.append(sample)
                if m.get("hasCard") and m.get("savingVisible"):
                    snap("handoff_saving_on_details", "09_handoff_saving")

            if m.get("reportVisible"):
                page.wait_for_timeout(500)
                m = page.evaluate(MEASURE)
                elapsed = round((time.perf_counter() - t0) * 1000)
                labeled["report"] = {"t_ms": elapsed, **m}
                page.screenshot(path=str(OUT / "10_report.png"), full_page=True)
                samples.append({"t_ms": elapsed, "phase": "report", **m, "settled": True})
                print("SAMPLE", samples[-1])
                break

        points = []
        for key in ("progress_0", "progress_mid", "progress_4", "saving"):
            s = labeled.get(key) or {}
            if s.get("cardTop") is not None:
                points.append(
                    {
                        "key": key,
                        "cardTop": s["cardTop"],
                        "sidebarVisible": s.get("sidebarVisible"),
                        "t_ms": s.get("t_ms"),
                    }
                )
        tops = [p["cardTop"] for p in points]
        stability = {
            "min": min(tops) if tops else None,
            "max": max(tops) if tops else None,
            "range": (max(tops) - min(tops)) if tops else None,
            "points": points,
        }

        opening = labeled.get("new_bom_opening") or {}
        form = labeled.get("new_bom_form") or {}
        report = labeled.get("report") or {}
        defects.update(
            {
                "new_bom_cover_hides_sidebar": bool(
                    opening.get("openingCoversSidebar")
                    or (opening and not opening.get("sidebarVisible"))
                ),
                "new_bom_form_missing": not bool(form.get("formVisible")),
                "card_drift_gt_8px": bool(
                    stability.get("range") is not None and stability["range"] > MAX_DRIFT_PX
                ),
                "blank_report_handoff": len(blank_handoff_frames) > 3,
                "clipped_section_nav_during_handoff": any(
                    f.get("sectionNavClippedRight") for f in blank_handoff_frames
                ),
                "sidebar_missing_during_progress": any(
                    not bool((labeled.get(k) or {}).get("sidebarVisible"))
                    for k in ("progress_0", "progress_mid", "progress_4", "saving")
                    if k in labeled
                ),
                "report_without_sidebar": bool(report) and not report.get("sidebarVisible"),
                "missing_stages": [
                    k
                    for k in (
                        "new_bom_form",
                        "upload_ready",
                        "progress_0",
                        "progress_mid",
                        "progress_4",
                        "saving",
                        "report",
                    )
                    if k not in labeled
                ],
                "file_not_retained": not bool(
                    (labeled.get("upload_ready") or {}).get("formVisible")
                    or page.locator('button:has-text("Analyze BOM")').count()
                ),
            }
        )

        analysis_id = report.get("analysisId")
        passed = (
            not defects["new_bom_cover_hides_sidebar"]
            and not defects["new_bom_form_missing"]
            and not defects["upload_empty_workspace_flash"]
            and not defects["card_drift_gt_8px"]
            and not defects["blank_report_handoff"]
            and not defects["clipped_section_nav_during_handoff"]
            and not defects["sidebar_missing_during_progress"]
            and not defects["report_without_sidebar"]
            and not defects["missing_stages"]
            and bool(report.get("reportVisible"))
            and bool(analysis_id)
        )
        out = {
            "labeled": labeled,
            "samples": samples[-80:],
            "blank_handoff_frames": blank_handoff_frames[:20],
            "stability": stability,
            "defects": defects,
            "analysis_id": analysis_id,
            "pass": passed,
            "max_drift_px": MAX_DRIFT_PX,
            "head": os.environ.get("CADIVOR_FLASH_HEAD", ""),
        }
        (OUT / "REPORT.json").write_text(json.dumps(out, indent=2))
        print(
            json.dumps(
                {
                    "keys": list(labeled.keys()),
                    "stability": stability,
                    "defects": defects,
                    "analysis_id": analysis_id,
                    "pass": passed,
                },
                indent=2,
            )
        )
        browser.close()
        return out


if __name__ == "__main__":
    raise SystemExit(0 if main().get("pass") else 1)
