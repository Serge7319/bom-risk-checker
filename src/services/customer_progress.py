"""Launch Sprint 30.0A customer activation helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ActivationProgress:
    account_created: bool
    first_bom: bool
    first_analysis: bool
    first_review: bool
    first_report: bool

    @property
    def completed(self) -> int:
        return sum((self.account_created, self.first_bom, self.first_analysis, self.first_review, self.first_report))

    @property
    def total(self) -> int:
        return 5

    @property
    def percent(self) -> int:
        return int(round((self.completed / self.total) * 100))


def build_activation_progress(*, analyses_count: int = 0, has_review: bool = False, has_report: bool = False, upload_detected: bool = False) -> ActivationProgress:
    analyses = max(0, int(analyses_count or 0))
    return ActivationProgress(
        account_created=True,
        first_bom=bool(upload_detected or analyses > 0),
        first_analysis=analyses > 0,
        first_review=bool(has_review),
        first_report=bool(has_report),
    )


def next_activation_action(progress: ActivationProgress) -> dict[str, Any]:
    if not progress.first_bom:
        return {"title": "Upload your first BOM", "copy": "Import a CSV or XLSX file and get the first risk summary in minutes.", "page": "BOM Analyzer", "button": "Upload BOM"}
    if not progress.first_analysis:
        return {"title": "Run your first analysis", "copy": "Generate lifecycle, supply, inventory, and engineering intelligence.", "page": "BOM Analyzer", "button": "Analyze BOM"}
    if not progress.first_review:
        return {"title": "Review the engineering priorities", "copy": "Validate the components Cadivor ranked as requiring attention.", "page": "Engineering Decisions", "button": "Open review"}
    if not progress.first_report:
        return {"title": "Share the outcome", "copy": "Generate an executive-ready report for engineering and procurement.", "page": "Reports", "button": "Create report"}
    return {"title": "Your workspace is activated", "copy": "Continue monitoring component and supplier changes across the portfolio.", "page": "Monitoring", "button": "Open monitoring"}
