"""Regression: cardTop ±8px and sidebar visible through 0/mid/4/saving/report."""
from __future__ import annotations

import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(
    __import__("os").environ.get(
        "CADIVOR_PERSIST_EVIDENCE_DIR",
        str(ROOT / ".evidence" / "progress_handoff" / "persist"),
    )
)
CSV = ROOT / ".evidence" / "fixtures" / "synthetic_bom_5parts.csv"
BASE = __import__("os").environ.get(
    "CADIVOR_PERSIST_BASE_URL", "http://127.0.0.1:8515/?page=BOM%20Analyzer"
)
MAX_DRIFT_PX = 8

MEASURE = """() => {
  const card = document.querySelector('.st-key-bom8_analysis_progress_card, .st-key-bom8_analysis_preparing_card');
  const main = document.querySelector('section[data-testid="stMain"]');
  const sidebar = document.querySelector(
    '.cv-foundation-sidebar, .cv-app-sidebar, [class*="foundation_navigation"], [class*="st-key-cv_foundation"], [data-testid="stSidebar"], section[data-testid="stSidebar"]'
  );
  const sidebarByChrome = (() => {
    // Foundation nav copies brand + BOM Analyzer into the left rail.
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
  const visible = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.height > 2 && r.width > 2;
  };
  const bodyText = document.body.innerText || '';
  const url = location.href || '';
  const onAnalysisDetails = url.includes('Analysis') && url.includes('Details');
  const hasReportCanvas = Boolean(document.querySelector('.st-key-approved_page_canvas_standard_analysis_detail'));
  const hasReportBody = (
      bodyText.includes('Engineering Intelligence')
      && (bodyText.includes('BOM Risk') || bodyText.includes('Review these components first'))
      && (bodyText.includes('Supplier evidence incomplete') || bodyText.includes('Risk coverage') || bodyText.includes('Needs review'))
    );
  const report = hasReportCanvas || (onAnalysisDetails && hasReportBody) || (!bodyText.includes('+ New BOM analysis') && hasReportBody);
  const text = card ? (card.innerText || '') : '';
  const m = text.match(/(\\d+)\\s+of\\s+(\\d+)/);
  const preparing = bodyText.includes('Preparing your BOM analysis');
  const saving = bodyText.includes('Saving the analysis');
  const kind = preparing ? 'preparing'
    : (saving ? 'saving'
    : (text.includes('Analyzing BOM') ? 'progress'
    : (report ? 'report' : 'other')));
  return {
    kind,
    hasCard: !!card,
    cardTop: card ? Math.round(card.getBoundingClientRect().top) : null,
    completed: m ? parseInt(m[1], 10) : null,
    total: m ? parseInt(m[2], 10) : null,
    sidebarVisible: visible(sidebar) || visible(sidebarByChrome),
    savingVisible: saving,
    reportVisible: report,
    text: (card ? text : bodyText).slice(0, 180),
  };
}"""


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    labeled: dict = {}
    samples = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1363, "height": 936})
        page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        # Prefer New BOM analysis; fall back to upload if already open
        if page.locator('button:has-text("New BOM analysis")').count():
            page.locator('button:has-text("New BOM analysis")').first.click()
            page.wait_for_timeout(1500)
        page.wait_for_selector('input[type="file"]', timeout=20000)
        inputs = page.locator(".stTextInput input")
        if inputs.count() >= 1:
            inputs.nth(0).fill("Persist QA")
        if inputs.count() >= 2:
            inputs.nth(1).fill("Synthetic 5-part")
        page.locator('input[type="file"]').first.set_input_files(str(CSV))
        page.wait_for_timeout(2500)
        labeled["upload_ready"] = {
            "analyze_enabled": page.locator('button:has-text("Analyze BOM")').count() > 0
        }
        page.screenshot(path=str(OUT / "00_upload_ready.png"), full_page=True)
        t0 = time.perf_counter()
        page.locator('button:has-text("Analyze BOM")').last.click(force=True)

        deadline = time.time() + 120
        last_sig = None
        while time.time() < deadline:
            page.wait_for_timeout(80)
            m = page.evaluate(MEASURE)
            elapsed = round((time.perf_counter() - t0) * 1000)
            sig = (m.get("kind"), m.get("completed"), m.get("cardTop"), m.get("sidebarVisible"), m.get("reportVisible"))
            if sig != last_sig:
                sample = {"t_ms": elapsed, "url": page.url, **m}
                samples.append(sample)
                print("SAMPLE", sample)
                last_sig = sig

            def snap(key: str, name: str) -> None:
                if key in labeled:
                    return
                labeled[key] = {"t_ms": elapsed, **m, "url": page.url}
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
                try:
                    page.locator('section[data-testid="stMain"]').screenshot(
                        path=str(OUT / f"{name}_main.png")
                    )
                except Exception:
                    pass

            if m.get("kind") == "progress" and m.get("completed") == 0:
                snap("progress_0", "01_progress_0")
            if m.get("kind") == "progress" and m.get("completed") in (2, 3):
                snap("progress_mid", "02_progress_mid")
            if m.get("kind") == "progress" and m.get("completed") == 4:
                snap("progress_4", "03_progress_4")
            if m.get("kind") == "saving":
                snap("saving", "04_saving")
            if "saving" in labeled and "Analysis" in page.url and "Details" in page.url and "report" not in labeled:
                page.wait_for_timeout(400)
                m = page.evaluate(MEASURE)
                elapsed = round((time.perf_counter() - t0) * 1000)
                if m.get("reportVisible"):
                    samples.append({"t_ms": elapsed, "url": page.url, **m, "settled": True})
                    print("SAMPLE", samples[-1])
                    snap("report", "05_report")
                    break
            if m.get("reportVisible"):
                page.wait_for_timeout(600)
                m = page.evaluate(MEASURE)
                elapsed = round((time.perf_counter() - t0) * 1000)
                samples.append({"t_ms": elapsed, "url": page.url, **m, "settled": True})
                print("SAMPLE", samples[-1])
                snap("report", "05_report")
                break

        points = []
        for key in ("progress_0", "progress_mid", "progress_4", "saving"):
            s = labeled.get(key) or {}
            if s.get("cardTop") is not None:
                points.append({"key": key, "cardTop": s["cardTop"], "sidebarVisible": s.get("sidebarVisible"), "t_ms": s.get("t_ms")})
        tops = [p["cardTop"] for p in points]
        stability = {
            "min": min(tops) if tops else None,
            "max": max(tops) if tops else None,
            "range": (max(tops) - min(tops)) if tops else None,
            "points": points,
        }
        report_ok = "report" in labeled and bool((labeled.get("report") or {}).get("reportVisible"))
        sidebar_ok = all(
            bool((labeled.get(k) or {}).get("sidebarVisible"))
            for k in ("progress_0", "progress_mid", "progress_4", "saving", "report")
            if k in labeled
        )
        # Report stage: sidebar must be visible; card may be gone
        if "report" in labeled:
            sidebar_ok = sidebar_ok and bool(labeled["report"].get("sidebarVisible"))

        defects = {
            "card_drift_gt_8px": bool(stability.get("range") is not None and stability["range"] > MAX_DRIFT_PX),
            "sidebar_missing_before_report": not sidebar_ok,
            "missing_stages": [k for k in ("progress_0", "progress_mid", "progress_4", "saving", "report") if k not in labeled],
            "saving_without_sidebar": bool(labeled.get("saving") and not labeled["saving"].get("sidebarVisible")),
            "report_without_sidebar": bool(labeled.get("report") and not labeled["report"].get("sidebarVisible")),
        }
        passed = (
            not defects["card_drift_gt_8px"]
            and not defects["sidebar_missing_before_report"]
            and not defects["missing_stages"]
            and report_ok
            and bool(stability.get("range") is not None and stability["range"] <= MAX_DRIFT_PX)
        )
        out = {
            "labeled": labeled,
            "samples": samples,
            "stability": stability,
            "defects": defects,
            "pass": passed,
            "max_drift_px": MAX_DRIFT_PX,
        }
        (OUT / "REPORT.json").write_text(json.dumps(out, indent=2))
        print(json.dumps({"keys": list(labeled.keys()), "stability": stability, "defects": defects, "pass": passed}, indent=2))
        browser.close()
        return out


if __name__ == "__main__":
    raise SystemExit(0 if main().get("pass") else 1)
