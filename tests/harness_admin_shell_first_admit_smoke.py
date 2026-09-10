#!/usr/bin/env python3
"""Browser proof: admin first-admit must show Admin Console without reload.

Usage:
  CADIVOR_SMOKE_BROWSER=chromium /opt/anaconda3/bin/python \\
    tests/harness_admin_shell_first_admit_smoke.py

Launches real streamlit_app.py (smoke PYTHONPATH sitecustomize). Fails hard —
no retry masking. Set CADIVOR_SMOKE_ATTEMPTS (default 1) for consecutive runs.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import harness_auth_gate_browser_smoke as base  # noqa: E402

SMOKE_BROWSER = str(os.environ.get("CADIVOR_SMOKE_BROWSER") or "chromium").strip().lower()
ATTEMPTS = max(1, int(os.environ.get("CADIVOR_SMOKE_ATTEMPTS") or "1"))
PORT = int(os.environ.get("CADIVOR_ADMIN_SHELL_SMOKE_PORT") or "8531")
STREAMLIT_PY = base.STREAMLIT_PY
SMOKE_APP = base.SMOKE_APP
SMOKE_PYTHONPATH = base.SMOKE_PYTHONPATH
OUT_ROOT = Path(
    os.environ.get("CADIVOR_ADMIN_SHELL_SMOKE_OUT")
    or "/tmp/cadivor_admin_shell_first_admit"
)


def _read_counters(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _kill_port(port: int) -> None:
    try:
        listed = subprocess.check_output(
            ["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
            text=True,
        ).strip()
        for pid_s in listed.split():
            try:
                os.kill(int(pid_s), signal.SIGTERM)
            except Exception:
                pass
        time.sleep(0.6)
    except Exception:
        pass


def _start_streamlit(*, port: int, role: str, counters: Path, log_path: Path):
    _kill_port(port)
    env = os.environ.copy()
    env.pop("CADIVOR_AUTH_GATE_MOCK", None)
    env.pop("CADIVOR_AUTH_SMOKE", None)
    existing = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = (
        SMOKE_PYTHONPATH if not existing else f"{SMOKE_PYTHONPATH}{os.pathsep}{existing}"
    )
    env.setdefault("SUPABASE_URL", "https://example.supabase.co")
    env.setdefault("SUPABASE_ANON_KEY", "public-anon-key-for-smoke")
    env.setdefault("SUPABASE_KEY", "public-anon-key-for-smoke")
    env["CADIVOR_SMOKE_IO_COUNTERS"] = str(counters)
    env["CADIVOR_SMOKE_ROLE"] = role
    env["CADIVOR_SMOKE_PLAN"] = str(os.environ.get("CADIVOR_SMOKE_PLAN") or "Starter")
    # Keep first-admit profile miss delay so early shell can lag role.
    env.setdefault("CADIVOR_SMOKE_LOAD_USER_DELAY", "0.85")
    if counters.exists():
        counters.unlink()
    log_fh = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            STREAMLIT_PY,
            "-m",
            "streamlit",
            "run",
            SMOKE_APP,
            "--server.port",
            str(port),
            "--server.address",
            "127.0.0.1",
            "--server.headless",
            "true",
            "--server.fileWatcherType",
            "none",
            "--browser.serverAddress",
            "127.0.0.1",
            "--browser.serverPort",
            str(port),
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(90):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.kill()
        raise AssertionError(f"streamlit failed to start on {port}")
    return proc, url, log_fh


def _admin_console_visible(page) -> bool:
    loc = page.locator(
        '.st-key-cv_foundation_navigation button:has-text("Admin Console"), '
        '[class*="st-key-cv_foundation_navigation"] button:has-text("Admin Console")'
    )
    try:
        return bool(loc.count()) and loc.first.is_visible()
    except Exception:
        return False


def _assert_admin_console_clickable(page, label: str) -> None:
    loc = page.locator(
        '.st-key-cv_foundation_navigation button:has-text("Admin Console")'
    ).first
    if not loc.count():
        raise AssertionError(f"{label}: Admin Console nav button missing")
    box = loc.bounding_box()
    if not box:
        raise AssertionError(f"{label}: Admin Console has no bounding box")
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2
    hit = page.evaluate(
        """({x, y}) => {
          const el = document.elementFromPoint(x, y);
          if (!el) return {ok:false, tag:null, text:null};
          const btn = el.closest('button');
          const text = ((btn || el).innerText || '').trim();
          return {
            ok: !!btn && /Admin Console/i.test(text),
            tag: (btn || el).tagName,
            text: text.slice(0, 80),
          };
        }""",
        {"x": cx, "y": cy},
    )
    if not hit.get("ok"):
        raise AssertionError(f"{label}: Admin Console not hit-testable: {hit!r}")


def _assert_counters_first_admit(counters: Path, label: str) -> dict:
    data = _read_counters(counters)
    paints = int(data.get("render_unified_shell") or 0)
    resyncs = int(data.get("shell_admin_resync_rerun") or 0)
    role_lookups = int(data.get("shell_admin_role_lookup") or 0)
    admin_paints = int(data.get("shell_paint_is_admin_true") or 0)
    # Pre-shell verified role: no entitlement-resync rerun; role lookup must run;
    # first durable shell paint must already be admin for admin users.
    if paints < 1:
        raise AssertionError(f"{label}: expected >=1 render_unified_shell, got {paints}")
    if resyncs != 0:
        raise AssertionError(
            f"{label}: admin entitlement resync rerun must not run (got {resyncs})"
        )
    role = str(os.environ.get("CADIVOR_SMOKE_ROLE") or "user").lower()
    if role == "admin":
        if role_lookups < 1:
            raise AssertionError(
                f"{label}: expected public.users.role lookup before shell "
                f"(lookups={role_lookups})"
            )
        if admin_paints < 1:
            raise AssertionError(
                f"{label}: first shell paint(s) never received is_admin=True "
                f"(admin_paints={admin_paints}, paints={paints})"
            )
    return data


def _run_admin_scenario(*, browser_name: str, out: Path, port: int, attempt: int) -> None:
    counters = out / "io_counters.json"
    log_path = out / "streamlit.log"
    proc = None
    log_fh = None
    try:
        proc, url, log_fh = _start_streamlit(
            port=port, role="admin", counters=counters, log_path=log_path
        )
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            launcher = p.chromium if browser_name == "chromium" else p.webkit
            browser = launcher.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()

            # Cold signed-out load.
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            base._wait_for_login_surface(
                page, f"cold_login_{attempt}", frames_dir=out, prefix=f"{attempt:02d}_cold"
            )
            page.screenshot(path=str(out / f"{attempt:02d}_cold_login.png"), full_page=True)

            # Successful login → first settled Dashboard only (no reload / no other nav).
            base._perform_valid_login(
                page, frames_dir=out, prefix=f"{attempt:02d}_first_login"
            )
            base._assert_settled_route(page, "Dashboard", f"first_dashboard_{attempt}")
            page.screenshot(
                path=str(out / f"{attempt:02d}_dashboard_settled.png"), full_page=True
            )

            if not _admin_console_visible(page):
                raise AssertionError(
                    f"attempt={attempt}: Admin Console missing on first settled Dashboard"
                )
            _assert_admin_console_clickable(page, f"first_admit_{attempt}")
            evidence = _assert_counters_first_admit(counters, f"first_admit_{attempt}")
            (out / f"{attempt:02d}_first_admit_counters.json").write_text(
                json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
            )

            # Open Admin Console from sidebar (still no manual reload).
            base._click_foundation_nav(page, "Admin Console")
            for i in range(120):
                body = (page.inner_text("body") or "")
                top = page.evaluate(
                    """() => {
                      const el = document.querySelector('.cv-foundation-page-context strong');
                      return (el && el.textContent || '').trim();
                    }"""
                )
                if top == "Admin Console" and (
                    "Operational control" in body or "Admin Console" in body
                ):
                    break
                page.wait_for_timeout(100)
            else:
                raise AssertionError(f"attempt={attempt}: Admin Console page did not open")
            page.screenshot(
                path=str(out / f"{attempt:02d}_admin_console_open.png"), full_page=True
            )

            # Logout → relogin → Admin Console again on first settle.
            base._click_sign_out(page, app_url=url)
            base._wait_for_login_surface(
                page, f"after_logout_{attempt}", frames_dir=out, prefix=f"{attempt:02d}_logout"
            )
            # Reset counters for relogin admit measurement.
            if counters.exists():
                counters.write_text("{}", encoding="utf-8")
            base._perform_valid_login(
                page, frames_dir=out, prefix=f"{attempt:02d}_relogin"
            )
            base._assert_settled_route(page, "Dashboard", f"relogin_dashboard_{attempt}")
            if not _admin_console_visible(page):
                raise AssertionError(
                    f"attempt={attempt}: Admin Console missing after logout/relogin"
                )
            _assert_admin_console_clickable(page, f"relogin_{attempt}")
            relogin_counters = _assert_counters_first_admit(
                counters, f"relogin_{attempt}"
            )
            (out / f"{attempt:02d}_relogin_counters.json").write_text(
                json.dumps(relogin_counters, indent=2, sort_keys=True), encoding="utf-8"
            )
            page.screenshot(
                path=str(out / f"{attempt:02d}_relogin_dashboard.png"), full_page=True
            )
            browser.close()
    finally:
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()
        if log_fh is not None:
            try:
                log_fh.close()
            except Exception:
                pass


def _run_non_admin_scenario(*, browser_name: str, out: Path, port: int, attempt: int) -> None:
    counters = out / "io_counters_nonadmin.json"
    log_path = out / "streamlit_nonadmin.log"
    proc = None
    log_fh = None
    try:
        proc, url, log_fh = _start_streamlit(
            port=port, role="user", counters=counters, log_path=log_path
        )
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            launcher = p.chromium if browser_name == "chromium" else p.webkit
            browser = launcher.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            base._wait_for_login_surface(
                page,
                f"nonadmin_cold_{attempt}",
                frames_dir=out,
                prefix=f"{attempt:02d}_nonadmin_cold",
            )
            base._perform_valid_login(
                page, frames_dir=out, prefix=f"{attempt:02d}_nonadmin_login"
            )
            base._assert_settled_route(page, "Dashboard", f"nonadmin_dashboard_{attempt}")
            if _admin_console_visible(page):
                raise AssertionError(
                    f"attempt={attempt}: non-admin saw Admin Console in sidebar"
                )
            page.screenshot(
                path=str(out / f"{attempt:02d}_nonadmin_dashboard.png"), full_page=True
            )
            browser.close()
    finally:
        if proc is not None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()
        if log_fh is not None:
            try:
                log_fh.close()
            except Exception:
                pass


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    browser_name = SMOKE_BROWSER
    if browser_name not in {"chromium", "webkit"}:
        print(f"ADMIN_SHELL_SMOKE fail=bad_browser browser={browser_name}")
        return 2
    out = OUT_ROOT / browser_name
    out.mkdir(parents=True, exist_ok=True)
    # Ensure child processes honor role for counter assertions inside helpers.
    results = []
    for attempt in range(1, ATTEMPTS + 1):
        print(f"ADMIN_SHELL_SMOKE start browser={browser_name} attempt={attempt}/{ATTEMPTS}")
        try:
            os.environ["CADIVOR_SMOKE_ROLE"] = "admin"
            _run_admin_scenario(
                browser_name=browser_name, out=out, port=PORT, attempt=attempt
            )
            os.environ["CADIVOR_SMOKE_ROLE"] = "user"
            _run_non_admin_scenario(
                browser_name=browser_name,
                out=out,
                port=PORT + 1,
                attempt=attempt,
            )
            results.append({"attempt": attempt, "ok": True})
            print(f"ADMIN_SHELL_SMOKE ok browser={browser_name} attempt={attempt}")
        except Exception as exc:
            results.append({"attempt": attempt, "ok": False, "error": str(exc)})
            print(
                f"ADMIN_SHELL_SMOKE fail browser={browser_name} attempt={attempt} detail={exc}"
            )
            (out / "results.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8"
            )
            return 1
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"ADMIN_SHELL_SMOKE ok browser={browser_name} attempts={ATTEMPTS} out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
