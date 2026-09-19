"""Cadivor inbound and transactional email routing.

Inbox map:
  info@     — general inquiries, demos, student requests
  beta@     — beta invitations and blocker reports
  support@  — customer help
  security@ — responsible disclosure
  legal@    — legal / terms / privacy inquiries
  billing@  — Stripe billing support

Transactional mail (invites, monitoring) uses Resend with CADIVOR_FROM_EMAIL
(or ALERT_FROM_EMAIL) as the verified sender identity.
"""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote

INFO_EMAIL = "info@cadivor.com"
GENERAL_EMAIL = INFO_EMAIL
BETA_EMAIL = "beta@cadivor.com"
SUPPORT_EMAIL = "support@cadivor.com"
SECURITY_EMAIL = "security@cadivor.com"
LEGAL_EMAIL = "legal@cadivor.com"
BILLING_EMAIL = "billing@cadivor.com"
SALES_EMAIL = "sales@cadivor.com"
CAREERS_EMAIL = "careers@cadivor.com"
HELLO_EMAIL = "hello@cadivor.com"

DEFAULT_TRANSACTIONAL_FROM = "Cadivor <no-reply@cadivor.com>"
DEFAULT_ALERT_FROM = "Cadivor Alerts <no-reply@cadivor.com>"
DEFAULT_REPLY_TO = SUPPORT_EMAIL
DEFAULT_FROM_EMAIL = DEFAULT_TRANSACTIONAL_FROM

# Public intent / topic keys → destination inbox.
INBOX_BY_INTENT: dict[str, str] = {
    "general": INFO_EMAIL,
    "inquiry": INFO_EMAIL,
    "demo": INFO_EMAIL,
    "student": INFO_EMAIL,
    "enterprise": INFO_EMAIL,
    "sales": INFO_EMAIL,
    "beta": BETA_EMAIL,
    "blocker": BETA_EMAIL,
    "support": SUPPORT_EMAIL,
    "help": SUPPORT_EMAIL,
    "product": SUPPORT_EMAIL,
    "security": SECURITY_EMAIL,
    "disclosure": SECURITY_EMAIL,
    "responsible-disclosure": SECURITY_EMAIL,
    "legal": LEGAL_EMAIL,
    "terms": LEGAL_EMAIL,
    "privacy": LEGAL_EMAIL,
    "billing": BILLING_EMAIL,
    "stripe": BILLING_EMAIL,
}

CONTACT_TOPIC_OPTIONS: tuple[tuple[str, str], ...] = (
    ("general", "General inquiry"),
    ("demo", "Book a product demo"),
    ("student", "Student plan request"),
    ("beta", "Beta invitation / access"),
    ("blocker", "Product blocker report"),
    ("support", "Customer help / product support"),
    ("billing", "Billing / Stripe support"),
    ("security", "Security / responsible disclosure"),
    ("legal", "Legal / terms / privacy"),
)


def normalize_intent(intent: str | None) -> str:
    key = str(intent or "").strip().lower().replace(" ", "-")
    if key in INBOX_BY_INTENT:
        return key
    return "general"


def resolve_inbox(intent: str | None) -> str:
    """Return the Cadivor inbox for a public contact intent."""
    return INBOX_BY_INTENT[normalize_intent(intent)]


def mailto_href(
    intent: str | None,
    *,
    subject: str,
    body: str = "",
) -> str:
    """Build a mailto: URL aimed at the correct Cadivor inbox."""
    to = resolve_inbox(intent)
    query = f"subject={quote(str(subject or '').strip())}"
    body_text = str(body or "").strip()
    if body_text:
        query = f"{query}&body={quote(body_text)}"
    return f"mailto:{to}?{query}"


def mailto(address: str, *, subject: str = "") -> str:
    """Build a mailto URL for an already-resolved address."""
    clean_address = str(address or "").strip()
    clean_subject = str(subject or "").strip()
    if not clean_subject:
        return f"mailto:{clean_address}"
    return f"mailto:{clean_address}?subject={quote(clean_subject)}"


def transactional_from_email() -> str:
    """Verified Resend From identity for Cadivor-originated mail."""
    from src.secrets import get_secret

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


def send_resend_email(
    *,
    to_email: str,
    subject: str,
    html: str,
    from_email: str | None = None,
) -> Mapping[str, Any] | None:
    """Send one transactional email through Resend.

    Raises ValueError when RESEND_API_KEY is missing. Callers that must not
    fail the primary action (e.g. invite persistence) should catch exceptions.
    """
    import resend

    from src.secrets import get_secret

    api_key = get_secret("RESEND_API_KEY", required=True)
    if not api_key:
        raise ValueError("Missing RESEND_API_KEY in configuration")
    resend.api_key = api_key
    recipient = str(to_email or "").strip()
    if not recipient or "@" not in recipient:
        raise ValueError("A valid recipient email is required")
    return resend.Emails.send(
        {
            "from": str(from_email or transactional_from_email()).strip(),
            "to": [recipient],
            "subject": str(subject or "").strip() or "Cadivor",
            "html": str(html or "").strip() or "<p></p>",
        }
    )


def workspace_invite_email_html(
    *,
    invitee_email: str,
    role: str,
    invited_by_name: str,
    workspace_label: str,
    accept_url: str,
) -> str:
    safe_role = str(role or "engineer").strip().title() or "Engineer"
    inviter = str(invited_by_name or "A Cadivor teammate").strip() or "A Cadivor teammate"
    workspace = str(workspace_label or "a Cadivor workspace").strip()
    link = str(accept_url or "").strip()
    return (
        f"<p>You have been invited to join <strong>{workspace}</strong> "
        f"as <strong>{safe_role}</strong>.</p>"
        f"<p>Invited by: {inviter}<br/>Invitation email: {invitee_email}</p>"
        f"<p><a href=\"{link}\">Open Cadivor to accept this invitation</a></p>"
        "<p>If you did not expect this invitation, you can ignore this email.</p>"
    )
