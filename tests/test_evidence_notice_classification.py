"""Contract for evidence-notice classification used by the Next Settings/UI polish."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTICE = (ROOT / "apps/web/src/lib/evidenceNotice.ts").read_text(encoding="utf-8")


def test_classifier_distinguishes_critical_context_and_service_gaps():
    assert "CRITICAL_RE" in NOTICE
    assert "CONTEXT_RE" in NOTICE
    assert "SERVICE_RE" in NOTICE
    assert "classifyEvidenceNotice" in NOTICE
    assert "compactContextLabel" in NOTICE
    # Service availability must not be painted as a yellow page warning.
    assert "monitoring email" in NOTICE.lower()
    assert "billing checkout" in NOTICE.lower()
    # Decision-critical synthetic / offline cues remain classified critical.
    assert "synthetic" in NOTICE.lower()
    assert "offline" in NOTICE.lower()


def test_reports_list_does_not_reuse_persistence_service_blurb_as_gap():
    main = (ROOT / "apps/api/main.py").read_text(encoding="utf-8")
    block = main.split("async def reports_list", 1)[1].split("async def reports_delete", 1)[0]
    assert '"gap": None' in block or '"gap":None' in block.replace(" ", "")
    assert "persistence[\"label\"]" not in block


def test_persistence_label_no_longer_bundles_service_gaps():
    store = (ROOT / "apps/api/workspace_store.py").read_text(encoding="utf-8")
    assert "service_gaps" in store
    postgres = store.split('if db_url:', 1)[1].split("if allow_ephemeral_file_store", 1)[0]
    assert '"label": "Saved BOM and project records are stored in your workspace database."' in postgres
    assert "Monitoring email" not in postgres.split("service_gaps", 1)[0]
