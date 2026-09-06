#!/usr/bin/env python3
"""Browser-level auth-gate smoke harness (test-only Streamlit entry).

Usage:
  /opt/anaconda3/bin/python tests/harness_auth_gate_browser_smoke.py

Starts tests/smoke_auth_streamlit_app.py (monkeypatched auth doubles — never
production streamlit_app.py). Captures screenshots under
/tmp/cadivor_auth_gate_smoke/.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/cadivor_auth_gate_smoke")
PORT = int(os.environ.get("CADIVOR_AUTH_SMOKE_PORT") or "8525")
MOCK_EMAIL = "auth-smoke@cadivor.test"
MOCK_PASSWORD = "cadivor-auth-smoke"
STREAMLIT_PY = str(ROOT / "venv" / "bin" / "python")
if not Path(STREAMLIT_PY).exists():
    STREAMLIT_PY = sys.executable
SMOKE_APP = str(ROOT / "tests" / "smoke_auth_streamlit_app.py")


def _assert_not_blank_topbar(html: str, label: str) -> None:
    if "cv-startup-shell-topbar" in html:
        raise AssertionError(f"{label}: fake startup topbar present")
    has_gate = 'data-auth-gate="' in html or "cadivor-auth-gate" in html
    has_brand = "Cadivor" in html
    has_login = "Login" in html or "Sign in" in html or "password" in html.lower()
    has_ready = (
        "Dashboard" in html
        or "Engineering workspace" in html
        or "cv-foundation-topbar" in html
    )
    if not (has_gate or has_brand or has_login or has_ready):
        raise AssertionError(f"{label}: empty/unknown frame without gate or brand")


_MARKUP_INDICATORS = (
    "<div",
    "<style",
    "<span",
    "class=",
    "cv-",
    "</",
    "unsafe_allow_html",
)


def _assert_no_visible_markup(page, label: str) -> None:
    """Visible page text must never contain raw HTML / CSS / component markup."""
    try:
        visible = str(page.inner_text("body") or "")
    except Exception as exc:
        raise AssertionError(f"{label}: could not read visible text ({exc})") from exc
    lowered = visible.casefold()
    for token in _MARKUP_INDICATORS:
        if token.casefold() in lowered:
            raise AssertionError(
                f"{label}: visible text contains markup indicator {token!r}"
            )


def _find_login_fields(page):
    for frame in [page, *page.frames]:
        email = frame.locator(
            'input[type="email"], input[autocomplete="email"], '
            'input[aria-label="Email"], div[data-testid="stTextInput"] input'
        ).first
        password = frame.locator(
            'input[type="password"], input[autocomplete="current-password"], '
            'div[data-testid="stTextInput"] input[type="password"]'
        ).first
        try:
            if email.count() and password.count():
                return frame, email, password
        except Exception:
            continue
    return None, None, None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    reuse_url = str(os.environ.get("CADIVOR_AUTH_SMOKE_URL") or "").strip()
    proc = None
    log_path = OUT / "streamlit_harness.log"
    url = reuse_url or f"http://127.0.0.1:{PORT}"

    if not reuse_url:
        env = os.environ.copy()
        # Deliberately do NOT set any mock-auth env switch — smoke uses DI only.
        env.pop("CADIVOR_AUTH_GATE_MOCK", None)
        env.setdefault("SUPABASE_URL", "https://example.supabase.co")
        env.setdefault("SUPABASE_ANON_KEY", "public-anon-key-for-smoke")
        env.setdefault("SUPABASE_KEY", "public-anon-key-for-smoke")
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
                "--browser.serverAddress",
                "127.0.0.1",
                "--browser.serverPort",
                str(PORT),
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=str(ROOT),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
        import urllib.request

        for _ in range(90):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("AUTH_SMOKE fail=server_start")
            return 2

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"AUTH_SMOKE fail=playwright_import detail={exc}")
        return 3

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=90000)

            saw_restoring_before_login = False
            for _ in range(40):
                html = page.content()
                _assert_no_visible_markup(page, "cold_start_wait")
                body = page.inner_text("body") or ""
                if "Restoring your session" in body:
                    saw_restoring_before_login = True
                target, email, password = _find_login_fields(page)
                if target is not None and 'data-auth-gate="login"' in html:
                    break
                page.wait_for_timeout(500)
            else:
                page.screenshot(path=str(OUT / "01_boot_or_login.png"), full_page=True)
                (OUT / "01_boot_or_login.html").write_text(
                    page.content()[:200000], encoding="utf-8"
                )
                print("AUTH_SMOKE fail=no_login_inputs")
                return 4

            if saw_restoring_before_login:
                raise AssertionError(
                    "cold_start: intermediate boot surface shown before Login"
                )

            page.screenshot(path=str(OUT / "01_boot_or_login.png"), full_page=True)
            html = page.content()
            _assert_not_blank_topbar(html, "frame1")
            _assert_no_visible_markup(page, "login")
            (OUT / "01_boot_or_login.html").write_text(html[:200000], encoding="utf-8")
            assert 'data-auth-gate="login"' in html
            login_body = page.inner_text("body") or ""
            if "Restoring your session" in login_body:
                raise AssertionError("login: boot restore message still visible")

            email.fill("wrong@cadivor.test")
            password.fill("not-the-password")
            target.locator(
                'button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]'
            ).first.click(timeout=8000)
            page.wait_for_timeout(2500)
            page.screenshot(path=str(OUT / "02_invalid_password.png"), full_page=True)
            html_bad = page.content()
            _assert_not_blank_topbar(html_bad, "invalid_password")
            _assert_no_visible_markup(page, "invalid_login")
            (OUT / "02_invalid_password.html").write_text(
                html_bad[:200000], encoding="utf-8"
            )

            target, email, password = _find_login_fields(page)
            if target is None:
                print("AUTH_SMOKE fail=login_fields_after_invalid")
                return 5
            email.fill(MOCK_EMAIL)
            password.fill(MOCK_PASSWORD)
            target.locator(
                'button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]'
            ).first.click(timeout=8000)
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / "03_authenticating.png"), full_page=True)
            html_auth = page.content()
            _assert_not_blank_topbar(html_auth, "authenticating")
            _assert_no_visible_markup(page, "authenticating")
            (OUT / "03_authenticating.html").write_text(
                html_auth[:200000], encoding="utf-8"
            )
            if "cv-startup-shell-topbar" in html_auth:
                raise AssertionError("authenticating: fake topbar present")

            ready = False
            for _ in range(40):
                html_ready = page.content()
                body = page.inner_text("body")
                _assert_no_visible_markup(page, "ready_wait")
                if (
                    "cv-foundation-topbar" in html_ready
                    or "Dashboard" in html_ready
                    or "Mock workspace" in html_ready
                ) and "Signing you in" not in body:
                    ready = True
                    break
                if "Sign in to continue" not in body and "Login" not in body:
                    ready = True
                    break
                page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / "04_ready.png"), full_page=True)
            html_ready = page.content()
            _assert_not_blank_topbar(html_ready, "ready")
            _assert_no_visible_markup(page, "ready")
            (OUT / "04_ready.html").write_text(html_ready[:200000], encoding="utf-8")
            if not ready or (
                "Mock workspace" not in html_ready and "Dashboard" not in html_ready
            ):
                print("AUTH_SMOKE fail=stuck_on_login")
                return 6
            if "cv-startup-shell-topbar" in html_ready:
                raise AssertionError("ready: fake topbar present")

            page.reload(wait_until="domcontentloaded")
            # Session restore may briefly show the full-page boot shell — never markup.
            for _ in range(20):
                _assert_no_visible_markup(page, "boot_restore_wait")
                html_probe = page.content()
                body_probe = page.inner_text("body") or ""
                if (
                    "Mock workspace" in html_probe
                    or "Dashboard" in html_probe
                    or 'data-auth-gate="login"' in html_probe
                ) and "Restoring your session" not in body_probe:
                    break
                page.wait_for_timeout(250)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / "05_session_restore.png"), full_page=True)
            html_restore = page.content()
            _assert_not_blank_topbar(html_restore, "session_restore")
            _assert_no_visible_markup(page, "session_restore")
            (OUT / "05_session_restore.html").write_text(
                html_restore[:200000], encoding="utf-8"
            )
            if "cv-startup-shell-topbar" in html_restore:
                raise AssertionError("session_restore: fake topbar present")
            if "Mock workspace" not in html_restore and "Dashboard" not in html_restore:
                if 'data-auth-gate="login"' in html_restore and "Login" in html_restore:
                    print("AUTH_SMOKE warn=session_restore_returned_login")
                else:
                    print("AUTH_SMOKE fail=session_restore_blank")
                    return 7

            browser.close()
        print(f"AUTH_SMOKE ok screenshots={OUT}")
        return 0
    finally:
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
