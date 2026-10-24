from __future__ import annotations

import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
import sys
import types

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    # This unit test never performs network I/O. The repository read wrapper
    # only needs exception types so its transport-retry imports can load.
    _httpx_stub = types.ModuleType("httpx")
    for _name in (
        "RemoteProtocolError", "ConnectError", "ReadTimeout", "WriteTimeout",
        "PoolTimeout", "TransportError",
    ):
        setattr(_httpx_stub, _name, type(_name, (Exception,), {}))
    sys.modules["httpx"] = _httpx_stub

from src.decision_repository import load_decision_state
from src.ui.decision_workspace.records import (
    normalize_due_date,
    recommendation_decision_key,
    recommendation_record_payload,
    render_recommendation_records,
)
from src.ui.decision_workspace.components import recommendation_details


ACTION = {
    "part_number": "TPS5430DDAR",
    "category": "Supply Coverage",
    "title": "Confirm the synthetic supplier gap",
    "action": "Confirm the immediate supply gap",
    "reason": "Saved supplier signals conflict.",
    "evidence": "Partial supplier coverage in the synthetic analysis.",
    "expected_result": "Documented review outcome.",
    "score": 74,
    "confidence": "74%",
    "owner": "Component Engineering",
}


class _Query:
    def __init__(self, database, table_name):
        self.database = database
        self.table_name = table_name
        self.filters = {}
        self.keys = None
        self.payload = None
        self.mode = "select"

    def select(self, *_args):
        self.mode = "select"
        return self

    def eq(self, name, value):
        self.filters[name] = value
        return self

    def in_(self, name, values):
        self.keys = {str(value) for value in values}
        return self

    def order(self, *_args, **_kwargs):
        return self

    def upsert(self, payload, *, on_conflict):
        self.mode = "upsert"
        self.payload = dict(payload)
        self.conflict = on_conflict
        return self

    def insert(self, payload):
        self.mode = "insert"
        self.payload = dict(payload)
        return self

    def execute(self):
        rows = self.database.tables.setdefault(self.table_name, [])
        if self.mode == "upsert":
            key = (self.payload.get("user_id"), self.payload.get("scope_key"), self.payload.get("decision_key"))
            for index, row in enumerate(rows):
                row_key = (row.get("user_id"), row.get("scope_key"), row.get("decision_key"))
                if row_key == key:
                    rows[index] = {**row, **self.payload}
                    return SimpleNamespace(data=[rows[index]])
            rows.append(self.payload)
            return SimpleNamespace(data=[self.payload])
        if self.mode == "insert":
            rows.append(self.payload)
            return SimpleNamespace(data=[self.payload])
        result = [
            row for row in rows
            if all(row.get(name) == value for name, value in self.filters.items())
            and (self.keys is None or str(row.get("decision_key")) in self.keys)
        ]
        return SimpleNamespace(data=result)


class _Supabase:
    def __init__(self):
        self.tables = {
            "engineering_decisions": [{
                "user_id": "user-test",
                "scope_key": "workspace-test",
                "decision_key": "another-analysis:unrelated",
                "part_number": "UNRELATED-SYNTHETIC-MPN",
                "status": "Released",
                "assigned_owner": "Unrelated",
            }],
            "engineering_decision_notes": [],
            "engineering_decision_events": [],
        }

    def table(self, name):
        return _Query(self, name)


class _Rerun(Exception):
    pass


class _FakeStreamlit(types.ModuleType):
    def __init__(self, *, submit=False):
        super().__init__("streamlit")
        self.submit = submit
        self.text_values = []
        self.messages = []

    def markdown(self, value, **_kwargs):
        self.messages.append(str(value))

    def caption(self, value):
        self.messages.append(str(value))

    def warning(self, value):
        self.messages.append(str(value))

    def info(self, value):
        self.messages.append(str(value))

    def error(self, value):
        self.messages.append(str(value))

    def success(self, value):
        self.messages.append(str(value))

    def text(self, value):
        self.text_values.append(str(value))

    def expander(self, *_args, **_kwargs):
        return nullcontext()

    def form(self, *_args, **_kwargs):
        return nullcontext()

    def selectbox(self, _label, options, **_kwargs):
        return "In Progress" if "In Progress" in options else options[0]

    def text_input(self, label, **_kwargs):
        if label == "Owner":
            return "QA Engineering"
        if label.startswith("Due date"):
            return "2026-10-26"
        return ""

    def text_area(self, *_args, **_kwargs):
        return "TEST: synthetic decision persistence check"

    def form_submit_button(self, *_args, **_kwargs):
        return self.submit

    def rerun(self):
        raise _Rerun()


class RecommendationDecisionRecordTests(unittest.TestCase):
    def test_recommendation_details_do_not_offer_browser_only_record_controls(self):
        html = recommendation_details(ACTION)
        self.assertNotIn("data-cv70-workflow-state", html)
        self.assertNotIn("data-cv70-notes-save", html)
        self.assertNotIn('data-cv70-action="approve"', html)

    def test_key_is_stable_and_scoped_to_analysis_and_recommendation(self):
        key = recommendation_decision_key("analysis-test", ACTION)
        self.assertEqual(key, recommendation_decision_key("analysis-test", dict(ACTION)))
        self.assertNotEqual(key, recommendation_decision_key("other-analysis", ACTION))
        self.assertNotEqual(
            key,
            recommendation_decision_key("analysis-test", {**ACTION, "part_number": "TPS5431DDAR"}),
        )

    def test_payload_keeps_status_owner_due_date_and_evidence(self):
        key = recommendation_decision_key("analysis-test", ACTION)
        payload = recommendation_record_payload(
            "analysis-test",
            ACTION,
            decision_key=key,
            status="In Progress",
            owner="QA Engineering",
            due_date="2026-10-26",
        )
        self.assertEqual(payload["decision_id"], key)
        self.assertEqual(payload["analysis_id"], "analysis-test")
        self.assertEqual(payload["part_number"], "TPS5430DDAR")
        self.assertEqual(payload["confidence"], 74)
        self.assertIn("supplier signals conflict", payload["rationale"])

    def test_due_date_is_validated_before_database_write(self):
        self.assertEqual(normalize_due_date("2026-10-26"), ("2026-10-26", None))
        self.assertIsNotNone(normalize_due_date("Monday")[1])
        self.assertEqual(normalize_due_date(""), (None, None))

    def test_save_and_reopen_preserves_status_note_and_scoped_history(self):
        database = _Supabase()
        key = recommendation_decision_key("analysis-test", ACTION)
        submitting_st = _FakeStreamlit(submit=True)
        with patch.dict(sys.modules, {"streamlit": submitting_st}):
            with self.assertRaises(_Rerun):
                render_recommendation_records(
                    [ACTION],
                    supabase=database,
                    user_id="user-test",
                    workspace_id="workspace-test",
                    analysis_id="analysis-test",
                    actor_name="Synthetic QA",
                )

        reopened_state, error = load_decision_state(
            database,
            user_id="user-test",
            workspace_id="workspace-test",
            decision_keys=[key],
        )
        self.assertIsNone(error)
        self.assertEqual(reopened_state[key]["status"], "In Progress")
        self.assertEqual(reopened_state[key]["owner"], "QA Engineering")
        self.assertEqual(reopened_state[key]["due_date"], "2026-10-26")
        self.assertEqual(
            reopened_state[key]["notes"][0]["text"],
            "TEST: synthetic decision persistence check",
        )
        self.assertEqual(len(reopened_state[key]["history"]), 2)

        reopened_st = _FakeStreamlit(submit=False)
        with patch.dict(sys.modules, {"streamlit": reopened_st}):
            render_recommendation_records(
                [ACTION],
                supabase=database,
                user_id="user-test",
                workspace_id="workspace-test",
                analysis_id="analysis-test",
                actor_name="Synthetic QA",
            )
        self.assertTrue(any("TEST: synthetic decision persistence check" in value for value in reopened_st.text_values))
        self.assertFalse(any("UNRELATED-SYNTHETIC-MPN" in value for value in reopened_st.text_values))


if __name__ == "__main__":
    unittest.main()
