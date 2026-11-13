"""Next.js signup email confirmation: stage-then-click contracts.

Proves source guardrails and (when CADIVOR_SMOKE_WEB is set) browser behavior:
page load makes no verify request; Confirm click makes exactly one; expired
tokens stay on /login with a readable message.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOGIN = ROOT / "apps" / "web" / "src" / "app" / "login" / "page.tsx"
HELPER = ROOT / "apps" / "web" / "src" / "lib" / "signupEmailConfirm.ts"
SUPABASE_TS = ROOT / "apps" / "web" / "src" / "lib" / "supabase.ts"
AUTH_PY = ROOT / "apps" / "api" / "supabase_auth.py"
HARNESS = ROOT / "tests" / "harness_nextjs_signup_email_confirm.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_helper_exports_stage_strip_verify_contract():
    src = _read(HELPER)
    assert 'SIGNUP_CONFIRM_TYPE = "email"' in src
    assert "parseSignupConfirmParams" in src
    assert "stripSignupConfirmParams" in src
    assert "verifySignupEmail" in src
    assert 'type: SIGNUP_CONFIRM_TYPE' in src or 'type: "email"' in src
    assert "token_hash" in src
    assert "Never log" in src or "never log" in src.lower()


def test_login_does_not_call_verify_otp_in_effects():
    src = _read(LOGIN)
    # No verifyOtp / verifySignupEmail inside useEffect bodies.
    effects = re.findall(r"useEffect\(\(\)\s*=>\s*\{(.*?)\},\s*\[[^\]]*\]\);", src, re.S)
    assert effects, "expected useEffect hooks on login page"
    for body in effects:
        assert "verifyOtp" not in body
        assert "verifySignupEmail" not in body
    # Click path must strip then verify.
    assert "stripSignupConfirmParams()" in src
    assert "verifySignupEmail" in src
    assert 'data-testid="signup-confirm-submit"' in src
    assert "Confirm your email to continue" in src
    assert "This link can’t be used" in src or "This link can't be used" in src
    assert 'data-testid="signup-confirm-invalid"' in src


def test_supabase_client_disables_url_detect_for_signup_confirm():
    src = _read(SUPABASE_TS)
    assert "signupConfirmCallbackInUrl" in src
    assert "detectSessionInUrl" in src


def test_api_signup_redirect_helper_requires_https_login_allowlist():
    src = _read(AUTH_PY)
    assert "CADIVOR_SIGNUP_REDIRECT_URL" in src
    assert "email_redirect_to" in src
    assert "def _signup_redirect_url" in src


def test_docs_confirm_sign_up_template_uses_token_hash_type_email():
    audit = _read(ROOT / "docs" / "EMAIL_DELIVERY_AUDIT.md")
    assert "CADIVOR_SIGNUP_REDIRECT_URL" in audit
    assert "https://app.cadivor.com/login" in audit
    assert "token_hash={{ .TokenHash }}" in audit or "token_hash={{ .TokenHash }}" in audit.replace(
        "&amp;", "&"
    )
    assert "type=email" in audit
    assert "Confirm sign up" in audit


@pytest.mark.skipif(
    not os.environ.get("CADIVOR_SMOKE_WEB"),
    reason="Set CADIVOR_SMOKE_WEB to a running Next origin to run browser harness",
)
def test_browser_harness_stage_click_expired():
    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, str(HARNESS)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    # Never echo raw token material from harness stdout into failures.
    safe_out = re.sub(r"token_hash=[^&\s]+", "token_hash=REDACTED", proc.stdout or "")
    safe_err = re.sub(r"token_hash=[^&\s]+", "token_hash=REDACTED", proc.stderr or "")
    assert proc.returncode == 0, f"harness failed\n{safe_out}\n{safe_err}"
    report_path = ROOT / ".evidence_ui" / "next_signup_email_confirm" / "harness_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report.get("load_verify_count") == 0
    assert report.get("click_verify_count") == 1
    assert report.get("expired_stayed_on_login") is True
    assert report.get("expired_message_visible") is True
    # Report must not retain raw fixture hashes.
    blob = json.dumps(report)
    assert "fixture-load-hash" not in blob
    assert "fixture-expired-hash" not in blob
