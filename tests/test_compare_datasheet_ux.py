"""UX regressions for Compare Parts, Datasheet Q&A, and auth re-entry."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.datasheet_qa import (
    DATASHEET_QA_DOC_KEY,
    DATASHEET_QA_STATUS_KEY,
    DATASHEET_QA_THREAD_KEY,
    NOT_FOUND_ANSWER,
    STATUS_PROCESSING,
    STATUS_READY,
    answer_datasheet_question,
    append_thread_turn,
    claim_datasheet_question_submit,
    clear_datasheet_document,
    compact_datasheet_history,
    extract_uploaded_datasheet,
    resolve_datasheet_question,
    store_document_in_session,
)
from src.parts_compare import (
    COMPARE_PARTS_RESULT_KEY,
    STATUS_RUNNING,
    claim_compare_parts_submit,
    resolve_compare_parts_submitted_mpn,
)
from tests.test_datasheet_qa import _text_pdf_bytes


ROOT = Path(__file__).resolve().parents[1]
COMPARE_PAGE = (ROOT / "src" / "pages" / "compare_parts.py").read_text(encoding="utf-8")
DATASHEET_PAGE = (ROOT / "src" / "pages" / "datasheet_qa.py").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "src" / "auth_bootstrap.py").read_text(encoding="utf-8")
STREAMLIT_APP = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")


class ComparePartsSubmitUxTests(unittest.TestCase):
    def test_first_click_resolves_widget_when_form_return_empty(self):
        resolved_a = resolve_compare_parts_submitted_mpn("", "LM358N")
        resolved_b = resolve_compare_parts_submitted_mpn("", "LM358P")
        self.assertEqual(resolved_a, "LM358N")
        self.assertEqual(resolved_b, "LM358P")

    def test_enter_submit_contract_uses_form_and_resolve(self):
        self.assertIn('st.form("compare_parts_form"', COMPARE_PAGE)
        self.assertIn("form_submit_button", COMPARE_PAGE)
        self.assertIn("resolve_compare_parts_submitted_mpn", COMPARE_PAGE)
        self.assertIn("COMPARE_PARTS_PART_A_WIDGET_KEY", COMPARE_PAGE)
        self.assertIn("COMPARE_PARTS_PART_B_WIDGET_KEY", COMPARE_PAGE)
        self.assertIn("Enter both Part A and Part B", COMPARE_PAGE)

    def test_duplicate_click_suppressed_while_identical_in_flight(self):
        session = {
            COMPARE_PARTS_RESULT_KEY: {
                "status": STATUS_RUNNING,
                "part_a": "AAA",
                "part_b": "BBB",
            }
        }
        self.assertFalse(claim_compare_parts_submit(session, "AAA", "BBB", now=100.0))
        # Different pair still allowed.
        self.assertTrue(claim_compare_parts_submit(session, "AAA", "CCC", now=100.0))

    def test_rapid_duplicate_after_claim_is_debounced(self):
        session = {}
        self.assertTrue(claim_compare_parts_submit(session, "AAA", "BBB", now=50.0))
        self.assertFalse(claim_compare_parts_submit(session, "AAA", "BBB", now=50.5))
        self.assertTrue(claim_compare_parts_submit(session, "AAA", "BBB", now=53.0))

    def test_no_full_width_primary_submit_bar(self):
        self.assertIn("use_container_width=False", COMPARE_PAGE)
        self.assertIn("cadivor_button_wrap(\"primary\")", COMPARE_PAGE)
        self.assertIn("cp-compare-card", COMPARE_PAGE)
        self.assertNotRegex(
            COMPARE_PAGE,
            r'form_submit_button\(\s*"Compare Parts[^"]*"\s*,\s*type="primary"\s*,\s*use_container_width=True',
        )


class DatasheetQaWorkspaceUxTests(unittest.TestCase):
    def test_resolve_question_prefers_widget_on_empty_form_return(self):
        self.assertEqual(
            resolve_datasheet_question("", "What is VCC?"),
            "What is VCC?",
        )

    def test_upload_then_two_sequential_questions_without_reupload(self):
        session = {}
        document = extract_uploaded_datasheet(
            _text_pdf_bytes(
                [
                    "Absolute maximum VCC is 5.5 V.",
                    "Operating temperature range is -40 C to 85 C.",
                ]
            ),
            filename="spec.pdf",
        )
        store_document_in_session(session, document)
        self.assertTrue(session[DATASHEET_QA_DOC_KEY]["available"])

        first = answer_datasheet_question(document, "What is the absolute maximum VCC?")
        self.assertTrue(first["ok"])
        append_thread_turn(session, question="What is the absolute maximum VCC?", result=first)
        session[DATASHEET_QA_STATUS_KEY] = STATUS_READY

        self.assertTrue(
            claim_datasheet_question_submit(
                session, "What is the operating temperature range?", now=200.0
            )
        )
        second = answer_datasheet_question(
            document,
            "What is the operating temperature range?",
            history=compact_datasheet_history(session[DATASHEET_QA_THREAD_KEY]),
        )
        self.assertTrue(second["ok"])
        append_thread_turn(
            session,
            question="What is the operating temperature range?",
            result=second,
        )

        self.assertEqual(len(session[DATASHEET_QA_THREAD_KEY]), 2)
        self.assertTrue(session[DATASHEET_QA_DOC_KEY]["available"])
        self.assertTrue(session[DATASHEET_QA_THREAD_KEY][0]["citations"])
        self.assertTrue(session[DATASHEET_QA_THREAD_KEY][1]["citations"])

    def test_duplicate_question_click_suppressed_while_processing(self):
        session = {DATASHEET_QA_STATUS_KEY: STATUS_PROCESSING}
        self.assertFalse(claim_datasheet_question_submit(session, "What is VCC?", now=10.0))

    def test_different_question_works_immediately_after_ready(self):
        session = {}
        self.assertTrue(claim_datasheet_question_submit(session, "Q1 about voltage", now=1.0))
        session[DATASHEET_QA_STATUS_KEY] = STATUS_READY
        self.assertTrue(
            claim_datasheet_question_submit(session, "Q2 about temperature", now=1.1)
        )

    def test_remove_document_clears_conversation(self):
        session = {
            DATASHEET_QA_DOC_KEY: {"available": True, "filename": "a.pdf"},
            DATASHEET_QA_THREAD_KEY: [{"question": "Q", "answer": "A"}],
            DATASHEET_QA_STATUS_KEY: STATUS_READY,
        }
        clear_datasheet_document(session)
        self.assertNotIn(DATASHEET_QA_DOC_KEY, session)
        self.assertNotIn(DATASHEET_QA_THREAD_KEY, session)

    def test_customer_copy_excludes_implementation_terms(self):
        # Customer-facing string literals only (ignore imports/helpers).
        literals = re.findall(r'["\']([^"\']{3,})["\']', DATASHEET_PAGE)
        joined = " ".join(literals).casefold()
        for term in ("chunk", "retrieval", "prompt", "model", "context", "diagnostic", "embedding"):
            self.assertNotIn(term, joined)

    def test_product_language_and_normal_ask_button(self):
        self.assertIn("Ask about this datasheet", DATASHEET_PAGE)
        self.assertIn("Ask another question", DATASHEET_PAGE)
        self.assertIn("Sources:", DATASHEET_PAGE)
        self.assertIn("NOT_FOUND_ANSWER", DATASHEET_PAGE)
        self.assertEqual(NOT_FOUND_ANSWER, "Not found in this datasheet.")
        self.assertIn('st.form_submit_button(\n                "Ask"', DATASHEET_PAGE)
        self.assertIn("use_container_width=False", DATASHEET_PAGE)
        self.assertIn("dq-doc-card", DATASHEET_PAGE)
        self.assertIn("dq-thread-card", DATASHEET_PAGE)
        self.assertIn("DATASHEET_QA_CLEAR_QUESTION_KEY", DATASHEET_PAGE)
        self.assertIn("DATASHEET_QA_QUESTION_WIDGET_KEY", DATASHEET_PAGE)
        self.assertIn("resolve_datasheet_question", DATASHEET_PAGE)

    def test_chronological_thread_not_reversed(self):
        self.assertIn("for turn in thread:", DATASHEET_PAGE)
        self.assertNotIn("reversed(thread)", DATASHEET_PAGE)


class AuthReentryShellTests(unittest.TestCase):
    def test_cold_authenticated_entry_shell_is_marked_before_auth_surface_clear(self):
        self.assertIn("mark_authenticated_entry_shell", BOOTSTRAP)
        self.assertIn("AUTH_ENTRY_SHELL_KEY", BOOTSTRAP)
        self.assertIn("Restoring your workspace", BOOTSTRAP)
        clear_idx = BOOTSTRAP.index("auth_surface_host.empty()")
        mark_idx = BOOTSTRAP.rfind("mark_authenticated_entry_shell", 0, clear_idx)
        self.assertGreater(mark_idx, 0)
        self.assertLess(mark_idx, clear_idx)

    def test_startup_shell_covers_entry_and_login_handoff(self):
        self.assertIn("AUTH_ENTRY_SHELL_KEY", BOOTSTRAP)
        self.assertIn("should_render_authenticated_startup_shell", STREAMLIT_APP)
        self.assertIn("render_startup_loading_shell", STREAMLIT_APP)
        self.assertIn("login_handoff_message()", STREAMLIT_APP)

    def test_clear_login_handoff_also_clears_entry_shell(self):
        self.assertIn("clear_authenticated_entry_shell()", BOOTSTRAP)
        block = BOOTSTRAP[
            BOOTSTRAP.index("def clear_login_handoff()") : BOOTSTRAP.index(
                "def login_handoff_timed_out()"
            )
        ]
        self.assertIn("clear_authenticated_entry_shell()", block)
        self.assertIn("LOGIN_HANDOFF_ACTIVE_KEY", block)

    def test_unauthenticated_login_still_uses_auth_surface_host(self):
        self.assertIn("with auth_surface_host.container():", BOOTSTRAP)
        self.assertIn("show_auth_ui(supabase, cookie_manager)", BOOTSTRAP)


class CustomerCopySanityTests(unittest.TestCase):
    def test_compare_parts_never_calls_direct_substitute(self):
        # Explicit product copy forbids the supplier Direct substitute label.
        self.assertIn("never labels either part as a Direct substitute", COMPARE_PAGE)
        # Ensure we do not present a Direct substitute badge/claim in the UI copy.
        self.assertNotRegex(COMPARE_PAGE, r'(?<!as a )Direct substitute')

    def test_not_found_copy_is_plain_language(self):
        self.assertEqual(NOT_FOUND_ANSWER, "Not found in this datasheet.")
        self.assertNotIn("chunk", NOT_FOUND_ANSWER.casefold())


if __name__ == "__main__":
    unittest.main()
