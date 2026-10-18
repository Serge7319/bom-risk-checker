"""Trusted product-photo URL handling and reusable Cadivor part imagery."""
from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from pathlib import Path
from collections.abc import Mapping
import re
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


ILLUSTRATION_LABEL = "Representative component image; actual part may vary"

# Existing family ids from component_family_profiles. Unlisted families use a
# neutral, unbranded package image rather than a chip glyph.
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
    "Relay": "relay",
    "Sensor": "sensor",
    "Switch": "switch",
    "Oscillator / crystal": "crystal",
    "Transformer": "transformer",
    "General electronic component": "generic",
}

# Saved analysis rows do not always retain a supplier category or description.
# A narrow set of manufacturer prefixes can still identify common families.
_MPN_FAMILY_PATTERNS = (
    (
        "Capacitor",
        re.compile(
            r"^(?:GRM|GRJ|GRT|CKG|CGA|CC\d{4}|CL\d{2}|C\d{4}[A-Z]|"
            r"T49[1245]|TAJ[A-Z]|TCJ[A-Z]|293D|EEU|ECA|EEE|ECJ|EMK|KGM|KCM|VJ\d{4}|MAL\d)",
            re.I,
        ),
    ),
    ("Resistor", re.compile(r"^(?:RC\d{4}|ERJ-|CRCW\d|MCR\d|RMCF|RK73|RT\d{4})", re.I)),
    ("Diode / protection", re.compile(r"^(?:1N\d{3,}|SS\d{2,}|BAV\d{2,}|MBR\d{2,}|PMEG\d+)", re.I)),
    ("MOSFET", re.compile(r"^(?:IRF\w+|AO\d{3,}|BSS\d{2,}|FDN\d+|SI\d{3,})", re.I)),
    ("Bipolar transistor", re.compile(r"^(?:2N\d{3,}|BC\d{2,}|MMBT\d+)", re.I)),
    ("Inductor", re.compile(r"^(?:LQH|LQM|LQG|SRR|XAL|NR\d{2,})", re.I)),
    ("MCU / processor", re.compile(r"^(?:STM32|ATMEGA|PIC\d|ESP32|RP2040)", re.I)),
    ("Regulator", re.compile(r"^(?:TPS\d|LM(?:2596|317|1117)|LD\d|MIC\d|AP\d{3,})", re.I)),
    ("Logic / interface IC", re.compile(r"^(?:MCP\d|MAX\d|SN\d|ADS\d|W25Q\d|PC\d{3,})", re.I)),
    # Generic MPN labels used in customer BOMs and demo files. These select
    # family illustrations only; they are not claims of exact product photos.
    ("Capacitor", re.compile(r"^CAP(?:[-_]|$)", re.I)),
    ("Resistor", re.compile(r"^RES(?:[-_]|$)", re.I)),
    ("Diode / protection", re.compile(r"^(?:DIO|LED)(?:[-_]|$)", re.I)),
    ("Connector / electromechanical", re.compile(r"^CON(?:[-_]|$)", re.I)),
    ("Logic / interface IC", re.compile(r"^IC(?:[-_]|$)", re.I)),
    ("MCU / processor", re.compile(r"^MCU(?:[-_]|$)", re.I)),
    ("Oscillator / crystal", re.compile(r"^OSC(?:[-_]|$)", re.I)),
    ("Regulator", re.compile(r"^REG(?:[-_]|$)", re.I)),
)

_ASSET_VARIANTS = {
    "capacitor": ("capacitor_smd", "capacitor_th"),
    "resistor": ("resistor_smd", "resistor_th"),
    "inductor": ("inductor_smd", "inductor_th"),
    "diode": ("diode_smd", "diode_th"),
    "transistor": ("transistor_smd", "transistor_th"),
    "ic": ("ic_smd", "ic_th"),
    "connector": ("connector_smd", "connector_th"),
    "relay": ("relay_smd", "relay_th"),
    "sensor": ("sensor_smd", "sensor_th"),
    "switch": ("switch_smd", "switch_th"),
    "crystal": ("crystal_smd", "crystal_th"),
    "transformer": ("transformer_smd", "transformer_th"),
    # The bundled generic PNGs depict specific transistor/diode packages.
    # Unknown families use neutral vector package art instead.
    "generic": ("", ""),
}
_THROUGH_HOLE = re.compile(
    r"\b(?:tht|through[\s-]?hole|pth|dip|pdip|to-\d{2,3}|axial|radial|leaded|hc-49)\b",
    re.IGNORECASE,
)
_SURFACE_MOUNT = re.compile(
    r"\b(?:smd|smt|surface[\s-]?mount|0[26]03|0805|1206|1210|2010|2512|qfn|qfp|soic|sot-\d+|sod-\d+|sma|smb|smc|bga|dfn|hc-49s)\b",
    re.IGNORECASE,
)
_PACKAGE_KEYS = (
    "package", "package_type", "package type", "package_case", "case_package",
    "case", "mounting_type", "mounting type", "mount_type", "mounting",
    "mounting_technology", "mount technology", "technology", "footprint",
)
_THROUGH_HOLE_KEYS = ("through_hole", "is_through_hole", "tht", "is_tht")
_SMD_KEYS = ("surface_mount", "is_surface_mount", "smd", "smt", "is_smd")


def _part_values(part: object) -> list[str]:
    if not isinstance(part, Mapping):
        return []
    keys = (
        "description_raw", "description", "Description", "part_description",
        "category_raw", "category", "Category", "architecture", "Architecture",
        "device_type", "Device Type", "device type", "manufacturer_part_number",
        "mpn", "MPN", "part_number", "part number",
    ) + _PACKAGE_KEYS
    return [str(part[key]).strip() for key in keys if part.get(key) not in (None, "")]


def _package_style(part: object) -> str:
    if isinstance(part, Mapping):
        for key in _THROUGH_HOLE_KEYS:
            value = str(part.get(key) or "").strip().casefold()
            if value in {"1", "true", "yes", "y", "through-hole", "tht"}:
                return "th"
        for key in _SMD_KEYS:
            value = str(part.get(key) or "").strip().casefold()
            if value in {"1", "true", "yes", "y", "surface-mount", "smd", "smt"}:
                return "smd"
        package_values = [
            str(part[key]).strip()
            for key in _PACKAGE_KEYS
            if part.get(key) not in (None, "")
        ]
        package_text = " ".join(package_values)
        if _THROUGH_HOLE.search(package_text):
            return "th"
        if _SURFACE_MOUNT.search(package_text):
            return "smd"
    descriptive_text = " ".join(_part_values(part))
    if _THROUGH_HOLE.search(descriptive_text):
        return "th"
    if _SURFACE_MOUNT.search(descriptive_text):
        return "smd"
    # Common electrolytic and radial capacitor descriptions imply leaded parts.
    if re.search(r"\\b(?:electrolytic|radial leads?)\\b", descriptive_text, re.IGNORECASE):
        return "th"
    return "smd"


def illustration_kind(
    part: object = None,
    category: object = None,
    part_number: object = None,
) -> str:
    """Map saved family/category text to a representative component image."""
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
    family = infer_family_id(payload) if payload else "General electronic component"
    mpn = ""
    if isinstance(part, Mapping):
        for key in ("manufacturer_part_number", "mpn", "MPN", "part_number", "part number"):
            candidate = str(part.get(key) or "").strip()
            if candidate:
                mpn = candidate
                break
    if not mpn:
        mpn = str(part_number or "").strip()
    for candidate_family, pattern in _MPN_FAMILY_PATTERNS:
        if pattern.search(mpn):
            # Confident manufacturer code prefixes beat stale generic metadata
            # such as a GRM MLCC that was stored with category "IC".
            family = candidate_family
            break
    if family == "General electronic component":
        category_text = str(payload.get("category") or "").strip().casefold()
        if category_text in {"ic", "integrated circuit", "integrated-circuit"}:
            family = "Logic / interface IC"
    return _KIND_BY_FAMILY.get(family, "generic")


@lru_cache(maxsize=32)
def _illustration_data_uri(asset_name: str) -> str:
    """Load a bundled, optimized PNG stored as base64 text for GitHub-safe writes."""
    asset_file = Path(__file__).resolve().parent / "component_images" / f"{asset_name}.png.b64"
    try:
        encoded = asset_file.read_text(encoding="ascii").strip()
        if not encoded:
            return ""
        base64.b64decode(encoded, validate=True)
    except (OSError, ValueError):
        return ""
    return f"data:image/png;base64,{encoded}"


def _asset_name(kind: str, part: object = None) -> str:
    variants = _ASSET_VARIANTS.get(kind) or _ASSET_VARIANTS["generic"]
    index = 1 if _package_style(part) == "th" else 0
    return variants[index]


def _svg_data_uri(kind: str, dimension: int) -> str:
    """Small visual safety fallback if a packaged photo asset is unavailable."""
    drawing = _ILLUSTRATION_SVG.get(kind, _ILLUSTRATION_SVG["generic"])
    palettes = {
        "ic": ("#eff6ff", "#dbeafe", "#2563eb"),
        "capacitor": ("#f5f3ff", "#e9d5ff", "#7c3aed"),
        "resistor": ("#fff7ed", "#fed7aa", "#c2410c"),
        "inductor": ("#f0fdfa", "#ccfbf1", "#0f766e"),
        "connector": ("#ecfeff", "#cffafe", "#0e7490"),
        "diode": ("#fff1f2", "#ffe4e6", "#be123c"),
        "transistor": ("#f0fdf4", "#dcfce7", "#15803d"),
        "sensor": ("#ecfeff", "#cffafe", "#0891b2"),
        "switch": ("#fffbeb", "#fef3c7", "#b45309"),
        "relay": ("#f8fafc", "#cbd5e1", "#334155"),
        "transformer": ("#fff7ed", "#fed7aa", "#9a3412"),
        "crystal": ("#f8fafc", "#cbd5e1", "#475569"),
        "generic": ("#f0f9ff", "#bae6fd", "#0369a1"),
    }
    background, border, foreground = palettes.get(kind, palettes["generic"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dimension}" height="{dimension}" viewBox="0 0 64 64">'
        f'<rect x="1" y="1" width="62" height="62" rx="12" fill="{background}" stroke="{border}" stroke-width="2"/>'
        f'<g transform="translate(20 20)" fill="none" stroke="{foreground}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        f'{drawing}</g></svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


_ILLUSTRATION_SVG = {
    "ic": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 6V3m6 3V3M9 21v-3m6 3v-3M6 9H3m3 6H3m18-6h-3m3 6h-3"/>',
    "resistor": '<path d="M2 12h3l2-4 3 8 3-8 2 4h3l2-4 2 4h2"/>',
    "capacitor": '<path d="M8 4v16M16 4v16M4 12H8m8 0h8"/>',
    "connector": '<rect x="3" y="7" width="10" height="10" rx="1"/><path d="M13 10h8M13 14h8M6 7V4m4 3V4"/>',
    "diode": '<path d="M5 6l8 6-8 6zM13 6v12M18 7v10"/>',
    "transistor": '<path d="M8 4v16M8 8l8-3v4M8 16l8 3v-4M16 5v3m0 8v3"/>',
    "inductor": '<path d="M3 15c2-6 2-6 4 0s2 6 4 0 2 6 4 0 2 6 4 0"/>',
    "sensor": '<circle cx="12" cy="12" r="3"/><path d="M12 5v2m0 10v2M5 12h2m10 0h2M7 7l1.5 1.5M15.5 15.5 17 17M17 7l-1.5 1.5M8.5 15.5 7 17"/>',
    "switch": '<path d="M4 16h4l8-8h4M8 16a2 2 0 1 1-4 0 2 2 0 0 1 4 0zm12-8a2 2 0 1 1-4 0 2 2 0 0 1 4 0z"/>',
    "relay": '<rect x="4" y="7" width="16" height="10" rx="2"/><path d="M7 4v3m10-3v3M7 17v3m10-3v3"/>',
    "transformer": '<path d="M6 6c4 0 4 12 0 12m12-12c-4 0-4 12 0 12M8 8h8m-8 8h8"/>',
    "crystal": '<rect x="8" y="5" width="8" height="14" rx="3"/><path d="M10 19v3m4-3v3"/>',
    "generic": '<rect x="7" y="8" width="10" height="8" rx="2"/><path d="M2 10h5m10 0h5M2 14h5m10 0h5"/>',
}


def _generic_component_svg(package_style: str, dimension: int) -> str:
    """Neutral two-terminal package art; never imply an IC for unknown parts."""
    if package_style == "th":
        drawing = (
            '<path d="M12 8V3m0 13v5" stroke="#a8b3c1" stroke-width="1.35"/>'
            '<rect x="7.7" y="7.5" width="8.6" height="9" rx="3" fill="#475569" stroke="#334155" stroke-width="1.1"/>'
            '<path d="M9.5 9.5h4.8" stroke="#aeb9c7" stroke-width=".8" stroke-linecap="round"/>'
        )
    else:
        drawing = (
            '<rect x="2.5" y="9" width="5" height="6" rx="1" fill="#c7d0db" stroke="#9aa8b8" stroke-width=".7"/>'
            '<rect x="16.5" y="9" width="5" height="6" rx="1" fill="#c7d0db" stroke="#9aa8b8" stroke-width=".7"/>'
            '<rect x="6.5" y="7" width="11" height="10" rx="2.1" fill="#475569" stroke="#334155" stroke-width="1.1"/>'
            '<path d="M8.7 9.4h6.1" stroke="#aeb9c7" stroke-width=".8" stroke-linecap="round"/>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{dimension}" height="{dimension}" viewBox="0 0 24 24">'
        '<rect x="1" y="1" width="22" height="22" rx="5" fill="#f5f7fa" stroke="#dbe3ec" stroke-width="1"/>'
        f'<g fill="none" stroke="#53657b" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{drawing}</g>'
        '</svg>'
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


def part_image_source(
    image_url: object,
    part_number: object,
    *,
    size: int = 64,
    category: object = None,
    part: object = None,
) -> str:
    """Return supplier photography first, then the bundled package illustration."""
    image = normalize_supplier_image_url(image_url)
    if image:
        return image
    try:
        dimension = min(132, max(48, int(size)))
    except (TypeError, ValueError):
        dimension = 64
    kind = illustration_kind(part, category, part_number)
    if kind == "generic":
        return _generic_component_svg(_package_style(part), dimension)
    asset_name = _asset_name(kind, part)
    asset = _illustration_data_uri(asset_name) if asset_name else ""
    return asset or _svg_data_uri(kind, dimension)


def part_image_markup(
    image_url: object,
    part_number: object,
    *,
    size: int = 76,
    category: object = None,
    part: object = None,
) -> str:
    """Use an exact supplier photo when available, otherwise a labeled family image."""
    try:
        dimension = min(132, max(48, int(size)))
    except (TypeError, ValueError):
        dimension = 76
    mpn = str(part_number or "").strip() or "component"
    safe_mpn = escape(mpn, quote=True)
    image = normalize_supplier_image_url(image_url)
    kind = ""
    if image:
        label = f"Product photo for {safe_mpn}"
        visual = (
            f'<img class="cv-part-photo__image" src="{escape(image, quote=True)}" '
            f'alt="{label}" loading="lazy" decoding="async" referrerpolicy="no-referrer" '
            'style="width:100%;height:100%;object-fit:contain;vertical-align:middle">'
        )
    else:
        kind = illustration_kind(part, category, part_number)
        label = ILLUSTRATION_LABEL
        if kind == "generic":
            source = _generic_component_svg(_package_style(part), dimension)
        else:
            asset_name = _asset_name(kind, part)
            source = _illustration_data_uri(asset_name) if asset_name else ""
        if source:
            visual = (
                f'<img class="cv-part-photo__image" src="{source}" '
                f'alt="{escape(label, quote=True)}" loading="lazy" decoding="async" '
                'style="width:100%;height:100%;object-fit:contain;vertical-align:middle">'
            )
        else:
            drawing = _ILLUSTRATION_SVG.get(kind, _ILLUSTRATION_SVG["generic"])
            visual = (
                '<span class="cv-part-photo__placeholder" aria-hidden="true">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
                f"{drawing}</svg></span>"
            )
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
    "part_image_source",
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
        "package", "package_type", "package type", "package_case", "case_package",
        "case", "mounting_type", "mounting type", "mount_type", "mounting",
        "mounting_technology", "mount technology", "technology", "footprint",
        "through_hole", "is_through_hole", "tht", "surface_mount", "is_surface_mount",
        "smd", "smt",
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



