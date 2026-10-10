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


ILLUSTRATION_LABEL = "Image for illustration purposes only"

# Existing family ids from component_family_profiles. Unlisted families use the generic drawing.
_KIND_BY_FAMILY = {
    "Capacitor": "capacitor",
    "Resistor": "resistor",
    "Inductor": "inductor",
    "Diode / protection": "diode",
    "Bipolar transistor": "transistor",
    "MOSFET": "transistor",
    "Regulator": "ic",
    "Operational amplifier": "ic",
    "Logic / interface IC": "ic",
    "MCU / processor": "ic",
    "FPGA / CPLD": "ic",
    "Connector / electromechanical": "connector",
    "Sensor": "sensor",
    "Switch": "switch",
}

_ILLUSTRATION_SVG = {
    "ic": (
        '<rect x="6" y="6" width="12" height="12" rx="2"/>'
        '<path d="M9 6V3m6 3V3M9 21v-3m6 3v-3M6 9H3m3 6H3m18-6h-3m3 6h-3"/>'
    ),
    "resistor": '<path d="M2 12h3l2-4 3 8 3-8 2 4h3l2-4 2 4h2"/>',
    "capacitor": '<path d="M8 4v16M16 4v16M4 12H8m8 0h8"/>',
    "connector": (
        '<rect x="3" y="7" width="10" height="10" rx="1"/>'
        '<path d="M13 10h8M13 14h8M6 7V4m4 3V4"/>'
    ),
    "diode": '<path d="M5 6l8 6-8 6zM13 6v12M18 7v10"/>',
    "transistor": '<path d="M8 4v16M8 8l8-3v4M8 16l8 3v-4M16 5v3m0 8v3"/>',
    "inductor": '<path d="M3 15c2-6 2-6 4 0s2 6 4 0 2 6 4 0 2 6 4 0"/>',
    "sensor": '<circle cx="12" cy="12" r="3"/><path d="M12 5v2m0 10v2M5 12h2m10 0h2M7 7l1.5 1.5M15.5 15.5 17 17M17 7l-1.5 1.5M8.5 15.5 7 17"/>',
    "switch": '<path d="M4 16h4l8-8h4M8 16a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm12-8a2 2 0 1 1-4 0 2 2 0 0 1 4 0z"/>',
    "generic": (
        '<rect x="4" y="6" width="16" height="12" rx="2"/>'
        '<path d="M8 10h3m2 0h3M8 14h8"/>'
    ),
}


def illustration_kind(part: object = None, category: object = None) -> str:
    """Map stored category text onto an illustration. Unknown text stays generic."""
    from src.component_family_profiles import infer_family_id

    payload: dict[str, str] = {}
    if isinstance(part, Mapping):
        for target, keys in (
            ("description", ("description_raw", "description", "Description", "part_description")),
            ("category", ("category_raw", "category", "Category")),
            ("architecture", ("architecture", "Architecture")),
            ("device_type", ("device_type", "Device Type", "device type")),
        ):
            for key in keys:
                value = part.get(key)
                if value is not None and str(value).strip():
                    payload[target] = str(value).strip()
                    break
    if category is not None and str(category).strip():
        payload.setdefault("category", str(category).strip())
    if not payload:
        return "generic"
    return _KIND_BY_FAMILY.get(infer_family_id(payload), "generic")


def part_image_markup(
    image_url: object,
    part_number: object,
    *,
    size: int = 76,
    category: object = None,
    part: object = None,
) -> str:
    """Supplier photo when the URL is trusted. Otherwise a labeled category illustration."""
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
        label = f"Product photo for {safe_mpn}"
        kind = ""
    else:
        kind = illustration_kind(part, category)
        drawing = _ILLUSTRATION_SVG.get(kind, _ILLUSTRATION_SVG["generic"])
        visual = (
            '<span class="cv-part-photo__placeholder" aria-hidden="true">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            f"{drawing}</svg></span>"
        )
        label = ILLUSTRATION_LABEL
    kind_attr = f' data-illustration="{escape(kind, quote=True)}"' if kind else ""
    return (
        f'<div class="cv-part-photo" style="--cv-part-photo-size:{dimension}px" '
        f'role="img" aria-label="{escape(label, quote=True)}" '
        f'title="{escape(label, quote=True)}"{kind_attr}>{visual}</div>'
    )


__all__ = [
    "ILLUSTRATION_LABEL",
    "attach_saved_component_images",
    "illustration_kind",
    "normalize_supplier_image_url",
    "part_image_markup",
]
def attach_saved_component_images(
    records: list[Mapping[str, object]] | None,
    saved_parts: list[Mapping[str, object]] | None,
) -> list[dict[str, object]]:
    """Attach a trusted saved photo to decisions by analysis and MPN.

    Unlinked decisions use a photo only when all matching saved rows agree on one
    trusted URL. This prevents an MPN shared by different records from receiving
    an arbitrary component photo.
    """
    image_keys = (
        "image_url", "product_image_url", "primary_image_url", "supplier_image_url",
        "photo_url", "PhotoUrl", "photoUrl", "ImageURL", "ImageUrl",
        "PrimaryPhoto", "Photo", "image", "photo",
    )
    mpn_keys = (
        "mpn", "MPN", "manufacturer_part_number", "part_number", "part number",
        "component",
    )
    metadata_keys = (
        "manufacturer", "description", "description_raw", "part_description",
        "category", "category_raw", "architecture", "device_type",
    )

    def _mpn(row: Mapping[str, object]) -> str:
        for key in mpn_keys:
            value = str(row.get(key) or "").strip()
            if value.casefold() not in {"", "nan", "none", "<na>"}:
                return " ".join(value.casefold().split())
        return ""

    def _analysis_id(row: Mapping[str, object]) -> str:
        value = str(row.get("analysis_id") or "").strip()
        return "" if value.casefold() in {"", "nan", "none", "<na>"} else value

    def _trusted_image(row: Mapping[str, object]) -> str:
        for key in image_keys:
            value = row.get(key)
            if value:
                image = normalize_supplier_image_url(value)
                if image:
                    return image
        return ""

    by_mpn: dict[str, list[Mapping[str, object]]] = {}
    for part in saved_parts or []:
        if not isinstance(part, Mapping):
            continue
        key = _mpn(part)
        if key:
            by_mpn.setdefault(key, []).append(part)

    enriched: list[dict[str, object]] = []
    for record in records or []:
        if not isinstance(record, Mapping):
            continue
        row = dict(record)
        candidates = by_mpn.get(_mpn(row), [])
        analysis_id = _analysis_id(row)
        exact = [
            part for part in candidates
            if analysis_id and _analysis_id(part) == analysis_id
        ]
        metadata_source = exact[0] if exact else None
        existing_image = _trusted_image(row)
        image_source = next((part for part in exact if _trusted_image(part)), None)

        if image_source is None and not existing_image:
            image_candidates = [part for part in candidates if _trusted_image(part)]
            unique_urls = {_trusted_image(part) for part in image_candidates}
            if len(unique_urls) == 1 and image_candidates:
                image_source = image_candidates[0]
                metadata_source = metadata_source or image_source
        if metadata_source is None and len(candidates) == 1:
            metadata_source = candidates[0]

        if not existing_image and image_source is not None:
            row["image_url"] = _trusted_image(image_source)
        if metadata_source is not None:
            for key in metadata_keys:
                value = metadata_source.get(key)
                current = row.get(key)
                if value not in (None, "") and current in (None, ""):
                    row[key] = value
        enriched.append(row)
    return enriched


