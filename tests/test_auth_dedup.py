"""Sprint 71.9 — per-run auth validation and cookie write deduplication tests."""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from tests.test_auth_session_contract import (
    _FakeUser,
    _InlineExecutor,
    _install_auth_state,
    _install_streamlit_stub,
)


class AuthDedupTests(unittest.TestCase):
    def setUp(self):
        for name in list(sys.modules):
            if name in {"src.auth_state", "src.auth_cookies"}:
                sys.modules.pop(name, None)

    def _load(self, session_state=None):
        st = _install_streamlit_stub(session_state)
        auth_state = _install_auth_state(st)
        sys.modules.pop("src.auth_cookies", None)
        import importlib

        auth_cookies = importlib.import_module("src.auth_cookies")
        return st, auth_state, auth_cookies

    def _mock_supabase(self, *, user=_FakeUser()):
        supabase = MagicMock()
        fresh_session = types.SimpleNamespace(
            access_token="fresh-access",
            refresh_token="fresh-refresh",
        )
        supabase.auth.set_session.return_value = types.SimpleNamespace(session=fresh_session)
        supabase.auth.get_user.return_value = types.SimpleNamespace(user=user)
        return supabase

    def test_validate_tokens_runs_once_per_script_run(self):
        st, auth_state, _ = self._load(
            {"access_token": "a", "refresh_token": "r"},
        )
        supabase = self._mock_supabase()
        cookie_manager = MagicMock()

        with patch.object(auth_state, "_current_script_run_id", return_value="run-1"):
            with patch.object(auth_state, "ThreadPoolExecutor", _InlineExecutor):
                with patch("src.auth_cookies.persist_session_auth_cookie") as persist_mock:
                    first = auth_state._validate_tokens(supabase, "a", "r", cookie_manager)
                    second = auth_state._validate_tokens(supabase, "a", "r", cookie_manager)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(supabase.auth.set_session.call_count, 1)
        persist_mock.assert_called_once()

    def test_persist_cookie_runs_once_per_script_run(self):
        st, _, auth_cookies = self._load(
            {
                "user": _FakeUser(),
                "access_token": "a",
                "refresh_token": "r",
            }
        )
        cookie_manager = MagicMock()
        auth_cookie_writes: list[str] = []

        def _track_set(**kwargs):
            auth_cookie_writes.append(str(kwargs.get("key") or ""))
            return None

        cookie_manager.set.side_effect = _track_set

        with patch.object(auth_cookies, "_script_run_id", return_value="run-1"):
            with patch.object(auth_cookies, "auth_cookies_enabled", return_value=True):
                with patch.object(auth_cookies, "cookie_secure_flag", return_value=False):
                    auth_cookies.persist_session_auth_cookie(cookie_manager)
                    auth_cookies.persist_session_auth_cookie(cookie_manager)

        persist_writes = [key for key in auth_cookie_writes if key == "cadivor_persist_auth_cookie"]
        self.assertEqual(len(persist_writes), 1)

    def test_invalid_token_still_fails_closed(self):
        st, auth_state, _ = self._load(
            {"access_token": "a", "refresh_token": "r"},
        )
        supabase = self._mock_supabase(user=None)

        with patch.object(auth_state, "_current_script_run_id", return_value="run-2"):
            with patch.object(auth_state, "ThreadPoolExecutor", _InlineExecutor):
                ok = auth_state._validate_tokens(supabase, "a", "r", cookie_manager=None)

        self.assertFalse(ok)
        self.assertNotIn("user", st.session_state)


if __name__ == "__main__":
    unittest.main()
