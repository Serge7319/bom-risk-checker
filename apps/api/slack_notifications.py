"""Workspace-scoped Slack monitoring alerts.

Incoming webhook URLs are validated and encrypted before storage. Slack posts
contain aggregate counts and a Cadivor link only; BOM names and part numbers
are not copied into the external channel.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit


_WEBHOOK_PATH = re.compile(r"^/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")


class SlackConfigurationError(ValueError):
    """Slack integration is incomplete or has an invalid webhook URL."""


def encryption_key_configured() -> bool:
    value = (os.environ.get("CADIVOR_SLACK_WEBHOOK_ENCRYPTION_KEY") or "").strip()
    if not value:
        return False
    try:
        from cryptography.fernet import Fernet

        Fernet(value.encode("ascii"))
        return True
    except Exception:  # noqa: BLE001
        return False


def validate_webhook_url(value: str) -> str:
    candidate = str(value or "").strip()
    try:
        parsed = urlsplit(candidate)
        valid_port = parsed.port in (None, 443)
    except ValueError:
        valid_port = False
        parsed = urlsplit("")
    if (
        len(candidate) > 2048
        or len(candidate) < 50
        or parsed.scheme != "https"
        or parsed.hostname != "hooks.slack.com"
        or parsed.username
        or parsed.password
        or not valid_port
        or parsed.query
        or parsed.fragment
        or not _WEBHOOK_PATH.fullmatch(parsed.path)
    ):
        raise SlackConfigurationError("Use a valid Slack incoming webhook URL.")
    return candidate


def _fernet():
    key = (os.environ.get("CADIVOR_SLACK_WEBHOOK_ENCRYPTION_KEY") or "").strip()
    if not key:
        raise SlackConfigurationError("Slack webhook encryption is not configured on Cadivor.")
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode("ascii"))
    except Exception as exc:  # noqa: BLE001
        raise SlackConfigurationError("Slack webhook encryption is not configured correctly.") from exc


def encrypt_webhook_url(value: str) -> str:
    url = validate_webhook_url(value)
    return _fernet().encrypt(url.encode("utf-8")).decode("ascii")


def decrypt_webhook_url(ciphertext: str) -> str:
    try:
        value = _fernet().decrypt(str(ciphertext or "").encode("ascii")).decode("utf-8")
        return validate_webhook_url(value)
    except SlackConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SlackConfigurationError("Saved Slack connection could not be decrypted.") from exc


def deliver_workspace_alert(ciphertext: str, alerts: list[dict]) -> bool:
    """Send a privacy-preserving aggregate notification to one workspace's channel."""
    url = decrypt_webhook_url(ciphertext)
    alert_count = len(alerts)
    if alert_count <= 0:
        return True
    analyses = {
        str(alert.get("analysis_id") or "")
        for alert in alerts
        if str(alert.get("analysis_id") or "")
    }
    analysis_count = max(1, len(analyses))
    payload = {
        "text": (
            f"Cadivor monitoring found {alert_count} new alert"
            f"{'' if alert_count == 1 else 's'} across {analysis_count} monitored BOM"
            f"{'' if analysis_count == 1 else 's'}. "
            "Review the evidence in Cadivor: https://app.cadivor.com/monitoring"
        )
    }
    try:
        import requests

        response = requests.post(
            url,
            json=payload,
            timeout=8,
            allow_redirects=False,
        )
        return response.status_code == 200
    except Exception:  # noqa: BLE001
        return False
