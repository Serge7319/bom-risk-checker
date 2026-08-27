"""Regression coverage for authenticated profile continuity."""
from __future__ import annotations

import unittest

from src.services.authenticated_profile_cache import (
    PROFILE_CACHE_KEY,
    recent_verified_profile,
    remember_verified_profile,
)


class AuthenticatedProfileCacheTests(unittest.TestCase):
    def test_recent_profile_is_returned_only_for_the_same_user(self):
        state = {}
        profile = {"id": "user-1", "email": "user@example.com", "role": "user"}
        remember_verified_profile(state, profile, now=100.0)

        self.assertEqual(recent_verified_profile(state, "user-1", now=150.0), profile)
        self.assertIsNone(recent_verified_profile(state, "user-2", now=150.0))

    def test_stale_profile_is_not_used_as_a_fallback(self):
        state = {}
        remember_verified_profile(state, {"id": "user-1"}, now=100.0)

        self.assertIsNone(recent_verified_profile(state, "user-1", now=221.0))

    def test_profile_without_an_identity_is_not_cached(self):
        state = {}

        self.assertIsNone(remember_verified_profile(state, {"email": "user@example.com"}, now=100.0))
        self.assertNotIn(PROFILE_CACHE_KEY, state)
