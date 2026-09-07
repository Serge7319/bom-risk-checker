#!/usr/bin/env python3
"""Browser-level production-path auth continuity smoke harness.

Usage:
  /opt/anaconda3/bin/python tests/harness_auth_gate_browser_smoke.py

Starts tests/smoke_production_streamlit_app.py — real ensure_authenticated_or_stop,
authenticated_runtime, unified_shell, and routing. Only the session boundary and
network IO are doubled. Captures frames under /tmp/cadivor_auth_gate_smoke/.
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
SMOKE_APP = str(ROOT / "tests" / "smoke_production_streamlit_app.py")

AUTH_ROUTES = (
    "Dashboard",
    "Alternative Finder",
    "Datasheet Q&A",
    "Compare Parts",
    "Procurement Advisor",
)

# Distinctive main-canvas copy — must appear before a route is considered settled.
# Sidebar labels alone are not enough (every route name is always in the nav).
ROUTE_CONTENT_MARKERS = {
    "Dashboard": ("Monitor portfolio health", "Welcome,"),
    "Alternative Finder": ("Choose a better replacement", "Find Alternatives"),
    "Datasheet Q&A": ("Ask Cadivor about your datasheet", "Upload datasheet"),
    "Compare Parts": ("Compare any two parts", "Part A"),
    "Procurement Advisor": ("Procurement Advisor", "Action Needed"),
}


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


def _viewport_probe(page) -> dict:
    return page.evaluate(
        """() => {
          const text = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim();
          const bg = window.getComputedStyle(document.body).backgroundColor || '';
          const gateNodes = Array.from(document.querySelectorAll(
            '.cv-auth-gate, .cv-auth-gate-card, [data-testid="cadivor-auth-gate"], [data-auth-gate]'
          ));
          const visibleGate = gateNodes.some((el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return !(
              style.display === 'none' ||
              style.visibility === 'hidden' ||
              Number(style.opacity || '1') === 0 ||
              rect.height < 2 ||
              rect.width < 2
            );
          });
          const gateKind = (document.querySelector('[data-auth-gate]') || {})
            .getAttribute?.('data-auth-gate') || '';
          const topbar = document.querySelector(
            '.cv-foundation-topbar:not(.cv-foundation-continuity)'
          );
          const nav = document.querySelector(
            '.st-key-cv_foundation_navigation, [class*="st-key-cv_foundation_navigation"]'
          );
          const continuityOnly = !topbar && !!document.querySelector(
            '.cv-foundation-continuity, [data-testid="cadivor-continuity-shell"]'
          );
          const hasLogin = gateKind === 'login' || /\\bLogin\\b|Sign in|password/i.test(text);
          const hasShell = !!(topbar && nav);
          const centeredLoader = Array.from(document.querySelectorAll(
            '.cv-auth-gate-card, [data-testid="cadivor-auth-gate"] .cv-auth-card, .cv-boot-card'
          )).some((el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            if (rect.height < 2 || rect.width < 2) return false;
            const cx = rect.left + rect.width / 2;
            const cy = rect.top + rect.height / 2;
            return Math.abs(cx - window.innerWidth / 2) < 220 &&
                   Math.abs(cy - window.innerHeight / 2) < 220;
          });
          const blankCanvas =
            text.length < 8 &&
            !hasLogin &&
            !hasShell &&
            (/rgb\\(\\s*255\\s*,\\s*255\\s*,\\s*255\\s*\\)/.test(bg) ||
             /rgb\\(\\s*0\\s*,\\s*0\\s*,\\s*0\\s*\\)/.test(bg) ||
             bg === 'rgba(0, 0, 0, 0)' ||
             !bg);
          return {
            textLen: text.length,
            textPreview: text.slice(0, 180),
            bg,
            hasLogin,
            hasShell,
            visibleGate,
            gateKind,
            continuityOnly,
            centeredLoader,
            blankCanvas,
            signingIn: /Signing you in|Restoring your session/i.test(text),
          };
        }"""
    )


def _assert_visible_branded_surface(page, label: str) -> None:
    """Fail if the viewport has neither Login nor the authenticated foundation shell."""
    probe = _viewport_probe(page)
    if probe.get("blankCanvas"):
        raise AssertionError(
            f"{label}: blank black/white frame "
            f"(bg={probe.get('bg')!r} preview={probe.get('textPreview')!r})"
        )
    if probe.get("hasLogin") or probe.get("hasShell"):
        return
    # During the brief authenticating transition, a branded gate card is allowed.
    if probe.get("visibleGate") and probe.get("gateKind") in {
        "boot",
        "authenticating",
        "error",
        "login",
    }:
        return
    body = " ".join((page.inner_text("body") or "").split())
    if len(body) < 8:
        raise AssertionError(f"{label}: blank viewport (no visible text)")
    raise AssertionError(
        f"{label}: viewport has neither Login nor authenticated foundation shell "
        f"(preview={probe.get('textPreview')!r})"
    )


def _assert_authenticated_continuity(page, label: str, *, allow_authenticating: bool = False) -> None:
    """Post-login invariant: shell stays; gate/boot/centered loader must not overlay it."""
    probe = _viewport_probe(page)
    if probe.get("blankCanvas"):
        raise AssertionError(f"{label}: blank black/white authenticated frame")
    if not probe.get("hasShell"):
        if allow_authenticating and probe.get("signingIn"):
            return
        raise AssertionError(
            f"{label}: authenticated foundation shell missing "
            f"(preview={probe.get('textPreview')!r})"
        )
    if probe.get("visibleGate") and probe.get("gateKind") in {
        "boot",
        "authenticating",
        "login",
        "error",
    }:
        raise AssertionError(
            f"{label}: visible .cv-auth-gate still present after shell mounted "
            f"(kind={probe.get('gateKind')!r})"
        )
    if probe.get("centeredLoader") or probe.get("signingIn"):
        raise AssertionError(
            f"{label}: centered auth/boot loader still visible after authentication"
        )


def _assert_no_continuity_skeleton_above_content(page, label: str) -> None:
    offenders = page.evaluate(
        """() => {
          const selectors = [
            '[data-testid="cadivor-continuity-shell"]',
            '.cv-foundation-continuity',
            '.cv56-skeleton-page',
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
              if (rect.height > 8 && rect.top < 120) {
                hits.push({ sel, top: rect.top, height: rect.height });
              }
            }
          }
          return hits;
        }"""
    )
    if offenders:
        raise AssertionError(f"{label}: continuity/skeleton still occupying layout {offenders!r}")


def _assert_login_handoff_frame(page, label: str) -> None:
    """Fail if the Login→shell handoff exposes a frame with neither Login/progress nor shell."""
    probe = _viewport_probe(page)
    has_progress = bool(
        probe.get("signingIn")
        or probe.get("gateKind") in {"authenticating", "boot"}
        or (
            probe.get("visibleGate")
            and probe.get("gateKind") in {"authenticating", "boot", "login", "error"}
        )
    )
    if probe.get("hasShell") or probe.get("hasLogin") or has_progress:
        # Once shell is up, a visible centered gate/boot card is not allowed.
        if probe.get("hasShell") and (
            probe.get("centeredLoader")
            or (
                probe.get("visibleGate")
                and probe.get("gateKind") in {"boot", "authenticating", "login", "error"}
            )
        ):
            raise AssertionError(
                f"{label}: gate/boot card still visible after foundation shell mounted"
            )
        return
    if probe.get("blankCanvas"):
        raise AssertionError(
            f"{label}: white/blank handoff frame "
            f"(bg={probe.get('bg')!r} preview={probe.get('textPreview')!r})"
        )
    raise AssertionError(
        f"{label}: handoff frame has neither Login/progress nor foundation shell "
        f"(preview={probe.get('textPreview')!r})"
    )


def _main_placeholder_probe(page) -> dict:
    return page.evaluate(
        """() => {
          const text = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim();
          const textContent = (document.body && document.body.textContent || '').replace(/\\s+/g, ' ').trim();
          const topbar = document.querySelector(
            '.cv-foundation-topbar:not(.cv-foundation-continuity)'
          );
          const nav = document.querySelector(
            '.st-key-cv_foundation_navigation, [class*="st-key-cv_foundation_navigation"]'
          );
          const shell = !!(topbar && nav);
          const topbarBottom = topbar ? topbar.getBoundingClientRect().bottom : 0;
          const pageCtx = document.querySelector('.cv-foundation-page-context');
          const pageCtxBottom = pageCtx ? pageCtx.getBoundingClientRect().bottom : 0;
          const ph = document.querySelector(
            '[data-testid="cadivor-main-content-placeholder"], .cv-main-content-placeholder'
          );
          let placeholderVisible = false;
          let placeholderTop = null;
          let placeholderHeight = 0;
          if (ph) {
            const style = window.getComputedStyle(ph);
            const rect = ph.getBoundingClientRect();
            placeholderVisible = !(
              style.display === 'none' ||
              style.visibility === 'hidden' ||
              Number(style.opacity || '1') === 0 ||
              rect.height < 2 ||
              rect.width < 2
            );
            placeholderTop = rect.top;
            placeholderHeight = rect.height;
          }
          const contentReady = !!document.querySelector(
            '[data-testid="cadivor-page-content-ready"]'
          );
          const hasDashboardCopy = /Monitor portfolio health|Welcome,|Upload my first BOM/i.test(text);
          const hasPlaceholderCopy = /Loading your workspace/i.test(text)
            || /Loading your workspace/i.test(textContent);
          return {
            shell,
            topbarBottom,
            pageCtxBottom,
            placeholderInDom: !!ph,
            placeholderVisible,
            placeholderTop,
            placeholderHeight,
            contentReady,
            hasDashboardCopy,
            hasPlaceholderCopy,
            textPreview: text.slice(0, 180),
            textContentHit: /Loading your workspace/i.test(textContent),
          };
        }"""
    )


def _assert_post_login_main_region(page, label: str) -> None:
    """After shell is visible, main canvas must have Dashboard content or placeholder."""
    probe = _main_placeholder_probe(page)
    if not probe.get("shell"):
        return
    body = ""
    try:
        body = str(page.inner_text("body") or "")
    except Exception:
        body = ""
    if (
        probe.get("placeholderVisible")
        or probe.get("contentReady")
        or probe.get("hasDashboardCopy")
        or probe.get("hasPlaceholderCopy")
        or "Loading your workspace" in body
    ):
        if probe.get("placeholderVisible"):
            top = probe.get("placeholderTop")
            topbar_bottom = probe.get("topbarBottom") or 0
            page_ctx_bottom = probe.get("pageCtxBottom") or 0
            floor = max(topbar_bottom, page_ctx_bottom)
            if top is not None and top + 2 < floor:
                raise AssertionError(
                    f"{label}: placeholder band above page heading/topbar "
                    f"(placeholderTop={top!r} floor={floor!r})"
                )
        return
    # Dump HTML snippet for diagnosis when the main canvas stays empty.
    try:
        html = page.content()
        (OUT / f"_empty_main_{label}.html").write_text(html[:200000], encoding="utf-8")
        page.screenshot(path=str(OUT / f"_empty_main_{label}.png"), full_page=True)
    except Exception:
        pass
    raise AssertionError(
        f"{label}: empty white main content region after shell "
        f"(preview={probe.get('textPreview')!r})"
    )


def _assert_no_visible_main_placeholder(page, label: str) -> None:
    probe = _main_placeholder_probe(page)
    if probe.get("placeholderVisible"):
        raise AssertionError(
            f"{label}: main-content placeholder must not be mounted/visible"
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


def _click_foundation_nav(page, route: str) -> None:
    # Prefer session-safe foundation nav buttons; fall back to link text.
    candidates = [
        page.locator(f'.st-key-cv_foundation_navigation button:has-text("{route}")').first,
        page.locator(f'[class*="st-key-cv_foundation_navigation"] button:has-text("{route}")').first,
        page.locator(f'button:has-text("{route}")').first,
        page.locator(f'a.cv-foundation-nav-link:has-text("{route}")').first,
    ]
    last_exc: Exception | None = None
    for loc in candidates:
        try:
            if loc.count():
                loc.click(timeout=8000)
                return
        except Exception as exc:
            last_exc = exc
            continue
    raise AssertionError(f"foundation nav control for {route!r} not found ({last_exc})")


def _wait_for_route(page, route: str, label: str, *, frames_dir: Path, prefix: str) -> None:
    ready = False
    markers = ROUTE_CONTENT_MARKERS.get(route, (route,))
    context_text = ""
    for i in range(50):
        _assert_no_visible_markup(page, f"{label}_{i}")
        _assert_visible_branded_surface(page, f"{label}_{i}")
        _assert_authenticated_continuity(page, f"{label}_{i}")
        html = page.content()
        body = page.inner_text("body") or ""
        page_context = page.locator(".cv-foundation-page-context strong").first
        try:
            context_text = (
                (page_context.inner_text() or "").strip() if page_context.count() else ""
            )
        except Exception:
            context_text = ""
        topbar_ok = context_text == route or context_text.replace("\xa0", " ") == route
        content_ok = any(marker in body for marker in markers)
        # Reject stale previous-route heroes still sitting in the main canvas.
        stale = False
        if route != "Alternative Finder" and "Choose a better replacement" in body:
            stale = True
        if route != "Compare Parts" and "Compare any two parts" in body:
            stale = True
        if (
            ("cv-foundation-topbar" in html)
            and topbar_ok
            and content_ok
            and not stale
            and "Signing you in" not in body
        ):
            _assert_no_continuity_skeleton_above_content(page, f"{label}_{i}")
            ready = True
            break
        if i in {0, 2, 5, 10, 20}:
            page.screenshot(
                path=str(frames_dir / f"{prefix}_t{i:02d}.png"), full_page=True
            )
        page.wait_for_timeout(400)
    page.screenshot(path=str(frames_dir / f"{prefix}_final.png"), full_page=True)
    (frames_dir / f"{prefix}_final.html").write_text(
        page.content()[:200000], encoding="utf-8"
    )
    if not ready:
        raise AssertionError(
            f"{label}: route {route!r} never settled with matching content "
            f"(topbar={context_text!r} markers={markers!r})"
        )

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    reuse_url = str(os.environ.get("CADIVOR_AUTH_SMOKE_URL") or "").strip()
    proc = None
    log_path = OUT / "streamlit_harness.log"
    url = reuse_url or f"http://127.0.0.1:{PORT}"

    if not reuse_url:
        # Ensure we never attach to a stale Streamlit from a prior smoke run.
        try:
            import signal as _signal
            import subprocess as _sp

            listed = _sp.check_output(
                ["lsof", "-tiTCP:%d" % PORT, "-sTCP:LISTEN"],
                text=True,
            ).strip()
            for pid_s in listed.split():
                try:
                    os.kill(int(pid_s), _signal.SIGTERM)
                except Exception:
                    pass
            time.sleep(0.6)
        except Exception:
            pass
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
            # Invalid login must not leave content-ready set (would skip placeholder).
            if 'data-testid="cadivor-page-content-ready"' in html_bad:
                raise AssertionError(
                    "invalid_login: cadivor-page-content-ready must not be set"
                )
            _assert_no_visible_main_placeholder(page, "invalid_login")

            target, email, password = _find_login_fields(page)
            if target is None:
                print("AUTH_SMOKE fail=login_fields_after_invalid")
                return 5
            email.fill(MOCK_EMAIL)
            password.fill(MOCK_PASSWORD)
            target.locator(
                'button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]'
            ).first.click(timeout=8000)

            # 1) Immediately after Login submit.
            page.wait_for_timeout(120)
            page.screenshot(path=str(OUT / "03a_login_submit.png"), full_page=True)
            (OUT / "03a_login_submit.html").write_text(
                page.content()[:200000], encoding="utf-8"
            )
            _assert_login_handoff_frame(page, "login_submit_immediate")

            # High-frequency sampling: shell+placeholder → Dashboard.
            ready = False
            saw_visible_placeholder = False
            shell_seen_at = None
            for i in range(250):
                _assert_no_visible_markup(page, f"login_to_dashboard_{i}")
                _assert_login_handoff_frame(page, f"login_to_dashboard_{i}")
                probe = _viewport_probe(page)
                ph = _main_placeholder_probe(page)
                if probe.get("hasShell"):
                    if shell_seen_at is None:
                        shell_seen_at = i
                    # Allow longer for the placeholder delta after chrome; the
                    # flush pass holds ~1.35s with shell+placeholder committed.
                    if (i - shell_seen_at) >= 8:
                        _assert_post_login_main_region(
                            page, f"login_to_dashboard_{i}"
                        )
                if (
                    ph.get("shell")
                    and (
                        ph.get("placeholderVisible")
                        or ph.get("hasPlaceholderCopy")
                    )
                    and not ph.get("hasDashboardCopy")
                ):
                    # 2) Foundation shell mounted; workspace/profile still loading.
                    if not saw_visible_placeholder:
                        page.screenshot(
                            path=str(OUT / "03b_shell_with_placeholder.png"),
                            full_page=True,
                        )
                        (OUT / "03b_shell_with_placeholder.html").write_text(
                            page.content()[:200000], encoding="utf-8"
                        )
                        (OUT / "03b_shell_with_placeholder.probe.json").write_text(
                            __import__("json").dumps(ph, indent=2),
                            encoding="utf-8",
                        )
                    saw_visible_placeholder = True
                    # CSS must not hide the only loading content yet.
                    if ph.get("contentReady"):
                        raise AssertionError(
                            f"login_to_dashboard_{i}: content-ready marker present "
                            "while placeholder is the only loading content"
                        )
                html_auth = page.content()
                if i in {0, 1, 2, 3, 5, 10, 20, 40}:
                    page.screenshot(
                        path=str(OUT / f"03_login_to_dashboard_t{i:02d}.png"),
                        full_page=True,
                    )
                    (OUT / f"03_login_to_dashboard_t{i:02d}.probe.json").write_text(
                        __import__("json").dumps(
                            {"i": i, "viewport": probe, "placeholder": ph},
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                if "cv-startup-shell-topbar" in html_auth:
                    raise AssertionError("login_to_dashboard: fake topbar present")
                if (
                    probe.get("hasShell")
                    and not probe.get("signingIn")
                    and ph.get("hasDashboardCopy")
                ):
                    _assert_authenticated_continuity(page, f"login_to_dashboard_{i}")
                    _assert_post_login_main_region(
                        page, f"login_to_dashboard_ready_{i}"
                    )
                    ready = True
                    break
                page.wait_for_timeout(100)

            # 3) Dashboard content fully rendered.
            page.screenshot(path=str(OUT / "03c_dashboard_ready.png"), full_page=True)
            page.screenshot(path=str(OUT / "04_dashboard_ready.png"), full_page=True)
            html_ready = page.content()
            _assert_not_blank_topbar(html_ready, "ready")
            _assert_no_visible_markup(page, "ready")
            _assert_authenticated_continuity(page, "ready")
            _assert_no_visible_main_placeholder(page, "dashboard_ready")
            ready_ph = _main_placeholder_probe(page)
            if not ready_ph.get("hasDashboardCopy"):
                raise AssertionError("dashboard_ready: Dashboard copy missing")
            (OUT / "03c_dashboard_ready.html").write_text(
                html_ready[:200000], encoding="utf-8"
            )
            (OUT / "04_dashboard_ready.html").write_text(
                html_ready[:200000], encoding="utf-8"
            )
            if not saw_visible_placeholder:
                print("AUTH_SMOKE fail=placeholder_never_visible")
                return 9
            if not ready:
                print("AUTH_SMOKE fail=stuck_on_login")
                return 6
            if "Mock workspace ready" in html_ready or "cadivor-auth-ready" in html_ready:
                raise AssertionError(
                    "ready: synthetic smoke ready surface still in use — "
                    "must exercise real authenticated_runtime / unified_shell"
                )

            # Authenticated route chain via real foundation nav.
            route_prefixes = {
                "Dashboard": "07_dashboard",
                "Alternative Finder": "08_alternative_finder",
                "Datasheet Q&A": "09_datasheet_qa",
                "Compare Parts": "10_compare_parts",
                "Procurement Advisor": "11_procurement_advisor",
            }
            for route in AUTH_ROUTES:
                if route != "Dashboard":
                    _click_foundation_nav(page, route)
                try:
                    _wait_for_route(
                        page,
                        route,
                        label=f"nav_{route}",
                        frames_dir=OUT,
                        prefix=route_prefixes[route],
                    )
                except AssertionError as exc:
                    print(f"AUTH_SMOKE fail=route_layout route={route} detail={exc}")
                    return 8
                # Ordinary authenticated navigation must never remount the placeholder.
                _assert_no_visible_main_placeholder(page, f"nav_{route}_no_placeholder")
                if route == "Alternative Finder":
                    page.screenshot(
                        path=str(OUT / "06_nav_no_placeholder.png"), full_page=True
                    )

            page.reload(wait_until="domcontentloaded")
            for _ in range(40):
                body_probe = page.inner_text("body") or ""
                if body_probe.strip():
                    _assert_no_visible_markup(page, "boot_restore_wait")
                    _assert_visible_branded_surface(page, "boot_restore_wait")
                probe = _viewport_probe(page)
                if probe.get("hasShell") and not probe.get("signingIn"):
                    break
                if probe.get("hasLogin"):
                    break
                page.wait_for_timeout(250)
            page.wait_for_timeout(1200)
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
            restore_probe = _viewport_probe(page)
            if not restore_probe.get("hasShell") and not restore_probe.get("hasLogin"):
                print("AUTH_SMOKE fail=session_restore_blank")
                return 7
            if restore_probe.get("hasLogin"):
                print("AUTH_SMOKE warn=session_restore_returned_login")
            else:
                _assert_authenticated_continuity(page, "session_restore")

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
