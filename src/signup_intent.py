"""Small, non-secret signup intent markers shared across public auth flows."""
from __future__ import annotations

from typing import Any

REPORT_PURCHASE_QUERY_PARAM = "cadivor_purchase"
REPORT_PURCHASE_QUERY_VALUE = "one_time_report"
REPORT_PURCHASE_METADATA_KEY = "cadivor_signup_intent"
REPORT_PURCHASE_METADATA_VALUE = "one_time_report"
REPORT_PURCHASE_ROUTE = "BOM Analyzer"
REPORT_PURCHASE_PENDING_SESSION_KEY = "cadivor_report_purchase_pending"


def is_report_only_signup(metadata: Any) -> bool:
    """Whether Supabase signup metadata requests the least-privilege report flow."""
    if not isinstance(metadata, dict):
        return False
    intent = str(metadata.get(REPORT_PURCHASE_METADATA_KEY) or "").strip().lower()
    return intent == REPORT_PURCHASE_METADATA_VALUE


def report_purchase_signup_metadata() -> dict[str, str]:
    """Return only the low-privilege marker used to suppress the free trial."""
    return {REPORT_PURCHASE_METADATA_KEY: REPORT_PURCHASE_METADATA_VALUE}
