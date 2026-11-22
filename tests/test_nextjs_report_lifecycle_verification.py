from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_PAGE = ROOT / "apps/web/src/app/reports/[id]/page.tsx"


def test_saved_report_labels_lifecycle_evidence_before_displaying_a_value():
    source = REPORT_PAGE.read_text(encoding="utf-8")

    assert "function reportLifecycleDisplay" in source
    assert 'evidenceClass === "live-authorized-supplier" && lifecycle?.current === true' in source
    assert 'label: "Preview only"' in source
    assert 'label: "Needs verification"' in source
    assert "Reported: ${value} · unverified" in source
    assert "const lifecycleDisplay = reportLifecycleDisplay(part);" in source
    assert "StatusPill kind={lifecycleDisplay.kind}" in source
    assert '<td>{String(part.Lifecycle || "")}</td>' not in source
