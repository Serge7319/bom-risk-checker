"""Tests for short-lived authenticated shell profile caching."""
from __future__ import annotations

import unittest
from pathlib import Path

from src.services.shell_profile_cache import (
    SHELL_PROFILE_CACHE_KEY,
    clear_shell_profile_cache,
    recent_shell_profile,
    remember_shell_profile,
)


class ShellProfileCacheTests(unittest.TestCase):
    def test_authenticated_shell_checks_session_cache_before_profile_read(self):
        runtime = (
            Path(__file__).resolve().parents[1] / "src" / "authenticated_runtime.py"
        ).read_text(encoding="utf-8")
        cache_lookup = runtime.index(
            "profile_for_shell = recent_shell_profile(st.session_state, _context_user_id)"
        )
        profile_read = runtime.index(
            "profile_for_shell = _quick_boot_read(_profile_for_shell, default=None)",
            cache_lookup,
        )
        self.assertLess(cache_lookup, profile_read)

    def test_returns_copy_for_same_user_within_ttl(self):
        state = {}
        remember_shell_profile(
            state,
            "user-1",
            {"full_name": "Engineer", "company": "Acme"},
            now=100,
        )

        profile = recent_shell_profile(state, "user-1", now=150)
        self.assertEqual(profile, {"full_name": "Engineer", "company": "Acme"})
        self.assertIsNot(profile, state[SHELL_PROFILE_CACHE_KEY]["profile"])

    def test_rejects_other_user_and_expired_profile(self):
        state = {}
        remember_shell_profile(state, "user-1", {"full_name": "Engineer"}, now=100)

        self.assertIsNone(recent_shell_profile(state, "user-2", now=101))
        self.assertIsNone(recent_shell_profile(state, "user-1", now=221))

    def test_explicit_update_invalidates_only_matching_user(self):
        state = {}
        remember_shell_profile(state, "user-1", {"full_name": "Engineer"}, now=100)

        clear_shell_profile_cache(state, "user-2")
        self.assertIsNotNone(recent_shell_profile(state, "user-1", now=101))
        clear_shell_profile_cache(state, "user-1")
        self.assertIsNone(recent_shell_profile(state, "user-1", now=101))


if __name__ == "__main__":
    unittest.main()
