#!/usr/bin/env python3
"""Sprint 74.2B.4 multi-run harness — auth mode + isolated card shell."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_auth_mode_card_shell import AuthModeMultiRunHarness  # noqa: E402


def main() -> int:
    loader = unittest.defaultTestLoader
    tests = loader.loadTestsFromTestCase(AuthModeMultiRunHarness)
    runner = unittest.TextTestRunner(verbosity=2)
    out = runner.run(tests)
    return 0 if out.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
