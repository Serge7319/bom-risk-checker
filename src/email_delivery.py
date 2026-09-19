"""Transactional email delivery for Cadivor-owned application actions."""
from __future__ import annotations

import html
import re
from typing import Any

from src.email_routing import (
    DEFAULT_REPLY_TO,
    DEFAULT_TRANSACTIONAL_FROM,
    SUPPORT_EMAIL,
)
from src.secrets import get_secret
from src.urls import app_url


class EmailDeliveryError(RuntimeError):
    """Raised when a Cadivor transactional message cannot be submitted."""


def _clean_recipient(value: str) -> str:
    recipient = str(value or "").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
        raise EmailDeliveryError("A valid recipient email address is required.")
    return recipient


def transactional_sender() -> str:
    """Resolve the verified-domain sender without using Resend's sandbox."""
    return str(
        get_secret(
            "TRANSACTIONAL_FROM_EMAIL",
            default=get_secret(
                "CADIVOR_FROM_EMAIL",
                default=get_secret(
                    "ALERT_FROM_EMAIL",
                    default=DEFAULT_TRANSACTIONAL_FROM,
                ),
            ),
        )
        or DEFAULT_TRANSACTIONAL_FROM
    ).strip()


def reply_to_address() -> str:
    return str(
        get_secret("EMAIL_REPLY_TO", default=DEFAULT_REPLY_TO)
        or DEFAULT_REPLY_TO
    ).strip()


def email_delivery_configured() -> bool:
    """Return whether the app has the minimum Resend configuration.

    Domain verification remains a provider-side check, but this prevents the
    workspace UI from offering email actions when no API key or sender exists.
    """
    try:
        api_key = str(get_secret("RESEND_API_KEY", default="") or "").strip()
        sender = transactional_sender()
        return bool(api_key and sender)
    except Exception:
        return False


def send_transactional_email(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    from_email: str | None = None,
    reply_to: str | None = None,
) -> Any:
    """Submit one transactional message through Resend.

    Configuration is intentionally resolved at call time so Railway and local
    Streamlit secrets behave consistently. No recipient or secret is logged.
    """
    recipient = _clean_recipient(to_email)
    clean_subject = str(subject or "").strip()
    if not clean_subject:
        raise EmailDeliveryError("An email subject is required.")

    try:
        import resend

        resend.api_key = get_secret("RESEND_API_KEY", required=True)
        payload: dict[str, Any] = {
            "from": str(from_email or transactional_sender()).strip(),
            "to": [recipient],
            "subject": clean_subject,
            "html": str(html_body or ""),
            "reply_to": str(reply_to or reply_to_address()).strip(),
        }
        if text_body:
            payload["text"] = str(text_body)
        return resend.Emails.send(payload)
    except EmailDeliveryError:
        raise
    except Exception as exc:
        raise EmailDeliveryError(
            "Cadivor could not submit the email to its delivery provider."
        ) from exc


def send_workspace_invitation_email(
    *,
    to_email: str,
    workspace_name: str,
    invited_by_name: str,
    role: str,
) -> Any:
    """Send an invitation that opens Cadivor's authenticated Workspace page."""
    recipient = _clean_recipient(to_email)
    safe_workspace = html.escape(str(workspace_name or "Cadivor Workspace").strip())
    safe_inviter = html.escape(str(invited_by_name or "A workspace owner").strip())
    safe_role = html.escape(str(role or "engineer").strip().title())
    invite_url = app_url(
        "",
        page="Workspace",
        auth="signup",
        source="workspace-invitation",
    )
    safe_url = html.escape(invite_url, quote=True)
    html_body = f"""
    <div style="font-family:Arial,sans-serif;color:#0f172a;line-height:1.55;max-width:620px">
      <p style="font-size:12px;font-weight:700;letter-spacing:.1em;color:#2563eb">CADIVOR WORKSPACE</p>
      <h1 style="font-size:26px;margin:0 0 16px">You have been invited to {safe_workspace}</h1>
      <p>{safe_inviter} invited you to join as <strong>{safe_role}</strong>.</p>
      <p>Use <strong>{html.escape(recipient)}</strong> when you sign in or create your Cadivor account.</p>
      <p style="margin:28px 0">
        <a href="{safe_url}" style="background:#2563eb;color:#fff;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:700">Open Cadivor</a>
      </p>
      <p style="color:#64748b;font-size:13px">If you were not expecting this invitation, you can ignore this email or contact {html.escape(SUPPORT_EMAIL)}.</p>
    </div>
    """
    text_body = (
        f"{invited_by_name or 'A workspace owner'} invited you to "
        f"{workspace_name or 'Cadivor Workspace'} as {str(role or 'engineer').title()}. "
        f"Use {recipient} to sign in: {invite_url}"
    )
    return send_transactional_email(
        to_email=recipient,
        subject=f"Invitation to join {workspace_name or 'Cadivor Workspace'} in Cadivor",
        html_body=html_body,
        text_body=text_body,
    )
