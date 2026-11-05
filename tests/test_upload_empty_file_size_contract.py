"""Regression: 0.0B upload UI is a zero-byte File client signal, not a prod CORS mask.

Isolation (Nov 2 2026 recording + Cursor/Playwright probes):
- Normal Chrome OS chooser on production uploads nonzero CSVs (2.1KB) and completes
  Analyze → progress → Saving → Engineering Intelligence.
- Empty ``File([], name)`` via DataTransfer surfaces as Streamlit ``0.0B``; a real
  byte payload surfaces as nonzero size and enables Analyze after PUT 204.
- Cursor MCP cannot complete the native file chooser and denies
  ``DOM.setFileInputFiles``; that path must not be "fixed" by disabling CORS/XSRF.
"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "scripts" / "cadivor_streamlit_boot.py"
RAILWAY = ROOT / "scripts" / "railway_start.sh"
CONFIG = ROOT / ".streamlit" / "config.toml"
FIXTURE = ROOT / ".evidence" / "fixtures" / "nov2_upload_debug_4part.csv"


class UploadEmptyFileSizeContractTests(unittest.TestCase):
    def test_synthetic_fixture_has_nonzero_bytes(self) -> None:
        self.assertTrue(FIXTURE.is_file(), f"missing fixture {FIXTURE}")
        size = FIXTURE.stat().st_size
        self.assertGreater(size, 0)
        # Streamlit formats small CSVs like "128.0B" — never "0.0B" for this fixture.
        self.assertNotEqual(size, 0)

    def test_empty_file_bytes_are_the_0_0B_signal(self) -> None:
        empty = b""
        real = FIXTURE.read_bytes()
        self.assertEqual(len(empty), 0)
        self.assertGreater(len(real), 0)
        # Document the UI mapping used in isolation evidence (no product formatter).
        empty_label = f"{len(empty) / 1:.1f}B"
        real_label = f"{len(real) / 1:.1f}B"
        self.assertEqual(empty_label, "0.0B")
        self.assertNotEqual(real_label, "0.0B")

    def test_product_keeps_cors_and_xsrf_enabled(self) -> None:
        """Guardrail: do not mask test-browser upload failures by weakening security."""
        start = RAILWAY.read_text(encoding="utf-8")
        config = CONFIG.read_text(encoding="utf-8")
        boot = BOOT.read_text(encoding="utf-8")
        self.assertNotIn("enableCORS=false", start)
        self.assertNotIn("enableXsrfProtection=false", start)
        self.assertIn("enableCORS = true", config)
        self.assertIn("enableXsrfProtection = true", config)
        self.assertIn('corsAllowedOrigins = ["https://app.cadivor.com"]', config)
        self.assertIn("https://app.cadivor.com", boot)


if __name__ == "__main__":
    unittest.main()
