"""Sprint 72.4 — Ask Cadivor persistence/resume regression tests."""
from __future__ import annotations

import importlib
import inspect
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from tests.copilot_conversation_store_stub import InMemoryCopilotStore
from tests.ask_cadivor_streamlit_stub import install_ask_cadivor_streamlit_stub, restore_ask_cadivor_streamlit_modules


QUESTION = "What should I review first in this BOM?"
ANSWER = "### Engineering Assessment\nReview PC817 first."
ANALYSIS_A = "analysis-a"
ANALYSIS_B = "analysis-b"
USER_A = "user-a"
USER_B = "user-b"
WORKSPACE = "workspace-1"


def _ensure_real_copilot_modules() -> None:
    for module_name in (
        "src.services.copilot_conversation_store",
        "src.services.copilot_conversation",
    ):
        module = sys.modules.get(module_name)
        if module is not None and not getattr(module, "__file__", None):
            sys.modules.pop(module_name, None)
    importlib.import_module("src.services.copilot_conversation")


def _context(*, analysis_id: str) -> dict:
    return {
        "analysis": {"analysis_id": analysis_id, "workspace_id": WORKSPACE},
        "analysis_id": analysis_id,
        "workspace_id": WORKSPACE,
        "summary": {"health_score": 93},
        "components": [{"part_number": "PC817", "risk_score": 40}],
    }


class CopilotConversationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        _ensure_real_copilot_modules()

    def test_normalize_persisted_thread_drops_corrupt_rows(self) -> None:
        from src.services.copilot_conversation_store import normalize_persisted_thread

        thread = normalize_persisted_thread(
            [
                {"question": QUESTION, "answer": ANSWER},
                {"question": "", "answer": "orphan"},
                "bad-row",
                {"question": "Valid?", "answer": "Yes."},
            ]
        )
        self.assertEqual(len(thread), 2)
        self.assertEqual(thread[0]["question"], QUESTION)

    def test_save_and_load_round_trip(self) -> None:
        from src.services.copilot_conversation_store import load_thread, save_thread

        store = InMemoryCopilotStore()
        payload = [{"question": QUESTION, "answer": ANSWER, "provider_connected": True}]
        self.assertIsNone(
            save_thread(
                store,
                user_id=USER_A,
                analysis_id=ANALYSIS_A,
                workspace_id=WORKSPACE,
                thread=payload,
            )
        )
        loaded, error = load_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
        )
        self.assertIsNone(error)
        self.assertEqual(loaded[0]["question"], QUESTION)
        self.assertEqual(loaded[0]["answer"], ANSWER)

    def test_cross_user_read_isolation(self) -> None:
        from src.services.copilot_conversation_store import load_thread, save_thread

        store = InMemoryCopilotStore()
        save_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
            thread=[{"question": QUESTION, "answer": ANSWER}],
        )
        loaded, error = load_thread(
            store,
            user_id=USER_B,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
        )
        self.assertIsNone(error)
        self.assertEqual(loaded, [])

    def test_cross_user_update_isolation(self) -> None:
        from src.services.copilot_conversation_store import load_thread, save_thread

        store = InMemoryCopilotStore()
        save_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
            thread=[{"question": QUESTION, "answer": ANSWER}],
        )
        save_thread(
            store,
            user_id=USER_B,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
            thread=[{"question": "Hijack?", "answer": "No."}],
        )
        loaded, _error = load_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
        )
        self.assertEqual(loaded[0]["question"], QUESTION)

    def test_cross_user_delete_isolation(self) -> None:
        from src.services.copilot_conversation_store import delete_thread, load_thread, save_thread

        store = InMemoryCopilotStore()
        save_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
            thread=[{"question": QUESTION, "answer": ANSWER}],
        )
        delete_thread(
            store,
            user_id=USER_B,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
        )
        loaded, _error = load_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
        )
        self.assertEqual(len(loaded), 1)

    def test_cross_analysis_read_isolation(self) -> None:
        from src.services.copilot_conversation_store import load_thread, save_thread

        store = InMemoryCopilotStore()
        save_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
            thread=[{"question": QUESTION, "answer": ANSWER}],
        )
        loaded, error = load_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_B,
            workspace_id=WORKSPACE,
        )
        self.assertIsNone(error)
        self.assertEqual(loaded, [])

    def test_missing_table_fails_gracefully(self) -> None:
        from src.services.copilot_conversation_store import load_thread

        class _MissingTableClient:
            def table(self, _name: str):
                raise Exception('relation "copilot_conversation_threads" does not exist')

        loaded, error = load_thread(
            _MissingTableClient(),
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
        )
        self.assertEqual(loaded, [])
        self.assertIsNotNone(error)

    def test_read_failure_hydrates_safely(self) -> None:
        from src.services.copilot_conversation import hydrate_thread_from_store

        class _BrokenClient:
            def table(self, _name: str):
                raise RuntimeError("read transport failure")

        session_state: dict = {}
        error = hydrate_thread_from_store(
            session_state,
            _context(analysis_id=ANALYSIS_A),
            user_id=USER_A,
            supabase=_BrokenClient(),
        )
        self.assertIsNotNone(error)
        self.assertNotIn("cv35_last_answer", session_state)


class CopilotConversationHydrationTests(unittest.TestCase):
    def setUp(self) -> None:
        restore_ask_cadivor_streamlit_modules()
        _ensure_real_copilot_modules()
        self.store = InMemoryCopilotStore()
        from src.services.copilot_conversation_store import save_thread

        save_thread(
            self.store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
            thread=[{"question": QUESTION, "answer": ANSWER, "provider_connected": True}],
        )

    def test_hydrate_restores_thread_and_latest_answer(self) -> None:
        from src.services.copilot_conversation import get_thread, hydrate_thread_from_store

        session_state: dict = {}
        hydrate_thread_from_store(
            session_state,
            _context(analysis_id=ANALYSIS_A),
            user_id=USER_A,
            supabase=self.store,
        )
        thread = get_thread(session_state, _context(analysis_id=ANALYSIS_A))
        self.assertEqual(thread[0]["question"], QUESTION)
        self.assertEqual(session_state["cv35_last_question"], QUESTION)
        self.assertEqual(session_state["cv35_last_answer"], ANSWER)

    def test_hydrate_is_scoped_to_analysis(self) -> None:
        from src.services.copilot_conversation import hydrate_thread_from_store

        session_state: dict = {}
        hydrate_thread_from_store(
            session_state,
            _context(analysis_id=ANALYSIS_B),
            user_id=USER_A,
            supabase=self.store,
        )
        self.assertNotIn("cv35_last_answer", session_state)

    def test_hydrate_is_scoped_to_user(self) -> None:
        from src.services.copilot_conversation import hydrate_thread_from_store

        session_state: dict = {}
        hydrate_thread_from_store(
            session_state,
            _context(analysis_id=ANALYSIS_A),
            user_id=USER_B,
            supabase=self.store,
        )
        self.assertNotIn("cv35_last_answer", session_state)


class AskCadivorPersistenceResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        restore_ask_cadivor_streamlit_modules()
        _ensure_real_copilot_modules()
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
    def _load_assistant(self):
        for name in list(sys.modules):
            if name.startswith("src.components.engineering_assistant"):
                sys.modules.pop(name, None)
        import src.components.engineering_assistant as assistant

        return assistant

    def _usage(self):
        return types.SimpleNamespace(
            is_admin=False,
            remaining=100,
            allowance=200,
            warning_level="normal",
            can_use=True,
            percent_used=10,
        )

    def _render(
        self,
        *,
        session_state: dict,
        store: InMemoryCopilotStore,
        analysis_id: str = ANALYSIS_A,
        user_id: str = USER_A,
        ai_cls,
    ) -> int:
        st = install_ask_cadivor_streamlit_stub(session_state=session_state)
        assistant = self._load_assistant()
        import src.ui.navigation as navigation

        navigation.st = st
        context = MagicMock()
        context.compact.return_value = _context(analysis_id=analysis_id)
        with patch.object(assistant, "_copilot_supabase_client", return_value=store):
            with patch.object(assistant, "EngineeringAI", ai_cls):
                with patch.object(assistant, "get_ai_usage_status", return_value=self._usage()):
                    with patch.object(assistant, "_render_response_scroll_anchor"):
                        with patch.object(assistant, "_apply_copilot_query_picks"):
                            with patch.object(assistant.components, "html", MagicMock()):
                                assistant.render_engineering_assistant(
                                    current_user={"id": user_id},
                                    engineering_context=context,
                                )
        return ai_cls.ask_calls

    def test_fresh_session_restores_without_ai(self) -> None:
        store = InMemoryCopilotStore()
        from src.services.copilot_conversation_store import save_thread

        save_thread(
            store,
            user_id=USER_A,
            analysis_id=ANALYSIS_A,
            workspace_id=WORKSPACE,
            thread=[{"question": QUESTION, "answer": ANSWER, "provider_connected": True}],
        )

        class _BlockedAI:
            ask_calls = 0
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                _BlockedAI.ask_calls += 1
                return types.SimpleNamespace(answer="should-not-run", provider="openai")

        session_state = {"cadivor_active_analysis_tab": "Ask Cadivor"}
        calls = self._render(session_state=session_state, store=store, ai_cls=_BlockedAI)
        self.assertEqual(calls, 0)
        self.assertEqual(session_state["cv35_last_answer"], ANSWER)

    def test_completed_answer_persists_on_commit(self) -> None:
        store = InMemoryCopilotStore()

        class _StubAI:
            ask_calls = 0
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                _StubAI.ask_calls += 1
                return types.SimpleNamespace(answer=ANSWER, provider="openai")

        session_state = {
            "cv41_pending_manual": QUESTION,
            "cv7142_ask_inflight": True,
            "cv35_question": QUESTION,
            "cadivor_active_analysis_tab": "Ask Cadivor",
        }
        calls = self._render(session_state=session_state, store=store, ai_cls=_StubAI)
        self.assertEqual(calls, 1)
        row = store.rows[(USER_A, ANALYSIS_A)]
        self.assertEqual(row["thread"][0]["question"], QUESTION)
        self.assertEqual(row["thread"][0]["answer"], ANSWER)

    def test_write_failure_does_not_erase_current_session_answer(self) -> None:
        class _FailingStore:
            def table(self, _name: str):
                raise RuntimeError("write transport failure")

        class _StubAI:
            ask_calls = 0
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                _StubAI.ask_calls += 1
                return types.SimpleNamespace(answer=ANSWER, provider="openai")

        session_state = {
            "cv41_pending_manual": QUESTION,
            "cv7142_ask_inflight": True,
            "cv35_question": QUESTION,
            "cadivor_active_analysis_tab": "Ask Cadivor",
        }
        calls = self._render(session_state=session_state, store=_FailingStore(), ai_cls=_StubAI)
        self.assertEqual(calls, 1)
        self.assertEqual(session_state["cv35_last_answer"], ANSWER)
        self.assertEqual(session_state["cv35_last_question"], QUESTION)

    def test_normal_rerun_still_works(self) -> None:
        store = InMemoryCopilotStore()
        session_state = {
            "cv35_last_question": QUESTION,
            "cv35_last_answer": ANSWER,
            "cv36_threads": {ANALYSIS_A: [{"question": QUESTION, "answer": ANSWER}]},
            "cv724_hydrated_analysis_ids": {ANALYSIS_A: True},
            "cadivor_active_analysis_tab": "Ask Cadivor",
        }

        class _BlockedAI:
            ask_calls = 0
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                _BlockedAI.ask_calls += 1
                return types.SimpleNamespace(answer="blocked", provider="openai")

        calls = self._render(session_state=session_state, store=store, ai_cls=_BlockedAI)
        self.assertEqual(calls, 0)
        self.assertEqual(session_state["cv35_last_answer"], ANSWER)

    def test_empty_history_shows_initial_state(self) -> None:
        store = InMemoryCopilotStore()

        class _BlockedAI:
            ask_calls = 0
            configured = True

            def __init__(self, **kwargs):
                pass

            def ask(self, **kwargs):
                _BlockedAI.ask_calls += 1
                return types.SimpleNamespace(answer="blocked", provider="openai")

        session_state = {"cadivor_active_analysis_tab": "Ask Cadivor"}
        calls = self._render(session_state=session_state, store=store, ai_cls=_BlockedAI)
        self.assertEqual(calls, 0)
        self.assertNotIn("cv35_last_answer", session_state)

    def test_engineering_assistant_wires_hydrate_and_persist(self) -> None:
        assistant = self._load_assistant()
        source = inspect.getsource(assistant.render_engineering_assistant)
        self.assertIn("_restore_persisted_copilot_thread", source)
        self.assertIn("persist_thread_to_store", source)

    def test_architecture_freeze_columns_unchanged(self) -> None:
        from pathlib import Path

        assistant_source = (
            Path(__file__).resolve().parents[1] / "src/components/engineering_assistant.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_DECISION_COLUMN_RATIO = [0.85, 1.15]", assistant_source)
        self.assertIn("st.columns(_DECISION_COLUMN_RATIO", assistant_source)


def tearDownModule() -> None:
    restore_ask_cadivor_streamlit_modules()


if __name__ == "__main__":
    unittest.main()
