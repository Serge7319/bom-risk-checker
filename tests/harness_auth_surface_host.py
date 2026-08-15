#!/usr/bin/env python3
"""Sprint 74.2B.5.2 — auth surface host multi-run harness."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_auth_surface_host import (  # noqa: E402
    AuthSurfaceHostCardAndModeTests,
    AuthSurfaceHostLifecycleTests,
    AuthSurfaceHostMultiRunHarness,
    AuthSurfaceHostSourceGuards,
)


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for case in (
        AuthSurfaceHostSourceGuards,
        AuthSurfaceHostLifecycleTests,
        AuthSurfaceHostCardAndModeTests,
        AuthSurfaceHostMultiRunHarness,
    ):
        suite.addTests(loader.loadTestsFromTestCase(case))
    runner = unittest.TextTestRunner(verbosity=2)
    out = runner.run(suite)
    return 0 if out.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
