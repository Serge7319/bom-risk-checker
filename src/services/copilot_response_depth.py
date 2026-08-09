"""Shared Ask Cadivor response-depth helpers."""
from __future__ import annotations


def wants_detailed_response(question: str) -> bool:
    """True when the user explicitly asks for a comprehensive or exhaustive analysis."""
    text = str(question or "").strip().lower()
    return any(
        token in text
        for token in (
            "detailed report",
            "full report",
            "comprehensive analysis",
            "comprehensive review",
            "explain every component",
            "every component",
            "all components",
            "each component",
            "exhaustive",
            "complete analysis",
            "thorough analysis",
            "deep dive",
            "component by component",
            "component-by-component",
        )
    )
