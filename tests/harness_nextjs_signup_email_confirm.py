#!/usr/bin/env python3
"""Browser harness: Next.js signup email confirm stage-then-click.

Requires a running Next origin (CADIVOR_SMOKE_WEB) with public Supabase env
pointing at a reachable host (requests are intercepted — no real verify).

  CADIVOR_SMOKE_WEB=http://127.0.0.1:3000 \\
  python tests/harness_nextjs_signup_email_confirm.py

Never prints raw token_hash values. Writes a redacted report under
.evidence_ui/next_signup_email_confirm/.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".evidence_ui" / "next_signup_email_confirm"
WEB = os.environ.get("CADIVOR_SMOKE_WEB", "").rstrip("/")

# Synthetic hashes used only in the address bar; never written to the report.
_LOAD_HASH = "fixture-load-hash"
_EXPIRED_HASH = "fixture-expired-hash"

_VERIFY_URL_RE = re.compile(r"/auth/v1/verify|/verify$", re.I)


def _redact(url: str) -> str:
    return re.sub(r"(token_hash=)[^&]+", r"\1REDACTED", url or "")


def _is_verify(url: str) -> bool:
    return bool(_VERIFY_URL_RE.search(url or ""))


def main() -> int:
    if not WEB:
        print("CADIVOR_SMOKE_WEB is required", file=sys.stderr)
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is required (apps/web devDependency)", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "web": WEB,
        "load_verify_count": None,
        "click_verify_count": None,
        "confirm_ui_visible": False,
        "url_cleared_after_click": False,
        "expired_stayed_on_login": False,
        "expired_message_visible": False,
        "ok": False,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        verify_urls: list[str] = []

        def on_request(request) -> None:
            if _is_verify(request.url):
                verify_urls.append("verify")

        page.on("request", on_request)

        # Intercept Supabase verify — success then expired in separate navigations.
        def handle_verify(route) -> None:
            if getattr(page, "_cadivor_verify_mode", "ok") == "expired":
                route.fulfill(
                    status=403,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "error": "otp_expired",
                            "msg": "Token has expired or is invalid",
                        }
                    ),
                )
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "access_token": "test-access",
                        "token_type": "bearer",
                        "expires_in": 3600,
                        "refresh_token": "test-refresh",
                        "user": {
                            "id": "u-test",
                            "email": "confirm-test@cadivor.test",
                            "email_confirmed_at": "2026-11-13T00:00:00Z",
                        },
                    }
                ),
            )

        # Only mock Supabase verify — do not intercept Next assets.
        page.route("**/auth/v1/verify**", handle_verify)
        page.route("**/auth/v1/verify", handle_verify)

        # --- Run 1: load alone — zero verify requests, Confirm UI visible ---
        verify_urls.clear()
        page._cadivor_verify_mode = "ok"  # type: ignore[attr-defined]
        # Use a placeholder hash; never log it.
        landing = f"{WEB}/login?token_hash={_LOAD_HASH}&type=email"
        page.goto(landing, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector('[data-testid="signup-confirm-ready"]', timeout=15000)
        time.sleep(0.8)  # allow any eager effects
        load_count = len(verify_urls)
        report["load_verify_count"] = load_count
        report["confirm_ui_visible"] = page.locator(
            '[data-testid="signup-confirm-ready"]'
        ).is_visible()
        heading = page.get_by_role("heading", name=re.compile(r"Confirm your email", re.I))
        assert heading.is_visible(), "Confirm heading missing"
        assert load_count == 0, f"expected 0 verify on load, got {load_count}"
        # Still on /login (may still have query until click)
        assert "/login" in page.url

        # --- Run 1b: one click → exactly one verify; token stripped ---
        verify_urls.clear()
        page.locator('[data-testid="signup-confirm-submit"]').click()
        page.wait_for_selector(
            '[data-testid="signup-confirm-success"], [data-testid="signup-confirm-invalid"]',
            timeout=15000,
        )
        # Give the in-flight request a moment to register.
        time.sleep(0.4)
        click_count = len(verify_urls)
        report["click_verify_count"] = click_count
        assert click_count == 1, f"expected 1 verify on click, got {click_count}"
        assert "token_hash=" not in page.url, _redact(page.url)
        report["url_cleared_after_click"] = "token_hash=" not in page.url
        assert "/login" in page.url

        # --- Run 2: expired token → stay on login with readable message ---
        verify_urls.clear()
        page._cadivor_verify_mode = "expired"  # type: ignore[attr-defined]
        expired_landing = f"{WEB}/login?token_hash={_EXPIRED_HASH}&type=email"
        page.goto(expired_landing, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector('[data-testid="signup-confirm-ready"]', timeout=15000)
        time.sleep(0.5)
        assert len(verify_urls) == 0, "expired load must not verify"
        page.locator('[data-testid="signup-confirm-submit"]').click()
        page.wait_for_selector('[data-testid="signup-confirm-invalid"]', timeout=15000)
        report["expired_stayed_on_login"] = "/login" in page.url
        body = page.locator('[data-testid="signup-confirm-invalid"]').inner_text()
        readable = bool(
            re.search(r"expired|already been used|can.?t be used", body, re.I)
        )
        report["expired_message_visible"] = readable
        assert report["expired_stayed_on_login"], _redact(page.url)
        assert readable, "expected readable expired/used message"
        # Retry actions present
        assert page.locator('[data-testid="signup-confirm-return-login"]').is_visible()
        assert page.get_by_role("link", name=re.compile(r"Create Account", re.I)).count() >= 1
        assert page.get_by_role("link", name=re.compile(r"Reset password", re.I)).count() >= 1

        # Screenshot without query string in the address bar (already stripped).
        shot = OUT / "confirm_states.png"
        page.screenshot(path=str(shot), full_page=True)

        browser.close()

    report["ok"] = (
        report["load_verify_count"] == 0
        and report["click_verify_count"] == 1
        and report["confirm_ui_visible"]
        and report["url_cleared_after_click"]
        and report["expired_stayed_on_login"]
        and report["expired_message_visible"]
    )
    (OUT / "harness_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
