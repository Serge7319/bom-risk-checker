"""Signed, workspace-scoped outbound developer webhooks.

Delivery payloads are persisted before dispatch. Endpoint and signing secrets
are Fernet-encrypted at rest; request bodies are HMAC-SHA256 signed. The
delivery worker disables redirects and rejects destinations that resolve to
non-public IP addresses.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

_EVENT_TYPES = frozenset({
    "analysis.completed",
    "monitoring.alerts.created",
    "webhook.test",
})
_MAX_ATTEMPTS = 5
_RETRY_DELAYS = (60, 300, 1800, 10800)
_logger = logging.getLogger(__name__)


class DeveloperWebhookError(ValueError):
    """A webhook URL, event, or encryption configuration is invalid."""


def allowed_event_types() -> list[str]:
    return sorted(_EVENT_TYPES)


def encryption_key_configured() -> bool:
    return bool(_fernet(required=False))


def _fernet(*, required: bool = True):
    raw = (
        os.environ.get("CADIVOR_DEVELOPER_WEBHOOK_ENCRYPTION_KEY")
        or os.environ.get("CADIVOR_SLACK_WEBHOOK_ENCRYPTION_KEY")
        or ""
    ).strip()
    if not raw:
        if required:
            raise DeveloperWebhookError("Webhook encryption is not configured on Cadivor.")
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(raw.encode("ascii"))
    except Exception as exc:  # noqa: BLE001
        if required:
            raise DeveloperWebhookError("Webhook encryption is not configured correctly.") from exc
        return None


def encrypt(value: str) -> str:
    return _fernet().encrypt(str(value).encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(str(value or "").encode("ascii")).decode("utf-8")
    except DeveloperWebhookError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DeveloperWebhookError("A saved webhook credential could not be decrypted.") from exc


def validate_destination(value: str, *, resolve_dns: bool = True) -> str:
    candidate = str(value or "").strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise DeveloperWebhookError("Enter a valid HTTPS webhook URL.") from exc
    host = (parsed.hostname or "").rstrip(".").lower()
    if (
        len(candidate) > 2048
        or parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise DeveloperWebhookError("Webhook destinations must use a public HTTPS URL on port 443.")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise DeveloperWebhookError("Webhook destinations cannot use private or reserved IP addresses.")
    if resolve_dns and literal_ip is None:
        try:
            addresses = {
                ipaddress.ip_address(row[4][0].split("%", 1)[0])
                for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            }
        except (OSError, ValueError) as exc:
            raise DeveloperWebhookError("Webhook destination DNS could not be verified.") from exc
        if not addresses or any(not address.is_global for address in addresses):
            raise DeveloperWebhookError("Webhook destinations must resolve only to public IP addresses.")
    return candidate


def normalize_event_types(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise DeveloperWebhookError("Choose one or more supported webhook event types.")
    items = list(dict.fromkeys(str(item or "").strip() for item in value))
    if not items or any(item not in _EVENT_TYPES for item in items):
        raise DeveloperWebhookError("Choose one or more supported webhook event types.")
    return items


def prepare_webhook(*, workspace_id: str, created_by: str, name: str, url: str, event_types: Any) -> tuple[dict[str, Any], str]:
    clean_name = " ".join(str(name or "").split())
    if not clean_name or len(clean_name) > 80:
        raise DeveloperWebhookError("Webhook name must be 1 to 80 characters.")
    destination = validate_destination(url)
    events = normalize_event_types(event_types)
    signing_secret = "whsec_" + secrets.token_urlsafe(32)
    webhook_id = str(uuid.uuid4())
    return ({
        "id": webhook_id,
        "workspace_id": str(workspace_id),
        "created_by": str(created_by),
        "name": clean_name,
        "endpoint_ciphertext": encrypt(destination),
        "signing_secret_ciphertext": encrypt(signing_secret),
        "event_types": events,
        "active": True,
    }, signing_secret)


def public_webhook(row: dict[str, Any]) -> dict[str, Any]:
    try:
        host = urlsplit(decrypt(str(row.get("endpoint_ciphertext") or ""))).hostname or ""
    except DeveloperWebhookError:
        host = ""
    return {
        "id": str(row.get("id") or ""),
        "name": str(row.get("name") or ""),
        "destination_host": host,
        "event_types": list(row.get("event_types") or []),
        "active": row.get("active") is True,
        "created_at": _iso(row.get("created_at")),
    }


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def envelope(event_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    if event_type not in _EVENT_TYPES:
        raise DeveloperWebhookError("Unsupported webhook event type.")
    return {
        "id": str(event_id),
        "type": event_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def queue_event(
    store: Any,
    *,
    workspace_id: str,
    event_type: str,
    data: dict[str, Any],
    webhook_id: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    if event_type not in _EVENT_TYPES:
        raise DeveloperWebhookError("Unsupported webhook event type.")
    resolved_event_id = str(event_id or f"evt_{uuid.uuid4().hex}")
    payload = envelope(resolved_event_id, event_type, data)
    queued = store.queue_developer_webhook_event(
        workspace_id=str(workspace_id),
        event_id=resolved_event_id,
        event_type=event_type,
        payload=payload,
        webhook_id=webhook_id,
    )
    return {"event_id": resolved_event_id, "queued": int(queued or 0)}


def _signed_headers(*, delivery_id: str, event_type: str, secret: str, raw_body: bytes) -> dict[str, str]:
    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("ascii") + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "User-Agent": "Cadivor-Webhook/1.0",
        "X-Cadivor-Webhook-Id": delivery_id,
        "X-Cadivor-Webhook-Event": event_type,
        "X-Cadivor-Webhook-Timestamp": timestamp,
        "X-Cadivor-Webhook-Signature": f"v1={signature}",
    }


def _send(row: dict[str, Any]) -> tuple[bool, int | None, str]:
    try:
        destination = validate_destination(decrypt(str(row.get("endpoint_ciphertext") or "")))
        secret = decrypt(str(row.get("signing_secret_ciphertext") or ""))
        payload = row.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return False, None, "invalid_payload"
        raw_body = json.dumps(
            payload, separators=(",", ":"), sort_keys=True,
            ensure_ascii=False, default=str,
        ).encode("utf-8")
        import requests

        with requests.Session() as session:
            session.trust_env = False
            response = session.post(
                destination,
                data=raw_body,
                headers=_signed_headers(
                    delivery_id=str(row.get("id") or ""),
                    event_type=str(row.get("event_type") or ""),
                    secret=secret,
                    raw_body=raw_body,
                ),
                timeout=(2, 4),
                allow_redirects=False,
            )
        return (200 <= response.status_code < 300), int(response.status_code), ("http_error" if response.status_code >= 300 else "")
    except DeveloperWebhookError:
        return False, None, "destination_not_allowed"
    except Exception as exc:  # noqa: BLE001
        # Do not log endpoint URLs, response bodies, signing secrets, or exception text.
        _logger.info("developer_webhook_delivery_failed exception=%s", type(exc).__name__)
        return False, None, "delivery_error"


def dispatch_due(
    store: Any, *, workspace_id: str | None = None, webhook_id: str | None = None,
    limit: int = 100,
) -> dict[str, int]:
    rows = store.list_due_developer_webhook_deliveries(
        workspace_id=workspace_id,
        webhook_id=webhook_id,
        limit=max(1, min(int(limit), 500)),
    )
    delivered = 0
    pending = 0
    failed = 0
    for row in rows:
        success, status_code, failure_code = _send(row)
        current_attempt = int(row.get("attempt_count") or 0) + 1
        retry_delay = _RETRY_DELAYS[min(current_attempt - 1, len(_RETRY_DELAYS) - 1)]
        status = store.finish_developer_webhook_delivery(
            str(row.get("id") or ""),
            delivered=success,
            response_status=status_code,
            failure_code=failure_code,
            retry_delay_seconds=retry_delay,
            max_attempts=_MAX_ATTEMPTS,
        )
        if success:
            delivered += 1
        elif status == "failed":
            failed += 1
        else:
            pending += 1
    return {"attempted": len(rows), "delivered": delivered, "pending": pending, "failed": failed}

