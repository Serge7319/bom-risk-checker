#!/usr/bin/env python3
"""Browser acceptance for trial, trial-expired, beta, and paid checkout states.

Does not call live Stripe. Checkout sessions are stubbed.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("CADIVOR_LIFECYCLE_UX_OUT") or str(ROOT / ".tmp_plan_lifecycle"))
PORT = int(os.environ.get("CADIVOR_LIFECYCLE_UX_PORT") or "8564")
STATE_FILE = OUT / "smoke_state.json"
MOCK_EMAIL = "auth-smoke@cadivor.test"
MOCK_PASSWORD = "cadivor-auth-smoke"
STREAMLIT_PY = str(ROOT / "venv" / "bin" / "python")
SMOKE_APP = str(ROOT / "streamlit_app.py")
SMOKE_PYTHONPATH = str(ROOT / "tests" / "billing_ux_smoke_pythonpath")
BROWSER = str(os.environ.get("CADIVOR_SMOKE_BROWSER") or "chromium").strip().lower()


def _future_trial() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()


def _past_trial() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


STATES = (
    {
        "id": "trial",
        "file": "01_trial.png",
        "overlay": {"plan": "Trial", "trial_ends_at": _future_trial()},
        "billing": "days remaining",
        "pricing": "Trial ·",
        "checkout": None,
    },
    {
        "id": "trial_expired",
        "file": "02_trial_expired.png",
        "overlay": {"plan": "Trial expired", "trial_ends_at": _past_trial()},
        "billing": "This trial has ended",
        "pricing": "Trial expired",
        "checkout": None,
    },
    {
        "id": "grandfathered_beta",
        "file": "03_grandfathered_beta.png",
        "overlay": {"plan": "Starter"},
        "billing": "grandfathered beta access",
        "pricing": "Beta access",
        "forbid": "Your active plan",
        "checkout": None,
    },
    {
        "id": "starter_checkout",
        "file": "04_starter_checkout_ready.png",
        "overlay": {"plan": "Trial", "trial_ends_at": _future_trial()},
        "billing": "days remaining",
        "pricing": "Upgrade to Starter",
        "checkout": "Starter",
        "forbid_annual": True,
    },
    {
        "id": "professional_checkout",
        "file": "05_professional_checkout_ready.png",
        "overlay": {"plan": "Trial", "trial_ends_at": _future_trial()},
        "billing": "days remaining",
        "pricing": "Upgrade to Professional",
        "checkout": "Professional",
        "forbid_annual": True,
    },
    {
        "id": "business_checkout",
        "file": "06_business_checkout_ready.png",
        "overlay": {"plan": "Trial", "trial_ends_at": _future_trial()},
        "billing": "days remaining",
        "pricing": "Upgrade to Business",
        "checkout": "Business",
        "forbid_annual": True,
    },
)


def _wait_settled(page, needle: str, *, timeout_s: float = 45.0, label: str) -> None:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        body = page.inner_text("body") or ""
        last = body[:400]
        if (
            needle in body
            and "Opening " not in body
            and "Preparing this page" not in body
            and "Loading workspace" not in body
            and "Loading saved BOMs" not in body
        ):
            page.wait_for_timeout(500)
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"{label}: page did not settle with {needle!r}; last={last!r}")


def _wait_text(page, needle: str, *, timeout_s: float = 45.0, label: str) -> None:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        body = page.inner_text("body") or ""
        last = body[:400]
        if needle in body:
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"{label}: missing {needle!r}; last={last!r}")


def _find_login_fields(page):
    for frame in [page, *page.frames]:
        email = frame.locator(
            'input[type="email"], input[autocomplete="email"], '
            'div[data-testid="stTextInput"] input'
        ).first
        password = frame.locator('input[type="password"]').first
        try:
            if email.count() and password.count():
                return frame, email, password
        except Exception:
            continue
    return None, None, None


def _login(page) -> None:
    for _ in range(90):
        target, email, password = _find_login_fields(page)
        body = page.inner_text("body") or ""
        if target is not None and ("Login" in body or "Sign in" in body or "Email" in body):
            email.fill(MOCK_EMAIL)
            password.fill(MOCK_PASSWORD)
            target.locator(
                'button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]'
            ).first.click(timeout=8000)
            _wait_text(page, "Dashboard", timeout_s=90.0, label="post_login")
            return
        page.wait_for_timeout(400)
    raise AssertionError("login fields never appeared")


def _open_pricing(page) -> None:
    page.locator('[class*="st-key-cv_foundation_navigation"] button:has-text("Settings")').first.click(timeout=8000)
    _wait_text(page, "Profile", timeout_s=40.0, label="settings")
    page.locator(".st-key-cv_settings_nav button:has-text('Billing')").click(timeout=8000)
    _wait_text(page, "Plan & billing", timeout_s=30.0, label="billing_tab")
    page.locator('[data-cadivor-nav-key="settings_view_plans"]').click(timeout=8000)
    _wait_text(page, "Cadivor plans", timeout_s=45.0, label="pricing")


def _assert_single_checkout(page, plan_name: str) -> None:
    page.locator(f"button:has-text('Upgrade to {plan_name}')").first.click(timeout=8000)
    deadline = time.monotonic() + 20
    last = {}
    while time.monotonic() < deadline:
        last = page.evaluate(
            """() => {
              const visible = (el) => {
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 8 && r.height > 8;
              };
              const nodes = Array.from(document.querySelectorAll('a, button')).filter((el) => {
                return visible(el) && (el.innerText || '').includes('Continue to secure checkout');
              });
              return {
                count: nodes.length,
                items: nodes.map((el) => {
                  const cs = getComputedStyle(el);
                  return {
                    tag: el.tagName,
                    text: (el.innerText || '').trim(),
                    bg: cs.backgroundColor,
                    width: el.getBoundingClientRect().width,
                    inCard: !!el.closest('[class*="st-key-cv311_checkout_"]'),
                  };
                }),
              };
            }"""
        )
        items = last.get("items") or []
        if last.get("count") == 1 and items and items[0]["bg"] == "rgb(37, 99, 235)" and items[0]["inCard"]:
            anchors = page.locator("a").filter(has_text="Continue to secure checkout")
            if anchors.count() != 1:
                raise AssertionError(f"expected one checkout anchor, saw {anchors.count()}")
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"{plan_name} checkout not a single primary button: {last}")


def _start_streamlit() -> subprocess.Popen:
    try:
        listed = subprocess.check_output(
            ["lsof", "-tiTCP:%d" % PORT, "-sTCP:LISTEN"], text=True
        ).strip()
        for pid_s in listed.split():
            try:
                os.kill(int(pid_s), signal.SIGTERM)
            except Exception:
                pass
        time.sleep(0.4)
    except Exception:
        pass
    env = os.environ.copy()
    env.pop("CADIVOR_AUTH_GATE_MOCK", None)
    existing = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = (
        SMOKE_PYTHONPATH if not existing else f"{SMOKE_PYTHONPATH}{os.pathsep}{existing}"
    )
    env.setdefault("SUPABASE_URL", "https://example.supabase.co")
    env.setdefault("SUPABASE_ANON_KEY", "public-anon-key-for-smoke")
    env.setdefault("SUPABASE_KEY", "public-anon-key-for-smoke")
    env["CADIVOR_SMOKE_STATE_FILE"] = str(STATE_FILE)
    log_fh = open(OUT / "streamlit.log", "w", encoding="utf-8")
    return subprocess.Popen(
        [
            STREAMLIT_PY,
            "-m",
            "streamlit",
            "run",
            SMOKE_APP,
            "--server.port",
            str(PORT),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
            "--server.address",
            "127.0.0.1",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    frames = OUT / BROWSER
    frames.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(STATES[0]["overlay"]), encoding="utf-8")
    from playwright.sync_api import sync_playwright

    proc = _start_streamlit()
    evidence = {"browser": BROWSER, "states": []}
    try:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                import urllib.request

                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_stcore/health", timeout=2)
                break
            except Exception:
                time.sleep(0.4)
        else:
            raise AssertionError("streamlit did not start")

        with sync_playwright() as p:
            browser_type = p.chromium if BROWSER == "chromium" else p.webkit
            browser = browser_type.launch(headless=True)
            for state in STATES:
                STATE_FILE.write_text(json.dumps(state["overlay"]), encoding="utf-8")
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(f"http://127.0.0.1:{PORT}", wait_until="domcontentloaded", timeout=90000)
                _login(page)
                page.locator(
                    '[class*="st-key-cv_foundation_navigation"] button:has-text("Settings")'
                ).first.click(timeout=8000)
                _wait_text(page, "Profile", timeout_s=40.0, label=f"{state['id']}_settings")
                page.locator(".st-key-cv_settings_nav button:has-text('Billing')").click(timeout=8000)
                _wait_settled(page, state["billing"], timeout_s=30.0, label=f"{state['id']}_billing")
                if state["checkout"] is None:
                    page.screenshot(path=str(frames / f"{state['id']}_billing.png"), full_page=False)
                page.locator('[data-cadivor-nav-key="settings_view_plans"]').click(timeout=8000)
                _wait_settled(page, state["pricing"], timeout_s=45.0, label=f"{state['id']}_pricing")
                body = page.inner_text("body") or ""
                forbidden = state.get("forbid")
                if forbidden and forbidden in body:
                    raise AssertionError(f"{state['id']} unexpectedly contains {forbidden!r}")
                if state.get("forbid_annual"):
                    for claim in ("Save 15%", "$296", "$1,010", "$3,050", "/ year"):
                        if claim in body:
                            raise AssertionError(f"{state['id']} shows unpublished annual claim {claim!r}")
                if state["checkout"]:
                    page.locator(f"button:has-text('Upgrade to {state['checkout']}')").first.scroll_into_view_if_needed()
                    _assert_single_checkout(page, state["checkout"])
                    body = page.inner_text("body") or ""
                    if state.get("forbid_annual"):
                        for claim in ("Save 15%", "$296", "$1,010", "$3,050", "/ year"):
                            if claim in body:
                                raise AssertionError(f"{state['id']} checkout shows unpublished annual claim {claim!r}")
                page.screenshot(path=str(frames / state["file"]), full_page=False)
                evidence["states"].append({"id": state["id"], "ok": True, "file": state["file"]})
                page.close()
            browser.close()
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
    (frames / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "browser": BROWSER, "out": str(frames)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "browser": BROWSER, "error": str(exc)}), file=sys.stderr)
        raise
