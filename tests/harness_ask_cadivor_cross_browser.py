#!/usr/bin/env python3
"""Cross-browser Ask Cadivor layout harness — Sprint 72.3.4.

Renders the zero-credit native Streamlit preview in Chromium, Firefox, and WebKit
via Playwright. Compares structural presence, not pixel-perfect screenshots.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PREVIEW = REPO_ROOT / "tests/manual_ask_cadivor_native_preview.py"
PORT = int(os.environ.get("ASK_CADIVOR_CROSS_BROWSER_PORT", "8767"))

BROWSERS = ("chromium", "firefox", "webkit")

LAYOUT_PROBE = """
() => {
  const q = (sel) => document.querySelector(sel);
  const count = (sel) => document.querySelectorAll(sel).length;
  const text = document.body.innerText || "";
  const styleLoaded = Boolean(document.getElementById("cadivor-ask-cadivor-v2-css"));
  const leftCol = count('[data-testid="column"]') >= 2 || count('.stColumn') >= 2;
  const cards = {
    exchange: count(".cv50-exchange"),
    reasonRows: count(".cv722-reason-row"),
    actionRows: count(".cv722-action-row"),
    summaryCells: count(".cv722-summary-item"),
    impactCells: count(".cv724-impact-cell"),
    driverCells: count(".cv724-driver-cell"),
    evidenceCards: count(".cv46-evidence-card"),
  };
  const overflowNodes = Array.from(document.querySelectorAll(".cv722-concise-answer, .cv727-assessment-panel, .cv50-exchange"))
    .filter((el) => el.scrollWidth > el.clientWidth + 2);
  const rawHtmlVisible = /<article class="cv46-evidence-card"/.test(text)
    || /<div class="cv722-reason-row"/.test(text);
  const missingStyles = cards.exchange > 0 && !styleLoaded;
  const sample = q(".cv722-reason-row") || q(".cv50-exchange");
  let display = "";
  if (sample) {
    display = getComputedStyle(sample).display;
  }
  return {
    styleLoaded,
    leftCol,
    cards,
    overflowCount: overflowNodes.length,
    rawHtmlVisible,
    missingStyles,
    sampleDisplay: display,
    hasDirectAnswer: text.includes("Review PC817 first."),
    hasQuestion: text.includes("What should I review first in this BOM?"),
  };
}
"""


def _wait_for_server(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{PORT}/"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError(f"Streamlit did not start on port {PORT}")


def _start_streamlit() -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["STREAMLIT_SERVER_HEADLESS"] = "true"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(PREVIEW),
        "--server.headless",
        "true",
        "--server.port",
        str(PORT),
        "--browser.gatherUsageStats",
        "false",
    ]
    return subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _probe_browser(browser_name: str) -> dict:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        if browser_name == "chromium":
            browser = playwright.chromium.launch(headless=True)
        elif browser_name == "firefox":
            browser = playwright.firefox.launch(headless=True)
        elif browser_name == "webkit":
            browser = playwright.webkit.launch(headless=True)
        else:
            raise ValueError(browser_name)

        page = browser.new_page(viewport={"width": 1440, "height": 2200})
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(2500)
        result = page.evaluate(LAYOUT_PROBE)
        browser.close()
        return result


def _evaluate(result: dict) -> tuple[bool, list[str]]:
    issues: list[str] = []
    cards = result.get("cards") or {}
    if not result.get("styleLoaded"):
        issues.append("Ask Cadivor v2 stylesheet missing")
    if not result.get("leftCol"):
        issues.append("Expected two Streamlit columns")
    if cards.get("exchange", 0) < 1:
        issues.append("Conversation exchange missing")
    if cards.get("reasonRows", 0) < 3:
        issues.append("Fewer than 3 reason rows")
    if cards.get("actionRows", 0) < 3:
        issues.append("Fewer than 3 action rows")
    if cards.get("summaryCells", 0) < 3:
        issues.append("Fewer than 3 summary cells")
    if cards.get("impactCells", 0) < 4:
        issues.append("Fewer than 4 impact cells")
    if cards.get("driverCells", 0) < 1:
        issues.append("No confidence driver cards")
    if cards.get("evidenceCards", 0) < 3:
        issues.append("Fewer than 3 evidence cards")
    if result.get("rawHtmlVisible"):
        issues.append("Raw HTML tags visible in page text")
    if result.get("missingStyles"):
        issues.append("Cards present but stylesheet absent")
    if result.get("overflowCount", 0) > 0:
        issues.append(f"{result['overflowCount']} core surface(s) overflow horizontally")
    display = str(result.get("sampleDisplay") or "")
    if display and display not in {"grid", "flex", "block", "list-item"}:
        issues.append(f"Unexpected sample display: {display}")
    if not result.get("hasDirectAnswer"):
        issues.append("Direct answer text missing")
    if not result.get("hasQuestion"):
        issues.append("Question text missing")
    return not issues, issues


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("SKIP: playwright not installed (pip install playwright && playwright install)")
        return 0

    proc = _start_streamlit()
    exit_code = 0
    print("=== Ask Cadivor cross-browser layout harness (Sprint 72.3.4) ===")
    print(f"Preview: {PREVIEW.name} on port {PORT}")
    print("Zero OpenAI credits — static PC817 renderer only")
    print()
    try:
        _wait_for_server()
        results: dict[str, dict] = {}
        for browser_name in BROWSERS:
            try:
                payload = _probe_browser(browser_name)
                ok, issues = _evaluate(payload)
                results[browser_name] = {"ok": ok, "issues": issues, "payload": payload}
                status = "PASS" if ok else "FAIL"
                print(f"[{status}] {browser_name}")
                if issues:
                    for issue in issues:
                        print(f"       - {issue}")
                else:
                    print(
                        f"       cards={json.dumps(payload.get('cards', {}), sort_keys=True)} "
                        f"display={payload.get('sampleDisplay')}"
                    )
                exit_code = exit_code or (0 if ok else 1)
            except Exception as exc:  # pragma: no cover - harness diagnostic
                print(f"[FAIL] {browser_name}: {exc}")
                results[browser_name] = {"ok": False, "issues": [str(exc)], "payload": {}}
                exit_code = 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if exit_code == 0:
        print("Cross-browser harness: PASS")
    else:
        print("Cross-browser harness: FAILED")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
