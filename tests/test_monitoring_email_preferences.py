import types
import unittest

from src.monitoring_email_preferences import monitoring_email_enabled


class _PreferenceQuery:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self.error:
            raise self.error
        return types.SimpleNamespace(data=self.rows)


class _PreferenceClient:
    def __init__(self, rows=None, error=None):
        self.query = _PreferenceQuery(rows=rows, error=error)
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return self.query


class MonitoringEmailPreferenceTests(unittest.TestCase):
    def test_both_email_toggles_must_be_enabled(self):
        allowed, error = monitoring_email_enabled(
            _PreferenceClient(
                [{"email_notifications": True, "monitoring_notifications": True}]
            ),
            "user-1",
        )
        self.assertTrue(allowed)
        self.assertIsNone(error)

        for row in (
            {"email_notifications": False, "monitoring_notifications": True},
            {"email_notifications": True, "monitoring_notifications": False},
            {"email_notifications": False, "monitoring_notifications": False},
        ):
            with self.subTest(row=row):
                allowed, error = monitoring_email_enabled(
                    _PreferenceClient([row]),
                    "user-1",
                )
                self.assertFalse(allowed)
                self.assertIsNone(error)

    def test_missing_preference_row_uses_documented_opt_in_default(self):
        client = _PreferenceClient([])
        allowed, error = monitoring_email_enabled(client, "user-2")
        self.assertEqual(client.table_name, "user_preferences")
        self.assertTrue(allowed)
        self.assertIsNone(error)

    def test_preference_read_failure_fails_closed(self):
        allowed, error = monitoring_email_enabled(
            _PreferenceClient(error=RuntimeError("database unavailable")),
            "user-3",
        )
        self.assertFalse(allowed)
        self.assertEqual(error, "database unavailable")


if __name__ == "__main__":
    unittest.main()
