#!/usr/bin/env python3
"""Sprint 74.2B.5.4 — auth scroll-anchoring harness."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_auth_scroll_anchoring import (  # noqa: E402
    AuthScrollAnchoringAuthenticatedScopeGuard,
    AuthScrollAnchoringLifecycleTests,
    AuthScrollAnchoringSourceGuards,
)


def main() -> int:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for case in (
        AuthScrollAnchoringSourceGuards,
        AuthScrollAnchoringLifecycleTests,
        AuthScrollAnchoringAuthenticatedScopeGuard,
    ):
        suite.addTests(loader.loadTestsFromTestCase(case))
    out = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if out.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
