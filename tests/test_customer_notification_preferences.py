"""Contracts for independent, database-backed Settings notification toggles."""
from __future__ import annotations

from types import SimpleNamespace

from src.customer_profile_service import (
    notification_preferences_from_record,
    update_user_preferences,
)


class _Query:
    def __init__(self, response):
        self.response = response
        self.payload = None

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=[self.payload])


class _Supabase:
    def __init__(self):
        self.query = _Query(None)

    def table(self, _name):
        return self.query


def test_notification_preferences_fall_back_to_legacy_account_flags():
    assert notification_preferences_from_record({
        "workspace_notifications": False,
        "report_notifications": False,
        "email_notifications": False,
    }) == {
        "project_activity": False,
        "simulation_results": False,
        "team_activity": False,
        "product_updates": False,
        "marketing_emails": False,
    }


def test_independent_preferences_override_legacy_flags_and_parse_false_strings():
    assert notification_preferences_from_record({
        "workspace_notifications": True,
        "notification_preferences": {
            "project_activity": False,
            "team_activity": True,
            "marketing_emails": "false",
        },
    }) == {
        "project_activity": False,
        "simulation_results": True,
        "team_activity": True,
        "product_updates": True,
        "marketing_emails": False,
    }


def test_notification_updates_allow_only_known_boolean_fields():
    client = _Supabase()
    _, error = update_user_preferences(client, "user-1", {
        "notification_preferences": {
            "project_activity": "false",
            "marketing_emails": True,
            "unexpected": True,
        },
    })

    assert error is None
    assert client.query.payload["notification_preferences"] == {
        "project_activity": False,
        "simulation_results": True,
        "team_activity": True,
        "product_updates": True,
        "marketing_emails": True,
    }

