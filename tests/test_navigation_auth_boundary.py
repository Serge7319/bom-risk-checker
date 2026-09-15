"""Sign-out and token checks must still fail closed after in-app navigation."""
from __future__ import annotations

import types

import src.auth_bootstrap as bootstrap
import src.auth_cookies as auth_cookies
import src.auth_gate as auth_gate
import src.auth_state as auth_state


class _Session(dict):
    def pop(self, key, default=None):
        return dict.pop(self, key, default)


class _Query(dict):
    def get(self, key, default=""):
        return dict.get(self, key, default)

    def clear(self):
        dict.clear(self)


class _FakeUser:
    id = "user-123"
    email = "user@example.com"


def _patch(monkeypatch, session, query):
    import sys

    fake = types.SimpleNamespace(
        session_state=session,
        query_params=query,
        markdown=lambda *_args, **_kwargs: None,
        components=types.SimpleNamespace(html=lambda *_args, **_kwargs: None),
    )
    # Ask Cadivor stubs can leave a ctx-less Streamlit runtime or replace
    # ``src.auth_state`` in ``sys.modules``. Keep fail-closed checks on the
    # explicit fake session used by this module.
    monkeypatch.setattr(auth_state, "st", fake)
    monkeypatch.setattr(bootstrap, "st", fake)
    monkeypatch.setattr(auth_cookies, "st", fake)
    monkeypatch.setitem(sys.modules, "src.auth_state", auth_state)
    try:
        import streamlit.runtime.scriptrunner as scriptrunner

        monkeypatch.setattr(scriptrunner, "get_script_run_ctx", lambda *a, **k: None)
    except Exception:
        pass
    return fake


def _live_session() -> _Session:
    return _Session(
        {
            "user": _FakeUser(),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
            "cadivor_nav_params": {"page": "Reports", "cadivor_signed_out": "1"},
            "cadivor_force_signed_out": True,
        }
    )


def test_explicit_sign_out_clears_the_session(monkeypatch):
    session = _live_session()
    _patch(monkeypatch, session, _Query({"cadivor_signed_out": "1", "page": "Reports"}))
    monkeypatch.setattr(auth_gate, "retire_authenticated_shell_hosts", lambda: None)
    cookies = types.SimpleNamespace(delete=lambda **_kwargs: None, set=lambda **_kwargs: None)
    supabase = types.SimpleNamespace(auth=types.SimpleNamespace(sign_out=lambda: None))

    auth_state.begin_logout(supabase, cookie_manager=cookies)

    assert "user" not in session
    assert "access_token" not in session
    assert "refresh_token" not in session
    assert session.get("cadivor_auth_status") == "signed_out"
    assert session.get("cadivor_explicit_logout") is True
    assert session.get("cadivor_force_signed_out") is True
    assert bootstrap.drop_stale_logout_query_for_authenticated_page_hop() is False
    assert auth_state.resolve_auth_state(supabase, None) == auth_state.AUTH_SIGNED_OUT
    assert "access_token" not in session


def test_expired_invalid_and_revoked_tokens_fail_closed(monkeypatch):
    cases = {
        "expired": types.SimpleNamespace(user=None),
        "invalid": types.SimpleNamespace(user=None),
        "revoked": RuntimeError("token revoked"),
    }
    for label, outcome in cases.items():
        session = _Session(
            {"access_token": f"{label}-a", "refresh_token": f"{label}-r"}
        )
        _patch(monkeypatch, session, _Query())

        def _reject(*_args, **_kwargs):
            if isinstance(outcome, Exception):
                raise outcome
            return types.SimpleNamespace(session=None, user=outcome.user)

        supabase = types.SimpleNamespace(
            auth=types.SimpleNamespace(set_session=_reject, get_user=_reject, sign_out=lambda: None)
        )
        status = auth_state.resolve_auth_state(supabase, cookie_manager=None)
        assert status == auth_state.AUTH_SIGNED_OUT, label
        assert "user" not in session
        assert session.get("cadivor_auth_status") != "authenticated"


def test_only_authenticated_page_hop_ignores_stale_logout_marker(monkeypatch):
    session = _live_session()
    query = _Query({"cadivor_signed_out": "1", "page": "Reports"})
    _patch(monkeypatch, session, query)

    assert bootstrap.drop_stale_logout_query_for_authenticated_page_hop() is True
    assert "cadivor_signed_out" not in query
    assert "cadivor_signed_out" not in session["cadivor_nav_params"]
    assert session.get("cadivor_force_signed_out") is None
    assert bootstrap.apply_signed_out_query_marker() is False
    assert session["access_token"] == "live-a"
    assert session["user"] is not None

    rejected = (
        {},
        {"access_token": "only-a", "refresh_token": "only-r"},
        {
            "user": _FakeUser(),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "signed_out",
        },
        {
            "user": _FakeUser(),
            "access_token": "live-a",
            "refresh_token": "live-r",
            "cadivor_auth_status": "authenticated",
            "cadivor_explicit_logout": True,
        },
    )
    for raw in rejected:
        session = _Session(raw)
        query = _Query({"cadivor_signed_out": "1"})
        _patch(monkeypatch, session, query)
        assert bootstrap.drop_stale_logout_query_for_authenticated_page_hop() is False
        assert query.get("cadivor_signed_out") == "1"
        assert bootstrap.apply_signed_out_query_marker() is True
        assert "access_token" not in session
        assert "user" not in session
        assert session.get("cadivor_explicit_logout") is True
