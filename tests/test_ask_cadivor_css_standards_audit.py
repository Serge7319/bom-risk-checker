"""Sprint 72.3.4 — Lightweight CSS standards audit for core Ask Cadivor surfaces."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_CADIVOR_V2_CSS = REPO_ROOT / "src/assets/css/ask_cadivor_v2.css"

CORE_START = "/* Sprint 72.2.4 — Production presentation recovery"
CORE_END = "/* Sprint 72.3.1 — Native Streamlit class surfaces"

FRAGILE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r":has\s*\(", ":has() pseudo-class"),
    (r"display\s*:\s*subgrid", "CSS subgrid"),
    (r"@container\b", "container queries"),
)

CORE_CLASS_PREFIXES = (
    ".cv50-",
    ".cv49-",
    ".cv722-",
    ".cv724-",
    ".cv46-",
    ".cv727-",
)


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _extract_core_css() -> str:
    text = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")
    start = text.index(CORE_START)
    end = text.index(CORE_END, start)
    return _strip_css_comments(text[start:end])


class AskCadivorCssStandardsAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core_css = _extract_core_css()
        cls.full_css = ASK_CADIVOR_V2_CSS.read_text(encoding="utf-8")

    def test_core_block_has_no_fragile_selectors(self) -> None:
        for pattern, label in FRAGILE_PATTERNS:
            self.assertIsNone(
                re.search(pattern, self.core_css, flags=re.IGNORECASE),
                msg=f"Core Ask Cadivor CSS must not use {label}",
            )

    def test_expander_suppression_does_not_use_has(self) -> None:
        block = self.full_css[self.full_css.index("Sprint 72.3.4 — legacy expander") :]
        block = block.split("/* Sprint 72.3.1", 1)[0]
        self.assertNotIn(":has(", _strip_css_comments(block))

    def test_core_action_rows_have_solid_color_fallbacks(self) -> None:
        action_block = re.search(
            r"\.cv722-action-row,\s*\n\.cv722-action-list li\s*\{[^}]+\}",
            self.core_css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(action_block)
        block = action_block.group(0)
        self.assertRegex(block, r"background:\s*#[0-9a-fA-F]{3,8};")
        self.assertRegex(block, r"border:\s*1px solid\s*#[0-9a-fA-F]{3,8};")

    def test_core_surfaces_use_grid_or_flex(self) -> None:
        for selector in (
            ".cv50-exchange-top",
            ".cv722-summary-strip",
            ".cv724-impact-grid",
            ".cv724-driver-grid",
            ".cv46-evidence-board",
            ".cv46-evidence-card-header",
        ):
            self.assertIn(selector, self.core_css)
            idx = self.core_css.index(selector)
            snippet = self.core_css[idx : idx + 420]
            self.assertRegex(
                snippet,
                r"display\s*:\s*(grid|flex)",
                msg=f"{selector} should use grid or flex",
            )

    def test_core_layout_includes_min_width_zero_hardening(self) -> None:
        self.assertGreaterEqual(self.core_css.count("min-width: 0"), 8)


if __name__ == "__main__":
    unittest.main()
