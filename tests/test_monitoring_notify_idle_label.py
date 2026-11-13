"""Monitoring idle Notify label and refresh/notify separation (source contract)."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MONITORING_PAGE = ROOT / "apps" / "web" / "src" / "app" / "monitoring" / "page.tsx"


class MonitoringNotifyIdleLabelTests(unittest.TestCase):
    def test_idle_unpersisted_alerts_show_notify_not_notifying(self):
        source = MONITORING_PAGE.read_text(encoding="utf-8")
        # Idle "Notifying…" required a.id to be truthy AND notifying === that id.
        # Comparing notifying === String(a.id || "") alone matched empty ids.
        self.assertIn("a.id && notifying === String(a.id)", source)
        self.assertNotIn('notifying === String(a.id || "")', source)
        self.assertIn("Notifying…", source)
        self.assertIn('"Notify"', source)
        # Ensure Notifying is gated on a real alert id, not idle empty-string equality.
        notifying_idx = source.index("Notifying…")
        gate = source[max(0, notifying_idx - 120) : notifying_idx]
        self.assertIn("a.id && notifying === String(a.id)", gate)

    def test_refresh_note_and_notify_are_explicit_and_separated(self):
        source = MONITORING_PAGE.read_text(encoding="utf-8")
        self.assertIn("Email was not sent — use Notify for delivery.", source)
        self.assertIn("Explicit email action — not run by Refresh", source)
        self.assertIn("refreshMonitoring(", source)
        self.assertIn("notifyMonitoringAlert(", source)
        self.assertIn("Refresh never sends email.", source)
        # Notify is disabled without a persisted alert id.
        self.assertIn("disabled={!a.id || Boolean(notifying)}", source)


if __name__ == "__main__":
    unittest.main()
