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


def _assert_visible_branded_surface(page, label: str) -> None:
    """Fail if the viewport has no Login, progress, or application-shell content."""
    html = page.content()
    try:
        body = str(page.inner_text("body") or "")
    except Exception as exc:
        raise AssertionError(f"{label}: could not read visible text ({exc})") from exc
    body_stripped = " ".join(body.split())
    if len(body_stripped) < 8:
        raise AssertionError(f"{label}: blank viewport (no visible text)")

    has_login = (
        'data-auth-gate="login"' in html
        and (
            "Login" in body
            or "Sign in" in body
            or "password" in body.casefold()
            or "Email" in body
        )
    )
    has_progress = (
        'data-auth-gate="boot"' in html
        or 'data-auth-gate="authenticating"' in html
        or "Restoring your session" in body
        or "Signing you in" in body
    )
    has_shell = (
        "cv-foundation-topbar" in html
        or "cadivor-continuity-shell" in html
        or "Mock workspace" in body
        or "Dashboard" in body
        or "Settings" in body
        or (
            "Cadivor" in body
            and ("Engineering" in body or "workspace" in body.casefold())
        )
    )
    # Cadivor alone on a blank page is not enough without login/progress/shell cues.
    if has_login or has_progress or has_shell:
        return
    if "Cadivor" in body and (
        "Login" in html or "password" in html.casefold() or "cv-foundation" in html
    ):
        return
    raise AssertionError(
        f"{label}: no branded Login, progress, or application-shell content "
        f"(body_preview={body_stripped[:180]!r})"
    )


def _assert_no_continuity_skeleton_above_heading(page, label: str, route: str) -> None:
    """After an authenticated route is ready, continuity/skeleton must not sit above the heading."""
    heading = page.locator('[data-testid="cadivor-page-heading"]').first
    heading.wait_for(state="visible", timeout=15000)
    heading_text = (heading.inner_text() or "").strip()
    if route not in heading_text:
        raise AssertionError(f"{label}: expected heading for {route!r}, got {heading_text!r}")

    heading_box = heading.bounding_box()
    if not heading_box:
        raise AssertionError(f"{label}: page heading has no bounding box")

    # Continuity / skeleton hosts must not occupy layout space above the heading.
    offenders = page.evaluate(
        """(headingTop) => {
          const selectors = [
            '[data-testid="cadivor-continuity-shell"]',
            '.cv-foundation-continuity',
            '.cv56-skeleton-page',
            '[data-testid="stElementContainer"]:has(.cv56-skeleton-page)',
            '[data-testid="stElementContainer"]:has(.cv-foundation-continuity)',
          ];
          const hits = [];
          for (const sel of selectors) {
            let nodes = [];
            try { nodes = Array.from(document.querySelectorAll(sel)); } catch (e) { continue; }
            for (const el of nodes) {
              const style = window.getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              const hidden =
                style.display === 'none' ||
                style.visibility === 'hidden' ||
                Number(style.opacity || '1') === 0 ||
                rect.height < 1 ||
                rect.width < 1;
              if (hidden) continue;
              if (rect.bottom > 8 && rect.top < headingTop - 4) {
                hits.push({
                  sel,
                  top: rect.top,
                  bottom: rect.bottom,
                  height: rect.height,
                });
              }
            }
          }
          return hits;
        }""",
        heading_box["y"],
    )
    if offenders:
        raise AssertionError(
            f"{label}: continuity/skeleton occupies space above heading {offenders!r}"
        )

    # No centered auth/boot card after authentication.
    body = page.inner_text("body") or ""
    if "Signing you in" in body or "Restoring your session" in body:
        raise AssertionError(f"{label}: auth/boot progress card still visible")
    if 'data-auth-gate="authenticating"' in page.content() and "Signing you in" in body:
        raise AssertionError(f"{label}: authenticating gate still visible")


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
                body = page.inner_text("body") or ""
                if body.strip():
                    _assert_no_visible_markup(page, "cold_start_wait")
                    _assert_visible_branded_surface(page, "cold_start_wait")
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
            _assert_visible_branded_surface(page, "login")
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
            _assert_visible_branded_surface(page, "invalid_login")
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
            # Capture the complete login → dashboard transition; never blank.
            ready = False
            for i in range(50):
                _assert_no_visible_markup(page, f"login_to_ready_{i}")
                _assert_visible_branded_surface(page, f"login_to_ready_{i}")
                html_auth = page.content()
                body = page.inner_text("body") or ""
                if i == 2:
                    page.screenshot(
                        path=str(OUT / "03_authenticating.png"), full_page=True
                    )
                    (OUT / "03_authenticating.html").write_text(
                        html_auth[:200000], encoding="utf-8"
                    )
                if "cv-startup-shell-topbar" in html_auth:
                    raise AssertionError("authenticating: fake topbar present")
                if (
                    "cv-foundation-topbar" in html_auth
                    or "Dashboard" in html_auth
                    or "Mock workspace" in html_auth
                ) and "Signing you in" not in body:
                    ready = True
                    break
                page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / "04_ready.png"), full_page=True)
            html_ready = page.content()
            _assert_not_blank_topbar(html_ready, "ready")
            _assert_no_visible_markup(page, "ready")
            _assert_visible_branded_surface(page, "ready")
            (OUT / "04_ready.html").write_text(html_ready[:200000], encoding="utf-8")
            if not ready or (
                "Mock workspace" not in html_ready and "Dashboard" not in html_ready
            ):
                print("AUTH_SMOKE fail=stuck_on_login")
                return 6
            if "cv-startup-shell-topbar" in html_ready:
                raise AssertionError("ready: fake topbar present")

            # Authenticated routes: no continuity/skeleton band above page heading.
            route_shots = {
                "Dashboard": "07_dashboard.png",
                "Alternative Finder": "08_alternative_finder.png",
                "Compare Parts": "09_compare_parts.png",
                "Design Impact": "10_design_impact.png",
            }
            for route, shot_name in route_shots.items():
                btn = page.locator(f'button:has-text("Open {route}")').first
                btn.click(timeout=8000)
                ready_route = False
                for i in range(30):
                    _assert_no_visible_markup(page, f"nav_{route}_{i}")
                    _assert_visible_branded_surface(page, f"nav_{route}_{i}")
                    body_nav = page.inner_text("body") or ""
                    html_nav = page.content()
                    if route in body_nav and "cv-foundation-topbar" in html_nav:
                        try:
                            _assert_no_continuity_skeleton_above_heading(
                                page, f"route_{route}", route
                            )
                            ready_route = True
                            break
                        except AssertionError:
                            # Heading may still be mounting; keep polling.
                            pass
                    page.wait_for_timeout(400)
                page.screenshot(path=str(OUT / shot_name), full_page=True)
                (OUT / shot_name.replace(".png", ".html")).write_text(
                    page.content()[:200000], encoding="utf-8"
                )
                if not ready_route:
                    print(f"AUTH_SMOKE fail=route_layout route={route}")
                    return 8
                _assert_no_continuity_skeleton_above_heading(
                    page, f"route_{route}_final", route
                )

            page.reload(wait_until="domcontentloaded")
            # Session restore may briefly show the full-page boot shell — never markup.
            # Browser reload can yield an empty body until Streamlit paints; once text
            # appears it must be branded Login/progress/shell (never a blank canvas).
            for _ in range(40):
                body_probe = page.inner_text("body") or ""
                if body_probe.strip():
                    _assert_no_visible_markup(page, "boot_restore_wait")
                    _assert_visible_branded_surface(page, "boot_restore_wait")
                html_probe = page.content()
                if (
                    "Mock workspace" in html_probe
                    or "Dashboard" in html_probe
                    or "Design Impact" in body_probe
                    or "Alternative Finder" in body_probe
                    or 'data-auth-gate="login"' in html_probe
                ) and "Restoring your session" not in body_probe:
                    break
                page.wait_for_timeout(250)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / "05_session_restore.png"), full_page=True)
            html_restore = page.content()
            _assert_not_blank_topbar(html_restore, "session_restore")
            _assert_no_visible_markup(page, "session_restore")
            _assert_visible_branded_surface(page, "session_restore")
            (OUT / "05_session_restore.html").write_text(
                html_restore[:200000], encoding="utf-8"
            )
            if "cv-startup-shell-topbar" in html_restore:
                raise AssertionError("session_restore: fake topbar present")
            if (
                "Mock workspace" not in html_restore
                and "Dashboard" not in html_restore
                and "Design Impact" not in html_restore
                and "Alternative Finder" not in html_restore
                and "Compare Parts" not in html_restore
            ):
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
