"""Compilation regression for the authenticated Cadivor runtime."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AuthenticatedRuntimeSyntaxTests(unittest.TestCase):
    def test_authenticated_runtime_compiles(self) -> None:
        source_path = ROOT / "src" / "authenticated_runtime.py"
        compile(source_path.read_text(encoding="utf-8"), str(source_path), "exec")


if __name__ == "__main__":
    unittest.main()
