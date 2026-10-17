from __future__ import annotations

from src.services.account_scope import bind_authenticated_account
from src.services.onboarding_progress_cache import (
    ONBOARDING_PROGRESS_CACHE_KEY,
    recent_onboarding_progress,
    remember_onboarding_progress,
)


def test_onboarding_cache_is_recent_and_account_scoped():
    state = {}
    progress = {"user_id": "user-a", "welcome_seen": True}

    remember_onboarding_progress(state, "user-a", progress, now=100.0)

    assert recent_onboarding_progress(state, "user-a", now=150.0) == progress
    assert recent_onboarding_progress(state, "user-b", now=150.0) is None
    assert recent_onboarding_progress(state, "user-a", now=221.0) is None

    state["cadivor_scoped_user_id"] = "user-a"
    assert bind_authenticated_account(state, "user-b") is True
    assert ONBOARDING_PROGRESS_CACHE_KEY not in state


def test_successful_empty_progress_is_cached_as_a_value():
    state = {}

    remember_onboarding_progress(state, "user-a", {}, now=50.0)

    assert recent_onboarding_progress(state, "user-a", now=51.0) == {}
