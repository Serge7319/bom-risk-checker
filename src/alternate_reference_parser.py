"""Extract explicit replacement-part hints from supplier descriptions.

These hints are leads for an engineer to verify. They are not supplier-verified
crosses and must never be treated as approved or form-fit-function compatible.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style"}:
            self._skip_depth += 1
        elif tag.casefold() in {"p", "div", "li", "br"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag.casefold() in {"p", "div", "li", "br"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


_REFERENCE = re.compile(
    r"\b(?:recommended\s+(?:alternative|alt)|replacement(?:\s+part)?|"
    r"successor(?:\s+product)?|direct\s+cross)\b"
    r"\s*(?:(?:is)\s+|[:=#-]\s*)?"
    r"([A-Z0-9][A-Z0-9._/+()\-]{2,})",
    re.IGNORECASE,
)


def _plain_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parser = _TextOnly()
    try:
        parser.feed(raw)
        return " ".join(" ".join(parser.parts).split())
    except Exception:
        return " ".join(re.sub(r"(?is)<[^>]*>", " ", raw).split())


def extract_description_alternates(description: Any) -> list[str]:
    """Return distinct MPN-like tokens explicitly following replacement labels."""
    text = _plain_text(description)
    found: list[str] = []
    seen: set[str] = set()
    for match in _REFERENCE.finditer(text):
        candidate = match.group(1).strip(" \t\r\n.,;:!?\"'`()[]{}")
        if len(candidate) < 4 or not re.search(r"[A-Z]", candidate, re.IGNORECASE):
            continue
        if not re.search(r"\d", candidate):
            continue
        key = re.sub(r"[^A-Z0-9]", "", candidate.upper())
        if key in seen:
            continue
        seen.add(key)
        found.append(candidate)
    return found
