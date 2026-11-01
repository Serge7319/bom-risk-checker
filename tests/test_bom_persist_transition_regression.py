"""Contract for BOM persist transition measurement harness."""
from __future__ import annotations

from pathlib import Path

HARNESS = Path(__file__).resolve().parent / "support" / "capture_bom_persist_stability.py"


def test_persist_stability_harness_measures_required_stages():
    source = HARNESS.read_text(encoding="utf-8")
    for key in ("progress_0", "progress_mid", "progress_4", "saving", "report"):
        assert key in source
    assert "sidebarVisible" in source
    assert "MAX_DRIFT_PX = 8" in source
    assert "card_drift_gt_8px" in source
    assert "report_without_sidebar" in source
