"""Legacy host tests retired — auth gate owns paint. See test_auth_gate.py."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AuthSurfaceHostRetired(unittest.TestCase):
    def test_bootstrap_does_not_create_empty_host(self):
        bootstrap = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
        fn = bootstrap[
            bootstrap.find("def ensure_authenticated_or_stop") : bootstrap.find(
                "# NOTE: auth gate owns paint"
            )
        ]
        self.assertNotRegex(fn, r"(?m)^\s*.*st\.empty\(\)")
        self.assertIn("paint_auth_gate(", fn)

    def test_should_render_startup_shell_always_false(self):
        from unittest.mock import MagicMock, patch

        with patch.dict("sys.modules", {"streamlit": MagicMock()}):
            # Import after stub so module can load.
            import importlib

            import src.auth_bootstrap as bootstrap

            importlib.reload(bootstrap)
            self.assertFalse(bootstrap.should_render_authenticated_startup_shell())


if __name__ == "__main__":
    unittest.main()
