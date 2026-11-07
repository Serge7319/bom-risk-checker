"""Behavior contracts for evidence-notice classification (Next UI)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTICE_TS = ROOT / "apps/web/src/lib/evidenceNotice.ts"
RUNNER = ROOT / "tests" / "_evidence_notice_runner.mjs"


CASES = [
    # critical
    ("Synthetic unit prices are estimates only.", "critical"),
    ("Offline catalog — incomplete evidence for this compare.", "critical"),
    ("Unable to confirm drop-in compatibility.", "critical"),
    ("Live supplier credentials are not connected.", "critical"),
    # context
    ("Based on saved analyses in this workspace.", "context"),
    ("Impact is computed from saved BOM analyses only.", "context"),
    ("Analyze a BOM first to unlock this view.", "context"),
    # service (omitted from page banners)
    ("Monitoring email is not connected.", "service"),
    ("Billing checkout is unavailable in this environment.", "service"),
    ("Design-tool connectors are not connected.", "service"),
    # empty
    ("", "hide"),
]


def _node_available() -> bool:
    try:
        subprocess.run(["node", "-v"], check=True, capture_output=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


@pytest.mark.skipif(not _node_available(), reason="node required for TS classifier behavior")
def test_classify_evidence_notice_categories():
    assert NOTICE_TS.is_file()
    assert RUNNER.is_file()
    env = {**os.environ, "EVIDENCE_NOTICE_CASES": json.dumps(CASES)}
    proc = subprocess.run(
        ["node", str(RUNNER)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    for item in payload["results"]:
        assert item["got"] == item["expected"], item


def test_compact_context_labels_are_restrained():
    assert "Based on saved analyses" in NOTICE_TS.read_text(encoding="utf-8")
    assert "Requires a saved BOM analysis" in NOTICE_TS.read_text(encoding="utf-8")


def test_gap_banner_omits_service_tone():
    gap = (ROOT / "apps/web/src/components/GapBanner.tsx").read_text(encoding="utf-8")
    assert 'tone === "hide" || tone === "service"' in gap
    assert "classifyEvidenceNotice" in gap


def test_settings_service_readiness_uses_dedicated_endpoint():
    settings = (ROOT / "apps/web/src/app/settings/page.tsx").read_text(encoding="utf-8")
    assert "fetchServiceReadiness" in settings
    assert "readinessUnknown" in settings
    assert "billing?.monitoring_email_enabled" not in settings
    assert "usage?.monitoring_email_enabled" not in settings
    main = (ROOT / "apps/api/main.py").read_text(encoding="utf-8")
    assert "/integrations/service-readiness" in main
    assert "async def service_readiness_get" in main


def test_globals_css_does_not_hide_page_overflow_on_html_body():
    css = (ROOT / "apps/web/src/app/globals.css").read_text(encoding="utf-8")
    html_body = css.split("html,", 1)[1].split("a {", 1)[0]
    assert "overflow-x: hidden" not in html_body
    assert "@media (max-width: 520px)" in css
    assert "data-label" in (ROOT / "apps/web/src/app/design-impact/page.tsx").read_text(
        encoding="utf-8"
    )
