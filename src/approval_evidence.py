"""Validation helpers for evidence required by engineering approval."""

from __future__ import annotations

import re
from typing import Any


_PAGE_REFERENCE = re.compile(r"\b(?:pages?|pp?\.?)\s*#?\s*\d+\b", re.IGNORECASE)
_NON_DOCUMENT_WORDS = {
    "a",
    "an",
    "and",
    "data",
    "datasheet",
    "document",
    "documentation",
    "manufacturer",
    "na",
    "official",
    "pdf",
    "p",
    "page",
    "pages",
    "pp",
    "rev",
    "revision",
    "sheet",
    "the",
}
_PLACEHOLDERS = {
    "-",
    "—",
    "n a",
    "na",
    "n a not available",
    "n a unknown",
    "not available",
    "not found",
    "not recorded",
    "none",
    "unknown",
    "tbd",
    "to be determined",
    "unavailable",
}


def has_document_page_citation(value: Any) -> bool:
    """Require a document identifier and explicit PDF page number(s).

    A non-empty string such as ``NA`` must not satisfy the approval evidence
    gate. The part or document identifier can be a part number, document title,
    or model name; revision is useful when published, but not every datasheet
    has a visible revision.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return False

    normalized = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    if normalized in _PLACEHOLDERS:
        return False
    if any(
        normalized.startswith(prefix)
        for prefix in (
            "not applicable ",
            "not available ",
            "not found ",
            "not recorded ",
            "unknown ",
            "unavailable ",
            "tbd ",
        )
    ):
        return False

    page_match = _PAGE_REFERENCE.search(text)
    if not page_match:
        return False

    document_prefix = text[: page_match.start()]
    normalized_prefix = re.sub(r"[^a-z0-9]+", " ", document_prefix.casefold()).strip()
    if normalized_prefix in {"na", "n a", "not applicable", "not available", "unknown", "tbd"}:
        return False
    identifier_words = [
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]*", document_prefix)
        if token.casefold() not in _NON_DOCUMENT_WORDS and len(token) > 1
    ]
    return bool(identifier_words)
