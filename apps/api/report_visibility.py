"""Customer-facing visibility rules for clearly marked internal QA analyses."""
from __future__ import annotations

import re
from typing import Any


_INTERNAL_MARKER = re.compile(
    r"(?<![a-z0-9])(?:synthetic|preview|fixture|e2e|qa)(?![a-z0-9])", re.I
)
_TEST_BOM_MARKER = re.compile(r"(?<![a-z0-9])test[\s_-]*bom(?:[\s_-]*\d+)?(?![a-z0-9])", re.I)
_SMOKE_MARKER = re.compile(
    r"(?<![a-z0-9])(?:smoke[\s_-]+(?:test|nested|flat)|(?:nested|flat)[\s_-]+smoke)(?![a-z0-9])",
    re.I,
)
_DEMO_FIXTURE_MARKER = re.compile(
    r"(?<![a-z0-9])demo[\s_-]+(?:controller(?:[\s_-]+bom)?|product[\s_-]+line)(?![a-z0-9])",
    re.I,
)


def is_internal_test_fixture_analysis(row: dict[str, Any]) -> bool:
    """Identify explicitly named demo/QA analyses without relying on evidence mode.

    Supplier evidence can be synthetic on a legitimate customer BOM, so mode
    and evidence labels are deliberately not used to hide the analysis.
    """
    if row.get("internal_test_fixture") is True or row.get("is_test_fixture") is True:
        return True

    values = [
        str(row.get(key) or "").strip()
        for key in ("project_name", "bom_name", "filename", "revision")
    ]
    searchable = " ".join(value for value in values if value)
    if not searchable:
        return False

    if _INTERNAL_MARKER.search(searchable):
        return True
    if _TEST_BOM_MARKER.search(searchable) or _SMOKE_MARKER.search(searchable):
        return True
    return bool(_DEMO_FIXTURE_MARKER.search(searchable))


def customer_visible_analyses(
    rows: list[dict[str, Any]], *, production: bool
) -> list[dict[str, Any]]:
    """Hide clearly named internal fixtures from production customer lists."""
    if not production:
        return rows
    return [row for row in rows if not is_internal_test_fixture_analysis(row)]
