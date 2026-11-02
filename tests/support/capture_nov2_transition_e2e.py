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
CSV = Path(
    os.environ.get(
        "CADIVOR_NOV2_E2E_CSV",
        str(ROOT / "tests" / "fixtures" / "synthetic_bom_25parts.csv"),
    )
)
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
  const cardTop = card ? Math.round(card.getBoundingClientRect().top) : null;
  const cardText = (card && card.innerText) || '';
  const m = (cardText || bodyText).match(/(\d+)\s+of\s+(\d+)/);
  const opening = Boolean(document.querySelector(
    '.cv-main-transition.cv-route-loading:not([style*="display: none"])'
  ));
  const reportEl = document.querySelector('.cv-ei-report');
  const report = Boolean(reportEl && visible(reportEl))
    || (Boolean(reportEl)
        && bodyText.includes('Engineering Intelligence')
        && bodyText.includes('components'));
  const componentMatch = bodyText.match(/(\d+)\s+COMPONENTS/i)
    || bodyText.match(/(\d+)\s+components/i);
  const bg = getComputedStyle(document.body).backgroundColor || '';
  const loginVisible = Boolean(
    document.querySelector('input[type="password"]')
    && (bodyText.includes('Login') || bodyText.includes('Sign in') || bodyText.includes('Email'))
  );
  const readableSurface = Boolean(
    loginVisible
    || opening
    || Boolean(card)
    || report
    || /Cadivor|BOM|Dashboard|Engineering|Signing you in|Preparing your workspace|Opening /i.test(bodyText)
  );
  const blankWorkspace = !readableSurface || (
    !loginVisible && !opening && !card && !report
    && mainText.replace(/\s+/g, '').length < 8
  );
  const analysisDetailsUrl = /page=Analysis(\+|%20|\s)?Details/i.test(location.href);
  // Active Saving owns the Analyzer top slot (y≈38). Ignore scrolled leftover cards.
  const saving = Boolean(card)
    && /Saving the analysis/i.test(cardText)
    && cardTop !== null
    && cardTop < 160;
  const prematureDetailsSkeleton = analysisDetailsUrl && !report && saving;
  return {
    url: location.href,
    navRails: navHosts.length,
    navInFlow: navInFlow.length,
    sidebarVisible: navHosts.length > 0,
    openingVisible: opening,
    cardTop,
    completed: m ? parseInt(m[1], 10) : null,
    total: m ? parseInt(m[2], 10) : null,
    saving,
    report,
    componentCount: componentMatch ? parseInt(componentMatch[1], 10) : null,
    blankWorkspace,
    loginVisible,
    bodyBg: bg,
    analysisDetailsUrl,
    prematureDetailsSkeleton,
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
    env.setdefault("CADIVOR_SMOKE_PLAN", "Professional")
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
    progress_series: list[int] = []
    try:
        _wait_http(f"http://127.0.0.1:{PORT}/")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome",
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1363, "height": 936})
            # marketing → login (recording path): auth=login&source=marketing
            page.goto(
                f"http://127.0.0.1:{PORT}/?auth=login&source=marketing",
                wait_until="domcontentloaded",
                timeout=90000,
            )
            blank_login_frames = []
            login_form_ready = False
            for _ in range(40):
                page.wait_for_timeout(150)
                m = page.evaluate(MEASURE)
                samples.append({"phase": "marketing_login", **m})
                if m.get("blankWorkspace"):
                    blank_login_frames.append(m)
                    page.screenshot(
                        path=str(OUT / "00_blank_login_candidate.png"), full_page=True
                    )
                if m.get("loginVisible"):
                    labeled["marketing_login"] = m
                    page.screenshot(
                        path=str(OUT / "00_marketing_login.png"), full_page=True
                    )
                    login_form_ready = True
                    break
            defects["blank_workspace_on_login"] = bool(blank_login_frames) and not login_form_ready
            if not login_form_ready:
                page.wait_for_timeout(1500)
            page.locator('input[type="email"], input[type="text"]').first.fill(EMAIL)
            page.locator('input[type="password"]').first.fill(PASSWORD)
            page.locator('button:has-text("Login"), button:has-text("Sign in")').first.click()

            home_ready = False
            blank_dashboard_frames = []
            for i in range(120):
                page.wait_for_timeout(200)
                m = page.evaluate(MEASURE)
                samples.append({"phase": "login", **m})
                if m.get("blankWorkspace"):
                    blank_dashboard_frames.append(m)
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
            defects["blank_workspace_login_to_dashboard"] = bool(blank_dashboard_frames) and not (
                labeled.get("login_opening") or labeled.get("home")
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

            deadline = time.time() + 180
            nav_leak_frames = []
            premature_details_frames = []
            blank_handoff_frames = []
            while time.time() < deadline:
                page.wait_for_timeout(100)
                m = page.evaluate(MEASURE)
                samples.append({"phase": "analyze", **m})
                if isinstance(m.get("completed"), int):
                    if not progress_series or progress_series[-1] != m["completed"]:
                        progress_series.append(int(m["completed"]))
                if m.get("completed") == 0 and m.get("total"):
                    labeled.setdefault("progress_0", m)
                    page.screenshot(path=str(OUT / "04_progress_0.png"), full_page=True)
                total_parts = int((labeled.get("progress_0") or {}).get("total") or 0)
                if (
                    total_parts
                    and m.get("completed") == total_parts
                    and not m.get("saving")
                    and not m.get("analysisDetailsUrl")
                    and not m.get("report")
                    and m.get("cardTop") is not None
                    and int(m.get("cardTop") or 999) < 160
                ):
                    labeled.setdefault("progress_complete", m)
                    page.screenshot(
                        path=str(OUT / "05_progress_complete.png"), full_page=True
                    )
                if m.get("saving"):
                    labeled.setdefault("saving", m)
                    page.screenshot(path=str(OUT / "06_saving.png"), full_page=True)
                    if int(m.get("navInFlow") or 0) > 0 or int(m.get("navRails") or 0) > 1:
                        nav_leak_frames.append(m)
                    if "Opening Analysis Details" in (m.get("preview") or ""):
                        defects["opening_analysis_details_during_saving"] = True
                if m.get("prematureDetailsSkeleton"):
                    premature_details_frames.append(m)
                if (
                    m.get("analysisDetailsUrl")
                    and not m.get("report")
                    and not m.get("saving")
                    and m.get("blankWorkspace")
                ):
                    blank_handoff_frames.append(m)
                if m.get("report"):
                    labeled["report"] = m
                    page.screenshot(path=str(OUT / "07_report.png"), full_page=True)
                    break

            defects.setdefault("opening_analysis_details_during_saving", False)
            defects["nav_leak_during_saving"] = len(nav_leak_frames) > 0
            defects["premature_analysis_details_skeleton"] = len(premature_details_frames) > 0
            defects["blank_handoff"] = len(blank_handoff_frames) > 0
            defects["missing_progress_0"] = "progress_0" not in labeled
            defects["missing_saving"] = "saving" not in labeled
            defects["missing_report"] = "report" not in labeled
            defects["progress_not_monotonic"] = any(
                progress_series[i] > progress_series[i + 1]
                for i in range(max(0, len(progress_series) - 1))
            )
            expected_n = 25 if "25parts" in CSV.name else None
            defects["wrong_component_count"] = bool(labeled.get("report")) and (
                expected_n is not None
                and labeled["report"].get("componentCount") not in {expected_n, None}
                and labeled["report"].get("total") not in {expected_n, None}
            )
            report_url = str((labeled.get("report") or {}).get("url") or page.url)
            report_count = (labeled.get("report") or {}).get("componentCount")
            if "report" in labeled and "analysis_id=" in report_url:
                # Persist the smoke cookie in the real browser jar so a hard
                # navigation can rehydrate the same authenticated session.
                page.context.add_cookies(
                    [
                        {
                            "name": "cadivor_auth_gate_smoke",
                            "value": "1",
                            "url": f"http://127.0.0.1:{PORT}/",
                        }
                    ]
                )
                page.goto(report_url, wait_until="domcontentloaded", timeout=90000)
                reloaded = False
                for _ in range(120):
                    page.wait_for_timeout(200)
                    m = page.evaluate(MEASURE)
                    samples.append({"phase": "reload", **m})
                    if m.get("loginVisible"):
                        page.locator(
                            'input[type="email"], input[type="text"]'
                        ).first.fill(EMAIL)
                        page.locator('input[type="password"]').first.fill(PASSWORD)
                        page.locator(
                            'button:has-text("Login"), button:has-text("Sign in")'
                        ).first.click()
                        for _wait in range(60):
                            page.wait_for_timeout(200)
                            shell = page.evaluate(MEASURE)
                            samples.append({"phase": "reload_reauth", **shell})
                            if shell.get("sidebarVisible") or shell.get("report"):
                                break
                        page.goto(
                            report_url, wait_until="domcontentloaded", timeout=90000
                        )
                        continue
                    if m.get("report"):
                        labeled["report_reload"] = m
                        page.screenshot(
                            path=str(OUT / "08_report_reload.png"), full_page=True
                        )
                        reloaded = True
                        break
                defects["missing_report_reload"] = not reloaded
                defects["reload_component_mismatch"] = bool(reloaded) and (
                    labeled["report_reload"].get("componentCount")
                    not in {report_count, expected_n, None}
                )
                if reloaded:
                    first_id = report_url.split("analysis_id=", 1)[1].split("&", 1)[0]
                    reload_url = str(labeled["report_reload"].get("url") or "")
                    defects["reload_analysis_id_mismatch"] = (
                        f"analysis_id={first_id}" not in reload_url
                    )
                else:
                    defects["reload_analysis_id_mismatch"] = False
            else:
                defects["missing_report_reload"] = "report" in labeled
                defects["reload_component_mismatch"] = False
                defects["reload_analysis_id_mismatch"] = False

            # Progress tops: only Analyzer progress/saving cards (not Details leftovers).
            tops = [
                labeled[k]["cardTop"]
                for k in ("progress_0", "progress_complete", "saving")
                if k in labeled and labeled[k].get("cardTop") is not None
            ]
            # If progress_complete was never captured (fast 0→Saving), compare 0 vs Saving.
            if (
                "progress_complete" not in labeled
                and "progress_0" in labeled
                and "saving" in labeled
            ):
                tops = [
                    labeled["progress_0"]["cardTop"],
                    labeled["saving"]["cardTop"],
                ]
            defects["progress_not_top"] = bool(tops) and (
                (max(tops) - min(tops)) > 8 or min(tops) > 120
            )

            # Exactly one saved analysis in smoke store (from streamlit log phase markers).
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            saved_marks = [
                line
                for line in log_text.splitlines()
                if "CADIVOR_PHASE analysis_saved " in line
            ]
            defects["wrong_saved_analysis_count"] = len(saved_marks) != 1

            passed = not any(bool(v) for v in defects.values())
            out = {
                "pass": passed,
                "defects": defects,
                "labeled": labeled,
                "progress_series": progress_series,
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
