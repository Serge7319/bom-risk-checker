from __future__ import annotations

import threading
from types import SimpleNamespace

from src.services.opening_profile_read import load_profile_for_opening


class _ScriptThreadState(dict):
    def __init__(self):
        super().__init__()
        self.owner = threading.get_ident()

    def get(self, key, default=None):
        assert threading.get_ident() == self.owner
        return super().get(key, default)

    def __setitem__(self, key, value):
        assert threading.get_ident() == self.owner
        return super().__setitem__(key, value)


def _thread_budget(fn):
    result = {}

    def worker():
        try:
            result["value"] = fn()
            result["status"] = "ok"
        except Exception:
            result["status"] = "error"

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2)
    if thread.is_alive():
        return None, "timeout"
    return result.get("value"), result.get("status", "error")


def test_profile_worker_reads_database_only_and_caches_on_script_thread():
    state = _ScriptThreadState()
    calls = []
    profile = {"id": "user-a", "email": "a@example.com"}

    def read_profile(user_id):
        assert threading.get_ident() != state.owner
        calls.append(user_id)
        return SimpleNamespace(data=[profile])

    def remember(session_state, row):
        session_state["profile"] = dict(row)
        return dict(row)

    loaded, status = load_profile_for_opening(
        session_state=state,
        user=SimpleNamespace(id="user-a"),
        access_token_fresh=True,
        supabase=object(),
        read_profile=read_profile,
        ensure_profile=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected provision")),
        recent_profile=lambda _state, _uid: None,
        remember_profile=remember,
        run_with_budget=_thread_budget,
    )

    assert status == "ok"
    assert loaded == profile
    assert calls == ["user-a"]
    assert state["profile"] == profile


def test_existing_trigger_created_profile_is_repaired_before_caching():
    state = _ScriptThreadState()
    profile = {"id": "user-a", "email": "a@example.com", "plan": "Starter"}
    repair_calls = []

    def repair(_client, user, row):
        assert threading.get_ident() == state.owner
        repair_calls.append((user.id, row["plan"]))
        return {**row, "plan": "Trial", "trial_ends_at": "2026-10-31T00:00:00+00:00"}

    loaded, status = load_profile_for_opening(
        session_state=state,
        user=SimpleNamespace(id="user-a"),
        access_token_fresh=True,
        supabase=object(),
        read_profile=lambda _user_id: SimpleNamespace(data=[profile]),
        ensure_profile=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected provision")),
        recent_profile=lambda _state, _uid: None,
        remember_profile=lambda session_state, row: session_state.__setitem__("profile", dict(row)) or dict(row),
        run_with_budget=_thread_budget,
        repair_profile=repair,
    )

    assert status == "ok"
    assert loaded["plan"] == "Trial"
    assert repair_calls == [("user-a", "Starter")]
    assert state["profile"]["plan"] == "Trial"


def test_cached_trigger_created_profile_is_repaired_on_warm_load():
    state = _ScriptThreadState()
    cached = {"id": "user-a", "email": "a@example.com", "plan": "Starter"}

    loaded, status = load_profile_for_opening(
        session_state=state,
        user=SimpleNamespace(id="user-a"),
        access_token_fresh=True,
        supabase=object(),
        read_profile=lambda _uid: (_ for _ in ()).throw(AssertionError("unexpected read")),
        ensure_profile=lambda *_: None,
        recent_profile=lambda _state, _uid: cached,
        remember_profile=lambda session_state, row: session_state.__setitem__("profile", dict(row)) or dict(row),
        run_with_budget=lambda _fn: (_ for _ in ()).throw(AssertionError("unexpected worker")),
        repair_profile=lambda _client, _user, row: {**row, "plan": "Trial"},
    )

    assert status == "ok"
    assert loaded["plan"] == "Trial"
    assert state["profile"]["plan"] == "Trial"


def test_stale_token_defers_auth_recovery_to_script_thread():
    state = _ScriptThreadState()
    budget_calls = []

    loaded, status = load_profile_for_opening(
        session_state=state,
        user=SimpleNamespace(id="user-a"),
        access_token_fresh=False,
        supabase=object(),
        read_profile=lambda _uid: (_ for _ in ()).throw(AssertionError("unexpected read")),
        ensure_profile=lambda *_: None,
        recent_profile=lambda _state, _uid: None,
        remember_profile=lambda *_: None,
        run_with_budget=lambda fn: budget_calls.append(fn),
    )

    assert loaded is None
    assert status == "refresh_required"
    assert budget_calls == []
