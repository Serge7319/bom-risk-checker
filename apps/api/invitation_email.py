"""Invitation email delivery for the Next API.

Delivery goes through ``src.email_delivery`` (Resend, ``RESEND_API_KEY`` +
``TRANSACTIONAL_FROM_EMAIL``) exactly like the Streamlit invite flow. Tests
install an in-memory sink with ``set_email_sink`` so no real Resend request is
ever made; the sink receives the same message the provider would.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

EmailSink = Callable[[dict[str, Any]], None]

_SINK: EmailSink | None = None


class InvitationEmailError(RuntimeError):
    """Raised when an invitation email cannot be submitted."""


@dataclass
class MemoryEmailSink:
    """Collects messages instead of sending them (tests / local previews)."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    def __call__(self, message: dict[str, Any]) -> None:
        if self.fail:
            raise InvitationEmailError("Sink configured to fail")
        self.messages.append(dict(message))

    def clear(self) -> None:
        self.messages.clear()


def set_email_sink(sink: EmailSink | None) -> None:
    """Install (or clear) the process-wide sink that replaces Resend."""
    global _SINK
    _SINK = sink


def active_sink() -> EmailSink | None:
    return _SINK


def delivery_mode() -> str:
    """``sink`` | ``resend`` | ``unconfigured`` (never exposes secret values)."""
    if _SINK is not None:
        return "sink"
    try:
        from src.email_delivery import email_delivery_configured

        return "resend" if email_delivery_configured() else "unconfigured"
    except Exception:  # noqa: BLE001
        return "unconfigured"


def delivery_ready() -> bool:
    return delivery_mode() != "unconfigured"


def send_workspace_invitation(
    *,
    to_email: str,
    workspace_name: str,
    invited_by_name: str,
    role: str,
    invite_url: str,
) -> dict[str, Any]:
    """Send one invitation email; raises ``InvitationEmailError`` on failure."""
    sink = _SINK
    if sink is not None:
        sink(
            {
                "kind": "workspace_invitation",
                "to": to_email,
                "workspace_name": workspace_name,
                "invited_by_name": invited_by_name,
                "role": role,
                "invite_url": invite_url,
            }
        )
        return {"mode": "sink"}
    try:
        from src.email_delivery import (
            EmailDeliveryError,
            send_workspace_invitation_email,
        )

        send_workspace_invitation_email(
            to_email=to_email,
            workspace_name=workspace_name,
            invited_by_name=invited_by_name,
            role=role,
            invite_url=invite_url,
        )
    except EmailDeliveryError as exc:
        raise InvitationEmailError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise InvitationEmailError(
            "Cadivor could not submit the email to its delivery provider."
        ) from exc
    return {"mode": "resend"}
