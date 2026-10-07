"""Trusted product-photo URL handling and reusable Cadivor part imagery."""
from __future__ import annotations

from html import escape
from collections.abc import Mapping
from urllib.parse import quote, urlsplit, urlunsplit

_ALLOWED_IMAGE_HOSTS = (
    "mouser.com",
    "digikey.com",
    "newark.com",
    "element14.com",
    "farnell.com",
)
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_IMAGE_KEYS = (
    "PhotoUrl",
    "photoUrl",
    "photo_url",
    "ImagePath",
    "ImageURL",
    "ImageUrl",
    "imageUrl",
    "image_url",
    "PrimaryPhoto",
    "primaryPhoto",
    "url",
    "href",
)


def normalize_supplier_image_url(value: object, *, provider: str = "") -> str:
    """Return a safe HTTPS product-photo URL from supported distributor fields."""
    if isinstance(value, Mapping):
        for key in _IMAGE_KEYS:
            candidate = value.get(key)
            if candidate:
                normalized = normalize_supplier_image_url(candidate, provider=provider)
                if normalized:
                    return normalized

        base_name = str(value.get("baseName") or value.get("basename") or "").strip()
        if base_name and provider.strip().casefold() in {"newark", "element14", "farnell"}:
            # Newark's product-image endpoint uses this documented US locale path.
            safe_name = base_name.lstrip("/")
            if safe_name and not any(part in {".", ".."} for part in safe_name.split("/")):
                filename = quote(safe_name, safe="/-._~")
                candidate = (
                    "https://www.newark.com/productimages/standard/en_US/"
                    f"{filename}"
                )
                return normalize_supplier_image_url(candidate, provider=provider)
        return ""

    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw

    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"https", "http"} or not host:
        return ""
    if parsed.username or parsed.password or (port not in (None, 80, 443)):
        return ""
    if not any(host == domain or host.endswith("." + domain) for domain in _ALLOWED_IMAGE_HOSTS):
        return ""

    path_parts = parsed.path.split("/")
    if any(part in {".", ".."} for part in path_parts):
        return ""
    suffix = ""
    last_segment = path_parts[-1].casefold()
    if "." in last_segment:
        suffix = "." + last_segment.rsplit(".", 1)[-1]
        if suffix not in _IMAGE_EXTENSIONS:
            return ""

    # Force HTTPS even if an older provider record supplies an HTTP image path.
    netloc = host
    if port == 443:
        netloc = f"{host}:443"
    return urlunsplit(("https", netloc, parsed.path, parsed.query, ""))


def part_image_markup(image_url: object, part_number: object, *, size: int = 76) -> str:
    """Build escaped, accessible part-photo markup with an honest neutral fallback."""
    try:
        dimension = min(132, max(48, int(size)))
    except (TypeError, ValueError):
        dimension = 76
    mpn = str(part_number or "").strip() or "component"
    safe_mpn = escape(mpn, quote=True)
    image = normalize_supplier_image_url(image_url)
    if image:
        visual = (
            f'<img src="{escape(image, quote=True)}" alt="Product photo for {safe_mpn}" '
            'loading="lazy" decoding="async" referrerpolicy="no-referrer">'
        )
    else:
        visual = (
            '<span class="cv-part-photo__placeholder" aria-hidden="true">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            '<rect x="4" y="4" width="16" height="16" rx="3"/>'
            '<path d="M9 1v3m6-3v3M9 20v3m6-3v3M1 9h3m-3 6h3m16-6h3m-3 6h3"/>'
            '<path d="M9 9h6v6H9z"/></svg></span>'
        )
    label = f"Product photo for {safe_mpn}" if image else f"No supplier photo available for {safe_mpn}"
    return (
        f'<div class="cv-part-photo" style="--cv-part-photo-size:{dimension}px" '
        f'role="img" aria-label="{label}">{visual}</div>'
    )


__all__ = ["normalize_supplier_image_url", "part_image_markup"]
