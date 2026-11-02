"""Synthetic login → New BOM → Analyze → Saving → EI (smoke adapter, no prod secrets)."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(
    os.environ.get(
        "CADIVOR_NOV2_E2E_DIR",
        str(ROOT / ".evidence" / "nov2_transition" / "after" / "local_e2e"),
    )
)
CSV = ROOT / ".evidence" / "fixtures" / "synthetic_bom_5parts.csv"
PORT = int(os.environ.get("CADIVOR_NOV2_E2E_PORT") or "8533")
SMOKE_PYTHONPATH = str(ROOT / "tests" / "smoke_pythonpath")
STREAMLIT_PY = str(ROOT / ".venv312" / "bin" / "python")
SMOKE_APP = str(ROOT / "streamlit_app.py")
EMAIL = "auth-smoke@cadivor.test"
PASSWORD = "cadivor-auth-smoke"

MEASURE = r"""() => {
  const visible = (el) => {
    if (!el) return false;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && r.height > 2 && r.width > 2;
  };
  const navHosts = Array.from(document.querySelectorAll(
    '[class*="st-key-cv_foundation_navigation"]'
  )).filter(visible);
  const navInFlow = navHosts.filter((el) => {
    const s = getComputedStyle(el);
    return s.position !== 'fixed' && s.position !== 'sticky';
  });
  const main = document.querySelector('section[data-testid="stMain"]');
  const mainText = (main && main.innerText) || '';
  const bodyText = document.body.innerText || '';
  const card = Array.from(document.querySelectorAll(
    '.st-key-bom8_analysis_progress_card, .st-key-bom8_analysis_preparing_card'
  )).find(visible) || null;
  const m = ((card && card.innerText) || bodyText).match(/(\d+)\s+of\s+(\d+)/);
  const opening = Boolean(document.querySelector(
    '.cv-main-transition.cv-route-loading:not([style*="display: none"])'
  ));
  const report = Boolean(document.querySelector('.cv-ei-report'))
    || (bodyText.includes('Engineering Intelligence')
        && (bodyText.includes('BOM Risk') || bodyText.includes('components')));
  const componentMatch = bodyText.match(/(\d+)\s+COMPONENTS/i)
    || bodyText.match(/(\d+)\s+components/i);
  return {
    url: location.href,
    navRails: navHosts.length,
    navInFlow: navInFlow.length,
    sidebarVisible: navHosts.length > 0,
    openingVisible: opening,
    cardTop: card ? Math.round(card.getBoundingClientRect().top) : null,
    completed: m ? parseInt(m[1], 10) : null,
    total: m ? parseInt(m[2], 10) : null,
    saving: Boolean(card) && /Saving the analysis/i.test((card && card.innerText) || ''),
    report,
    componentCount: componentMatch ? parseInt(componentMatch[1], 10) : null,
    preview: bodyText.replace(/\s+/g, ' ').trim().slice(0, 220),
  };
}"""


def _wait_http(url: str, timeout_s: float = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError(f"server not ready: {url}")


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = SMOKE_PYTHONPATH + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env.setdefault("SUPABASE_URL", "https://example.supabase.co")
    env.setdefault("SUPABASE_ANON_KEY", "public-anon-key-for-smoke")
    env.setdefault("SUPABASE_KEY", "public-anon-key-for-smoke")
    env["CADIVOR_SMOKE_IO_COUNTERS"] = str(OUT / "io_counters.json")
    log_path = OUT / "streamlit.log"
    log_fh = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            STREAMLIT_PY,
            "-m",
            "streamlit",
            "run",
            SMOKE_APP,
            "--server.port",
            str(PORT),
            "--server.address",
            "127.0.0.1",
            "--server.headless",
            "true",
            "--server.fileWatcherType",
            "none",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    samples = []
    defects: dict = {}
    labeled: dict = {}
    try:
        _wait_http(f"http://127.0.0.1:{PORT}/")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1363, "height": 936})
            page.goto(
                f"http://127.0.0.1:{PORT}/?auth=login",
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(1500)
            page.locator('input[type="email"], input[type="text"]').first.fill(EMAIL)
            page.locator('input[type="password"]').first.fill(PASSWORD)
            page.locator('button:has-text("Login"), button:has-text("Sign in")').first.click()

            home_ready = False
            for i in range(120):
                page.wait_for_timeout(200)
                m = page.evaluate(MEASURE)
                samples.append({"phase": "login", **m})
                if m.get("openingVisible") and "login_opening" not in labeled:
                    labeled["login_opening"] = m
                    page.screenshot(path=str(OUT / "01_login_opening.png"), full_page=True)
                if m.get("sidebarVisible") and (
                    "Start your first" in (m.get("preview") or "")
                    or "Good " in (m.get("preview") or "")
                    or "Upload a BOM" in (m.get("preview") or "")
                ):
                    labeled["home"] = m
                    page.screenshot(path=str(OUT / "02_home_with_rail.png"), full_page=True)
                    home_ready = True
                    break
            defects["login_missing_home_rail"] = not home_ready or not bool(
                (labeled.get("home") or {}).get("sidebarVisible")
            )
            defects["login_opening_without_rail"] = bool(labeled.get("login_opening")) and not bool(
                (labeled.get("login_opening") or {}).get("sidebarVisible")
            )

            if page.locator('button:has-text("New BOM analysis"), button:has-text("Upload a BOM")').count():
                page.locator(
                    'button:has-text("New BOM analysis"), button:has-text("Upload a BOM")'
                ).first.click()
            page.wait_for_selector('input[type="file"]', timeout=45000)
            labeled["new_bom"] = page.evaluate(MEASURE)
            page.screenshot(path=str(OUT / "03_new_bom.png"), full_page=True)
            defects["new_bom_missing_rail"] = not bool(labeled["new_bom"].get("sidebarVisible"))

            inputs = page.locator(".stTextInput input")
            if inputs.count() >= 1:
                inputs.nth(0).fill("NOV2 Transition Project")
            if inputs.count() >= 2:
                inputs.nth(1).fill("NOV2 Synthetic BOM")
            page.locator('input[type="file"]').first.set_input_files(str(CSV))
            for _ in range(50):
                page.wait_for_timeout(120)
                analyze = page.locator('button:has-text("Analyze BOM")')
                if analyze.count() and analyze.last.is_enabled():
                    break
            page.locator('button:has-text("Analyze BOM")').last.click(force=True)

            deadline = time.time() + 140
            nav_leak_frames = []
            while time.time() < deadline:
                page.wait_for_timeout(100)
                m = page.evaluate(MEASURE)
                samples.append({"phase": "analyze", **m})
                if m.get("completed") == 0 and m.get("total"):
                    labeled.setdefault("progress_0", m)
                    page.screenshot(path=str(OUT / "04_progress_0.png"), full_page=True)
                if m.get("completed") == 4:
                    labeled.setdefault("progress_4", m)
                    page.screenshot(path=str(OUT / "05_progress_4.png"), full_page=True)
                if m.get("saving"):
                    labeled.setdefault("saving", m)
                    page.screenshot(path=str(OUT / "06_saving.png"), full_page=True)
                    if int(m.get("navInFlow") or 0) > 0 or int(m.get("navRails") or 0) > 1:
                        nav_leak_frames.append(m)
                if m.get("report"):
                    labeled["report"] = m
                    page.screenshot(path=str(OUT / "07_report.png"), full_page=True)
                    break

            defects["nav_leak_during_saving"] = len(nav_leak_frames) > 0
            defects["missing_progress_0"] = "progress_0" not in labeled
            defects["missing_progress_4"] = "progress_4" not in labeled
            defects["missing_saving"] = "saving" not in labeled
            defects["missing_report"] = "report" not in labeled
            defects["wrong_component_count"] = bool(labeled.get("report")) and (
                (labeled["report"].get("componentCount") not in {4, 5, None})
                and (labeled["report"].get("total") not in {4, 5, None})
            )
            tops = [
                labeled[k]["cardTop"]
                for k in ("progress_0", "progress_4", "saving")
                if k in labeled and labeled[k].get("cardTop") is not None
            ]
            defects["progress_not_top"] = bool(tops) and min(tops) > 120

            passed = not any(defects.values())
            out = {
                "pass": passed,
                "defects": defects,
                "labeled": labeled,
                "nav_leak_frames": nav_leak_frames[:10],
                "samples_tail": samples[-40:],
                "sha": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
                ).strip(),
            }
            (OUT / "REPORT.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
            print(json.dumps({"pass": passed, "defects": defects, "keys": list(labeled)}, indent=2))
            browser.close()
            return out
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        log_fh.close()


if __name__ == "__main__":
    raise SystemExit(0 if main().get("pass") else 1)
