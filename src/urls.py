"""Central Cadivor URL configuration and link builders."""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, urlencode


def _normalize_origin(value: str, default: str) -> str:
    candidate = str(value or default or "").strip()
    if not candidate:
        candidate = default
    return candidate.rstrip("/")


CADIVOR_MARKETING_ORIGIN = _normalize_origin(
    os.getenv(
        "CADIVOR_MARKETING_ORIGIN",
        os.getenv("CADIVOR_MARKETING_URL", "https://www.cadivor.com"),
    ),
    "https://www.cadivor.com",
)

CADIVOR_APP_ORIGIN = _normalize_origin(
    os.getenv(
        "CADIVOR_APP_ORIGIN",
        "https://bom-risk-checker-j9co3yumwgvqjumut24fxm.streamlit.app",
    ),
    "https://bom-risk-checker-j9co3yumwgvqjumut24fxm.streamlit.app",
)

# Backward-compatible alias used by older modules.
CADIVOR_MARKETING_URL = f"{CADIVOR_MARKETING_ORIGIN}/"


def marketing_url(path: str = "") -> str:
    """Build an absolute marketing-site URL."""
    clean_path = str(path or "").strip()
    if not clean_path:
        return f"{CADIVOR_MARKETING_ORIGIN}/"
    if clean_path.startswith(("http://", "https://", "mailto:")):
        return clean_path
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    return f"{CADIVOR_MARKETING_ORIGIN}{clean_path}"


def app_url(path: str = "", **params: Any) -> str:
    """Build an absolute authenticated-application URL."""
    clean_path = str(path or "").strip()
    base = CADIVOR_APP_ORIGIN if not clean_path else f"{CADIVOR_APP_ORIGIN}/{clean_path.lstrip('/')}"
    filtered = {
        key: str(value)
        for key, value in params.items()
        if value is not None and str(value).strip() != ""
    }
    if not filtered:
        return base
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode(filtered, quote_via=quote)}"


def app_auth_url(
    mode: str,
    *,
    source: str = "marketing",
    intent: str | None = None,
    plan: str | None = None,
) -> str:
    """Build a marketing-to-app authentication deep link."""
    params: dict[str, str] = {"auth": str(mode or "").strip().lower(), "source": source}
    if intent:
        params["intent"] = intent
    if plan:
        params["plan"] = plan
    return app_url("", **params)


def app_checkout_url(*, page: str = "", checkout: str = "success") -> str:
    """Build a Stripe checkout return URL preserving the session placeholder."""
    params = [f"checkout={checkout}", "session_id={CHECKOUT_SESSION_ID}"]
    if page:
        params.insert(0, f"page={quote(page)}")
    return f"{CADIVOR_APP_ORIGIN}/?{'&'.join(params)}"


def internal_app_href(page: str, **params: Any) -> str:
    """Build a same-tab in-app query link for Streamlit pages."""
    payload = {"page": page}
    payload.update(
        {
            key: str(value)
            for key, value in params.items()
            if value is not None and str(value).strip() != ""
        }
    )
    return "?" + urlencode(payload, quote_via=quote)
